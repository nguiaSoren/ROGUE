"""TargetPanel — multi-provider dispatch for one rendered attack × N trials.

Pipeline position (ROGUE_PLAN.md §A.23 / §10.1):

    instantiator.render(...)   ->   RenderedAttack
                                         |
                                         v
       TargetPanel.run_attack(rendered, config, n_trials=N)
                                         |
                                         v
                                list[ModelResponse]   ->   judge.py

Consumed by `scripts/reproduce_once.py` and the FastAPI `/api/reproduce`
endpoint. For each (RenderedAttack, DeploymentConfig) pair we issue
`n_trials` independent calls in parallel (asyncio.gather) so a single
breach run produces a bootstrap-able sample of model behaviour (§10.3:
breach-rate confidence intervals come from these N i.i.d. trials).

Provider routing is keyed off the `provider/model` prefix on
`DeploymentConfig.target_model`. The hackathon panel collapses onto two
SDKs (`openai` and `anthropic`) by routing Groq / OpenRouter through the
OpenAI-compatible chat-completions surface. Day-1 §10.1 markers tag the
spots that still need real `rogue.config.settings` wiring rather than the
direct `os.environ.get(...)` reads we use on Day 0.

Per-trial capture: response text, end-to-end latency (perf_counter delta),
prompt/completion token counts from the provider's usage block (0 if
absent), USD cost estimated from `_PRICE_PER_MILLION`, and a flat `error`
string that downstream §10.3 storage maps to `verdict=ERROR` /
`verdict=REFUSED` BreachResult rows when content-policy blocks fire.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from rogue.reproduce.instantiator import RenderedAttack
from rogue.schemas import DeploymentConfig

__all__ = ["ModelResponse", "TargetPanel", "supports_audio", "supports_image"]

_log = logging.getLogger(__name__)


# ---------- Multimodal capability gate (Step 0a) ----------
#
# Vision(image)-capable panel models, verified 2026-05-29 (see
# papers/MULTIMODAL_CONTEXT.md Step 0a). Membership is by full provider-prefixed
# id. `meta-llama/llama-3.1-8b-instruct` is deliberately ABSENT — it is text-only
# (vision is Llama 3.2 11B/90B), so dispatching an image to it would 400 and
# pollute the breach matrix as a fake "failure" rather than an honest
# modality-unsupported skip. Unknown models default to NOT capable so we never
# silently send an image to an unverified endpoint.
_IMAGE_CAPABLE_MODELS: frozenset[str] = frozenset(
    {
        "openai/gpt-5.4-nano",
        "openai/gpt-5.4",  # stretch tier
        "anthropic/claude-haiku-4-5",
        "anthropic/claude-sonnet-4-6",  # stretch tier
        "mistralai/mistral-small-2603",  # native multimodal
        "google/gemini-3.1-flash-lite",  # image parts work via the OpenRouter route
    }
)


def supports_image(target_model: str) -> bool:
    """True iff ``target_model`` accepts image input. See ``_IMAGE_CAPABLE_MODELS``.

    Used by ``TargetPanel.run_attack`` to skip-and-label (not error) an image
    attack aimed at a text-only model. Exported so the orchestration / dashboard
    layers can render an honest "modality-unsupported" cell rather than an ERROR.
    """
    return target_model in _IMAGE_CAPABLE_MODELS


# Audio(speech)-capable panel models. Verified 2026-05-29 (Step 0b: Gemini), then
# the audio panel was broadened 1→3 on 2026-06-04 (#1b follow-up — the multimodal
# harvest parked 5 audio techniques against a single audio target, so measuring
# audio breach/graduation needed more than one endpoint). All accept an
# OpenAI-compat `input_audio` block:
#   - google/gemini-3.1-flash-lite       — via OpenRouter (the original, proven route)
#   - mistralai/voxtral-small-24b-2507   — via OpenRouter (same route as Gemini)
#   - openai/gpt-audio-mini              — via OpenAI DIRECT (api.openai.com, native audio)
# Claude takes no audio (no Anthropic audio-input model exists on OpenRouter).
# Unknown models default to NOT capable (fail-safe), same as the image gate.
_AUDIO_CAPABLE_MODELS: frozenset[str] = frozenset(
    {
        "google/gemini-3.1-flash-lite",
        "mistralai/voxtral-small-24b-2507",
        "openai/gpt-audio-mini",
    }
)


def supports_audio(target_model: str) -> bool:
    """True iff ``target_model`` accepts audio input. See ``_AUDIO_CAPABLE_MODELS``.

    Audio analogue of ``supports_image`` — drives the same skip-and-label gate.
    """
    return target_model in _AUDIO_CAPABLE_MODELS


def _attach_audio_to_last_user(
    messages: list[dict[str, Any]],
    audio_b64: str,
    audio_format: str,
) -> list[dict[str, Any]]:
    """Return a copy of ``messages`` with ``audio_b64`` attached to the last user turn.

    OpenAI-compatible ``input_audio`` block (the only audio route in the panel —
    Gemini via OpenRouter). Text payload stays first; audio is the second part.
    System turns are untouched; a plain-string user content is required (a
    pre-built block list is left as-is for forward-compatibility).

        {"type": "input_audio", "input_audio": {"data": <b64>, "format": <fmt>}}
    """
    out: list[dict[str, Any]] = [dict(m) for m in messages]
    for i in range(len(out) - 1, -1, -1):
        if out[i].get("role") != "user":
            continue
        text = out[i].get("content", "")
        if not isinstance(text, str):
            return out
        out[i]["content"] = [
            {"type": "text", "text": text},
            {
                "type": "input_audio",
                "input_audio": {"data": audio_b64, "format": audio_format},
            },
        ]
        return out
    return out


def _attach_image_to_last_user(
    messages: list[dict[str, Any]],
    image_b64: str,
    media_type: str,
    *,
    provider: str,
) -> list[dict[str, Any]]:
    """Return a copy of ``messages`` with ``image_b64`` attached to the last user turn.

    The text payload is preserved as the first content part; the image is added
    as a second part using the provider-specific block schema. System turns are
    never touched (image blocks only belong in user turns). If there is no user
    turn (should not happen — the instantiator always emits one), the messages
    are returned unchanged.

    provider="openai"   -> {"type": "image_url", "image_url": {"url": "data:<mt>;base64,<b64>"}}
    provider="anthropic"-> {"type": "image", "source": {"type": "base64", "media_type": <mt>, "data": <b64>}}
    """
    out: list[dict[str, Any]] = [dict(m) for m in messages]
    for i in range(len(out) - 1, -1, -1):
        if out[i].get("role") != "user":
            continue
        text = out[i].get("content", "")
        # Only transform a plain-string content; if a caller already passed a
        # block list, leave it (idempotent / forward-compatible).
        if not isinstance(text, str):
            return out
        if provider == "openai":
            image_part: dict[str, Any] = {
                "type": "image_url",
                "image_url": {"url": f"data:{media_type};base64,{image_b64}"},
            }
        else:  # anthropic
            image_part = {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": image_b64,
                },
            }
        out[i]["content"] = [{"type": "text", "text": text}, image_part]
        return out
    return out


# ---------- Pricing table (USD per 1,000,000 tokens) ----------
#
# Sourced from STATUS panel-revision research in ROGUE_PLAN.md (2026-05-24).
# Tuple shape: (input_price_per_million, output_price_per_million).
# Groq / OpenRouter entries are approximate — they refresh more often than the
# big-three APIs, so treat the resulting `cost_usd` as a budget estimate, not
# a billing source of truth.
_PRICE_PER_MILLION: dict[str, tuple[float, float]] = {
    "openai/gpt-5.4-nano": (0.20, 1.25),
    "anthropic/claude-haiku-4-5": (1.00, 5.00),
    "anthropic/claude-opus-4-8": (15.00, 75.00),  # Opus-tier estimate — cost log only
    "groq/llama-3.1-8b-instant": (0.05, 0.08),  # Llama 3.1 8B Instant 128k — verified 2026-05-25 from Groq pricing page ($0.05/$0.08 confirmed). (Original ID `meta-llama/Llama-3.1-8B-Instruct` did NOT exist on Groq's public model list; corrected 2026-05-24 PM via GET /models.)
    "meta-llama/llama-3.1-8b-instruct": (0.02, 0.05),  # OpenRouter — locked 2026-05-26 as the canonical Llama slot (Groq dev-tier upgrade gated; OpenRouter is also cheaper at $0.02/$0.05 vs Groq's $0.05/$0.08, so this isn't just a fallback — it's the strictly-better choice. "Instruct" is the upstream Meta name; Groq's "Instant" suffix was Groq-branding for their inference-stack optimization, not a different fine-tune). Pricing verified from OpenRouter model page.
    "mistralai/mistral-small-2603": (0.15, 0.60),  # Mistral Small 4 via OpenRouter — verified 2026-05-25 ($0.15/$0.60). Pinned from `-latest` to the explicit 2026-03-17 release because vendor `-latest` tags can re-point mid-quarter.
    "google/gemini-3.1-flash-lite": (0.25, 1.50),
    # Audio panel expansion (2026-06-04, #1b follow-up) — OpenRouter/OpenAI verified prices:
    "mistralai/voxtral-small-24b-2507": (0.10, 0.30),  # Mistral Voxtral (audio) via OpenRouter
    "openai/gpt-audio-mini": (0.60, 2.40),  # OpenAI gpt-audio-mini (audio) via OpenAI direct
    # Stretch (Day 4 if budget permits):
    "openai/gpt-5.4": (2.50, 15.00),
    "anthropic/claude-sonnet-4-6": (3.00, 15.00),
}


def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Return USD cost estimate for a single call; 0.0 + warn on unknown model.

    We log-and-return-zero rather than raise so an unrecognised model (e.g. a
    stretch-tier model added mid-demo without a pricing entry) does not crash
    a full reproduction run — the cost just shows as $0 in the matrix and
    operations notices the missing entry from the warning.
    """
    prices = _PRICE_PER_MILLION.get(model)
    if prices is None:
        _log.warning(
            "no price entry for model %r in _PRICE_PER_MILLION; cost reported as 0.0",
            model,
        )
        return 0.0
    in_price, out_price = prices
    return (tokens_in * in_price + tokens_out * out_price) / 1_000_000


# ---------- Retry policy (per ROGUE_PLAN.md §9.2) ----------
#
# Retry on (a) network transients, (b) provider RateLimitError, and
# (c) HTTPStatusError with status_code in {429, 500, 502, 503, 504}.
# 4xx other than 429 are NOT retried — they are deterministic (bad
# request / content-policy refusal / auth failure) so re-issuing won't
# help. Final-exhausted RateLimitError + any non-retryable exception is
# caught in the outer `_call_*` wrapper and converted to a
# ModelResponse(error=...) — this preserves first-class accounting of
# rate-limit failures in the breach matrix while still giving tenacity
# a chance to recover on a transient 429.
# See §9.2 + tasks/LESSONS.md 2026-05-25 retry-policy completion.
_TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    asyncio.TimeoutError,
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.RemoteProtocolError,
)

# Hard per-request network timeout + bounded retries for EVERY target provider
# client. Added 2026-06-03 before a paid sweep: an un-timed-out OpenRouter request
# stalled an earlier run ~8h. With a ceiling, a wedged target call raises a
# (retryable) timeout instead of hanging the whole sweep. Mirrors the escalation
# planner's hardening — the panel hits the same OpenAI-compat endpoints.
_REQUEST_TIMEOUT_S = 90.0
_MAX_RETRIES = 2


def _is_retryable(exc: BaseException) -> bool:
    """Retry on (a) network transients, (b) provider RateLimitError, (c) 5xx/429
    HTTPStatusError (including provider-SDK APIStatusError shapes that wrap the
    raw HTTP status). 4xx other than 429 are NOT retried — they are
    deterministic (bad request, auth failure, content-policy refusal) and
    re-issuing won't help.
    See ROGUE_PLAN.md §9.2 + tasks/LESSONS.md 2026-05-25 retry-policy completion.
    """
    if isinstance(exc, _TRANSIENT_ERRORS):
        return True
    # Provider-SDK rate-limit + status-error shapes — both OpenAI and
    # Anthropic surface non-2xx as a typed APIStatusError subclass with a
    # `.status_code` attribute, NOT as a raw httpx.HTTPStatusError. Catching
    # RateLimitError directly preserves intent; the APIStatusError generic
    # arm picks up 5xx (InternalServerError, etc.) without us having to
    # enumerate every SDK exception class.
    try:
        from openai import APIStatusError as OpenAIAPIStatusError  # noqa: PLC0415
        from openai import RateLimitError as OpenAIRateLimit  # noqa: PLC0415
    except ImportError:
        OpenAIAPIStatusError = None  # type: ignore[assignment,misc]
        OpenAIRateLimit = None  # type: ignore[assignment,misc]
    try:
        from anthropic import APIStatusError as AnthropicAPIStatusError  # noqa: PLC0415
        from anthropic import RateLimitError as AnthropicRateLimit  # noqa: PLC0415
    except ImportError:
        AnthropicAPIStatusError = None  # type: ignore[assignment,misc]
        AnthropicRateLimit = None  # type: ignore[assignment,misc]
    for klass in (OpenAIRateLimit, AnthropicRateLimit):
        if klass is not None and isinstance(exc, klass):
            return True
    for klass in (OpenAIAPIStatusError, AnthropicAPIStatusError):
        if klass is not None and isinstance(exc, klass):
            status = getattr(exc, "status_code", None)
            if status in {429, 500, 502, 503, 504}:
                return True
    # HTTPStatusError fallback — covers anything raised via raise_for_status()
    # plus provider SDKs that surface 5xx as a generic httpx error.
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return False


# ---------- Output model ----------


class ModelResponse(BaseModel):
    """One target-model trial result. Immutable; one per (rendered, cfg, trial).

    `content` is the model's response text — empty string when `error` is set.
    `error` is None on success; a short string on a recordable failure
    (content-policy block, rate-limit-exhausted, network refusal). Downstream
    §10.3 storage maps non-None `error` to BreachResult.verdict=ERROR, and a
    content-policy block specifically is a valid REFUSED outcome per §10.1.
    """

    content: str
    latency_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    error: str | None
    trial_index: int
    temperature: float

    model_config = {"frozen": True}


# ---------- The panel ----------


class TargetPanel:
    """Dispatches a RenderedAttack against a DeploymentConfig over N trials.

    One instance is safe to share across an entire reproduction run: each
    provider client is constructed lazily on first use (so importing this
    module never requires API keys), and the per-call state lives entirely
    in `_dispatch_one`.
    """

    def __init__(self) -> None:
        # Lazy provider clients — mirrors the precedent in
        # `extract/extraction_agent.py`. None until first use; construction is
        # deferred so the module is importable without API keys present.
        self._openai_client: Any | None = None
        self._anthropic_client: Any | None = None
        self._groq_client: Any | None = None
        self._openrouter_client: Any | None = None

    async def aclose(self) -> None:
        """Release every lazy-init provider client. Idempotent.

        Callers (e.g. ``scripts/reproduce_once.py``) should invoke this in
        a ``finally:`` block at the end of a sweep so asyncio doesn't log
        unclosed-transport warnings on process exit. The underlying SDK
        clients (`AsyncOpenAI` for the 4 OpenAI-compat endpoints +
        `AsyncAnthropic`) each carry an `httpx.AsyncClient` that needs
        explicit teardown. Mirrors :meth:`BrightDataClient.aclose`.
        """
        for attr in (
            "_openai_client",
            "_anthropic_client",
            "_groq_client",
            "_openrouter_client",
        ):
            client = getattr(self, attr, None)
            if client is None:
                continue
            close_fn = getattr(client, "close", None)
            if close_fn is None:
                continue
            try:
                # Both AsyncOpenAI and AsyncAnthropic expose `close()` as
                # an awaitable; await defensively.
                result = close_fn()
                if result is not None and hasattr(result, "__await__"):
                    await result
            except Exception:  # pragma: no cover — cleanup must never raise
                pass
            setattr(self, attr, None)

    # ----- Construction -----

    @classmethod
    def from_env(cls) -> TargetPanel:
        """Symmetric to `BrightDataClient.from_env()` — returns a ready panel.

        No env-var assertions today: the lazy provider clients only read keys
        when an actual dispatch fires, so a partially-configured environment
        (e.g. only OPENAI_API_KEY set) still imports and constructs cleanly.
        The first call that needs a missing key surfaces the auth error from
        the provider SDK itself, which is the clearest possible signal.
        """
        # IMPLEMENT Day 1 §10.1 — once `rogue.config.settings` (§A.3) lands,
        # this is where we validate required keys are present up-front and
        # pass them into provider-client constructors explicitly rather than
        # relying on each SDK's default env-var pickup.
        return cls()

    # ----- Public API -----

    async def run_attack(
        self,
        rendered: RenderedAttack,
        config: DeploymentConfig,
        temperature: float = 0.7,
        n_trials: int = 5,
    ) -> list[ModelResponse]:
        """Fan out `n_trials` independent calls; return list ordered by trial_index.

        Temperature is varied across trials as `temperature + 0.1 * i` capped
        at 1.5. Rationale: §10.3's breach-rate bootstrap wants i.i.d.-ish
        samples per (attack, config), but identical temperature on a
        determinism-leaning provider (e.g. some OpenRouter routes pin seeds)
        can collapse the sample to a single response. A small monotonic walk
        guarantees variation without straying so far from the operator-chosen
        baseline that we're testing a different attack at trial N than at
        trial 0. The cap at 1.5 keeps us inside every panel provider's
        accepted range (OpenAI tops out at 2.0; Anthropic at 1.0 historically
        but tolerates up to 1.0+ in newer SDKs; 1.5 is the safe shared ceiling).

        Multimodal gate (Step 0a): if the rendered attack carries an image but
        the target model is not image-capable, we return an EMPTY list rather
        than dispatching — an image sent to a text-only model 400s, which the
        orchestrator would otherwise record as a fake ERROR cell. An empty
        result is the honest "modality-unsupported" signal; the caller simply
        produces no breach rows for that (attack, config) pair. See
        papers/MULTIMODAL_CONTEXT.md Step 0a + `supports_image`.
        """
        if rendered.image_b64 is not None and not supports_image(config.target_model):
            _log.info(
                "skip: image attack vs text-only model %s — modality_unsupported "
                "(not an error; no trials dispatched)",
                config.target_model,
            )
            return []
        if rendered.audio_b64 is not None and not supports_audio(config.target_model):
            _log.info(
                "skip: audio attack vs non-audio model %s — modality_unsupported "
                "(not an error; no trials dispatched)",
                config.target_model,
            )
            return []
        temperatures = [min(temperature + 0.1 * i, 1.5) for i in range(n_trials)]
        coros = [
            self._dispatch_one(rendered, config, trial_index=i, temperature=t)
            for i, t in enumerate(temperatures)
        ]
        # NOTE Day-3 (§11.3 backfill): this gather is bounded by n_trials (default 5)
        # — fine for Day 0/1 ad-hoc testing. On the Day-3 full backfill, the OUTER
        # loop over (canonical_primitives × deployment_configs) in
        # `scripts/reproduce_once.py` must wrap its fan-out in an
        # `asyncio.Semaphore(10)` (tune to provider rate limits); otherwise the
        # composition is ~200–400 primitives × 5 configs × 5 trials = 1k–2k
        # concurrent calls and providers will start 429-ing in cascades. Do NOT
        # add the semaphore in here — per-call concurrency stays bounded; only
        # the fan-out needs the cap. See ROGUE_PLAN.md §11.3.
        responses = await asyncio.gather(*coros)
        # asyncio.gather preserves order, which equals trial_index order here,
        # but we sort defensively in case a future refactor changes the call
        # shape (e.g. as_completed) — the downstream judge keys on trial_index.
        return sorted(responses, key=lambda r: r.trial_index)

    # ----- Internals -----

    async def _dispatch_one(
        self,
        rendered: RenderedAttack,
        config: DeploymentConfig,
        trial_index: int,
        temperature: float,
    ) -> ModelResponse:
        """Route a single trial to the right provider based on target_model prefix."""
        model_id = config.target_model

        if model_id.startswith("openai/"):
            bare_model = model_id.split("/", 1)[1]
            return await self._call_openai_compat(
                base_url="https://api.openai.com/v1",
                api_key=os.environ.get("OPENAI_API_KEY"),
                model=bare_model,
                messages=rendered.messages,
                temperature=temperature,
                trial_index=trial_index,
                client_attr="_openai_client",
                price_key=model_id,
                image_b64=rendered.image_b64,
                image_media_type=rendered.image_media_type,
                audio_b64=rendered.audio_b64,
                audio_format=rendered.audio_format,
            )
        if model_id.startswith("groq/"):
            # Groq exposes models via an OpenAI-compatible endpoint. Strip the
            # `groq/` prefix and send the bare model ID (e.g. `llama-3.1-8b-instant`)
            # which is what Groq's `GET /models` endpoint actually exposes.
            # (Corrected 2026-05-24 PM: original code branched on `meta-llama/`,
            # which paired with the wrong panel ID; both bug sites fixed in lockstep.)
            #
            # DEAD CODE — kept intentionally 2026-05-26. The Llama panel slot
            # moved off Groq to OpenRouter (Groq dev-tier upgrade gated +
            # OpenRouter is strictly cheaper at $0.02/$0.05 vs Groq's
            # $0.05/$0.08). No `DeploymentConfig` in the codebase uses a
            # `groq/...` model_id today, so this branch never runs in
            # production. The path is preserved so a future task can opt
            # back in with a one-line panel edit if Groq ships a unique
            # model (e.g. their inference-stack-optimized variants) we
            # want to compare against. See tasks/LESSONS.md 2026-05-26.
            bare_model = model_id.split("/", 1)[1]
            return await self._call_openai_compat(
                base_url="https://api.groq.com/openai/v1",
                api_key=os.environ.get("GROQ_API_KEY"),
                model=bare_model,
                messages=rendered.messages,
                temperature=temperature,
                trial_index=trial_index,
                client_attr="_groq_client",
                price_key=model_id,
            )
        if model_id.startswith(("mistralai/", "google/", "meta-llama/")):
            # OpenRouter routes by the FULL "provider/model" string — keep the
            # prefix here (do not strip) so e.g. `mistralai/mistral-small-2603`
            # or `meta-llama/llama-3.1-8b-instruct` reaches the right upstream.
            # `meta-llama/` was added 2026-05-26 as the OpenRouter fallback for
            # the Llama panel slot when Groq's developer-tier upgrade is
            # temporarily unavailable (see tasks/LESSONS.md 2026-05-26 entry).
            return await self._call_openai_compat(
                base_url="https://openrouter.ai/api/v1",
                api_key=os.environ.get("OPENROUTER_API_KEY"),
                model=model_id,
                messages=rendered.messages,
                temperature=temperature,
                trial_index=trial_index,
                client_attr="_openrouter_client",
                price_key=model_id,
                image_b64=rendered.image_b64,
                image_media_type=rendered.image_media_type,
                audio_b64=rendered.audio_b64,
                audio_format=rendered.audio_format,
            )
        if model_id.startswith("anthropic/"):
            bare_model = model_id.split("/", 1)[1]
            return await self._call_anthropic(
                model=bare_model,
                messages=rendered.messages,
                temperature=temperature,
                trial_index=trial_index,
                price_key=model_id,
                image_b64=rendered.image_b64,
                image_media_type=rendered.image_media_type,
            )

        raise NotImplementedError(f"unrouted provider: {model_id}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    async def _do_openai_compat_call(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        client_attr: str,
    ) -> Any:
        """Inner retried call — raises on failure so tenacity sees the exception.

        Splitting this from the outer wrapper is load-bearing: the outer
        wrapper catches RateLimitError and converts it to a structured
        ModelResponse, but a caught-and-handled exception never propagates
        to tenacity. By raising here, we let tenacity retry transient 429s
        (per `_is_retryable`) before the outer wrapper records the final
        exhaustion as `rate_limit_exhausted` on the ModelResponse.
        """
        # IMPLEMENT Day 1 §10.1 — when `rogue.config.settings` lands, drop the
        # bare `os.environ.get` reads in `_dispatch_one` and let the settings
        # loader validate keys at startup. Today we accept None and let the
        # SDK raise the clearer auth error on first call.
        from openai import AsyncOpenAI  # noqa: PLC0415

        client = getattr(self, client_attr)
        if client is None:
            client = AsyncOpenAI(
                base_url=base_url, api_key=api_key,
                timeout=_REQUEST_TIMEOUT_S, max_retries=_MAX_RETRIES,
            )
            setattr(self, client_attr, client)

        return await client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
        )

    async def _call_openai_compat(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        trial_index: int,
        client_attr: str,
        price_key: str,
        image_b64: str | None = None,
        image_media_type: str = "image/png",
        audio_b64: str | None = None,
        audio_format: str = "wav",
    ) -> ModelResponse:
        """Single call against any OpenAI-compatible chat-completions endpoint.

        Used for OpenAI proper, Groq, and OpenRouter (which fronts Mistral +
        Google for us). The `client_attr` parameter names the instance slot
        the AsyncOpenAI client is cached on so the four endpoints don't share
        a single client (different base_urls / api_keys).

        When `image_b64` is set (Step 0a), the image is attached to the last
        user turn as an OpenAI-format `image_url` data-URI block before dispatch.
        When `audio_b64` is set (Step 0b), an `input_audio` block is attached
        instead. The OpenRouter route passes either through to Gemini / Mistral
        unchanged.

        Retry policy lives on `_do_openai_compat_call` (see `_is_retryable`).
        Post-retry RateLimitError, non-retryable BadRequestError, and any
        bubbled HTTPStatusError are converted to a ModelResponse with
        `error` set — they are first-class outcomes for the breach matrix
        (REFUSED-at-provider / budget-exhaust signal), not infrastructure
        failures.
        """
        from openai import APIStatusError, BadRequestError, RateLimitError  # noqa: PLC0415

        call_messages: list[dict[str, Any]] = list(messages)
        if image_b64 is not None:
            call_messages = _attach_image_to_last_user(
                call_messages, image_b64, image_media_type, provider="openai"
            )
        if audio_b64 is not None:
            call_messages = _attach_audio_to_last_user(
                call_messages, audio_b64, audio_format
            )

        t0 = time.perf_counter()
        try:
            response = await self._do_openai_compat_call(
                base_url=base_url,
                api_key=api_key,
                model=model,
                messages=call_messages,
                temperature=temperature,
                client_attr=client_attr,
            )
        except RateLimitError as e:
            # All 3 retries exhausted on 429 — record as structured failure.
            latency_ms = int((time.perf_counter() - t0) * 1000)
            return ModelResponse(
                content="",
                latency_ms=latency_ms,
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                error=f"rate_limit_exhausted: {e}",
                trial_index=trial_index,
                temperature=temperature,
            )
        except BadRequestError as e:
            # 4xx — NOT retried (predicate returns False for non-429 4xx).
            # Content-policy refusal or genuine bad request. Record + move on.
            latency_ms = int((time.perf_counter() - t0) * 1000)
            return ModelResponse(
                content="",
                latency_ms=latency_ms,
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                error=f"content_policy_or_bad_request: {e}",
                trial_index=trial_index,
                temperature=temperature,
            )
        except APIStatusError as e:
            # 5xx persistent failure after retries (OpenAI SDK surfaces 5xx
            # as APIStatusError subclasses — InternalServerError etc. — NOT
            # as raw httpx.HTTPStatusError). Record as structured.
            latency_ms = int((time.perf_counter() - t0) * 1000)
            status = getattr(e, "status_code", "unknown")
            return ModelResponse(
                content="",
                latency_ms=latency_ms,
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                error=f"http_status_{status}: {e}",
                trial_index=trial_index,
                temperature=temperature,
            )
        except httpx.HTTPStatusError as e:
            # Raw httpx HTTPStatusError that bubbled past the SDK layer
            # (rare; covers any caller that uses the bare httpx path).
            latency_ms = int((time.perf_counter() - t0) * 1000)
            return ModelResponse(
                content="",
                latency_ms=latency_ms,
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                error=f"http_status_{e.response.status_code}: {e}",
                trial_index=trial_index,
                temperature=temperature,
            )
        latency_ms = int((time.perf_counter() - t0) * 1000)

        # `usage` is optional in the OpenAI-compat spec — some OpenRouter
        # routes omit it. Default to 0 rather than crashing.
        usage = getattr(response, "usage", None)
        tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
        tokens_out = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0

        # `choices[0].message.content` is the canonical text slot. None can
        # appear on tool-call-only responses; coerce to empty string so the
        # downstream judge always gets a str.
        content = ""
        if response.choices:
            message = response.choices[0].message
            content = getattr(message, "content", None) or ""

        return ModelResponse(
            content=content,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=_estimate_cost(price_key, tokens_in, tokens_out),
            error=None,
            trial_index=trial_index,
            temperature=temperature,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    async def _do_anthropic_call(
        self,
        *,
        model: str,
        anthropic_temp: float,
        system_prompt: str,
        chat_messages: list[dict[str, Any]],
    ) -> Any:
        """Inner retried call — raises on failure so tenacity sees the exception.

        Mirrors `_do_openai_compat_call` — see that docstring for the load-
        bearing rationale (outer wrapper catches post-retry exhaustion).
        """
        # IMPLEMENT Day 1 §10.1 — same settings-loader caveat as
        # `_call_openai_compat`. Day 0 we rely on the SDK's default env
        # pickup of `ANTHROPIC_API_KEY` so the module imports cleanly.
        from anthropic import AsyncAnthropic  # noqa: PLC0415

        if self._anthropic_client is None:
            self._anthropic_client = AsyncAnthropic(
                timeout=_REQUEST_TIMEOUT_S, max_retries=_MAX_RETRIES,
            )

        return await self._anthropic_client.messages.create(
            model=model,
            max_tokens=4096,
            temperature=anthropic_temp,
            system=system_prompt if system_prompt else "",
            messages=chat_messages,  # type: ignore[arg-type]
        )

    async def _call_anthropic(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        trial_index: int,
        price_key: str,
        image_b64: str | None = None,
        image_media_type: str = "image/png",
    ) -> ModelResponse:
        """Single call against the Anthropic Messages API.

        Anthropic takes the system prompt as a top-level `system=` kwarg, not
        as an inline `{"role": "system"}` entry. We split the rendered messages
        accordingly: any leading system message(s) are concatenated into the
        `system` kwarg, and the remaining user/assistant turns are forwarded
        as the `messages` payload. The instantiator only ever emits at most
        one leading system message today, but we tolerate >1 defensively.

        When `image_b64` is set (Step 0a), the image is attached to the last
        user turn as an Anthropic-format `image` block (`source.type="base64"`)
        after the system/chat split — image blocks belong only in user turns.

        Retry policy lives on `_do_anthropic_call` (see `_is_retryable`).
        Post-retry exceptions are converted to structured ModelResponse here.
        """
        from anthropic import APIStatusError, BadRequestError, RateLimitError  # noqa: PLC0415

        # Separate system messages from the chat turns. Concatenate with
        # double-newline so multi-system inputs (rare but possible) round-trip
        # without losing structure.
        system_parts: list[str] = []
        chat_messages: list[dict[str, Any]] = []
        for msg in messages:
            if msg.get("role") == "system":
                system_parts.append(msg.get("content", ""))
            else:
                chat_messages.append(msg)
        system_prompt = "\n\n".join(p for p in system_parts if p)

        # Anthropic requires at least one non-system message; the instantiator
        # guarantees this today, but assert defensively so a future regression
        # surfaces as a clear ValueError rather than an opaque 400 from the API.
        if not chat_messages:
            raise ValueError(
                "anthropic dispatch: no non-system messages in RenderedAttack"
            )

        if image_b64 is not None:
            chat_messages = _attach_image_to_last_user(
                chat_messages, image_b64, image_media_type, provider="anthropic"
            )

        # Cap temperature at 1.0 for Anthropic — the SDK rejects higher values
        # on some model lines. We document the panel-level cap as 1.5 elsewhere
        # but clamp per-provider here to keep dispatches successful.
        anthropic_temp = min(temperature, 1.0)

        t0 = time.perf_counter()
        try:
            response = await self._do_anthropic_call(
                model=model,
                anthropic_temp=anthropic_temp,
                system_prompt=system_prompt,
                chat_messages=chat_messages,
            )
        except RateLimitError as e:
            # All 3 retries exhausted on 429 — record as structured failure.
            latency_ms = int((time.perf_counter() - t0) * 1000)
            return ModelResponse(
                content="",
                latency_ms=latency_ms,
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                error=f"rate_limit_exhausted: {e}",
                trial_index=trial_index,
                temperature=temperature,
            )
        except BadRequestError as e:
            # Anthropic surfaces content-policy blocks as BadRequestError too;
            # same handling as the OpenAI-compat branch — REFUSED-style outcome.
            latency_ms = int((time.perf_counter() - t0) * 1000)
            return ModelResponse(
                content="",
                latency_ms=latency_ms,
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                error=f"content_policy_or_bad_request: {e}",
                trial_index=trial_index,
                temperature=temperature,
            )
        except APIStatusError as e:
            # 5xx persistent failure after retries (Anthropic SDK surfaces
            # 5xx as APIStatusError subclasses, not raw httpx errors).
            latency_ms = int((time.perf_counter() - t0) * 1000)
            status = getattr(e, "status_code", "unknown")
            return ModelResponse(
                content="",
                latency_ms=latency_ms,
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                error=f"http_status_{status}: {e}",
                trial_index=trial_index,
                temperature=temperature,
            )
        except httpx.HTTPStatusError as e:
            # Raw httpx HTTPStatusError fallback (covers anything that
            # bubbles past the SDK layer as a plain httpx error).
            latency_ms = int((time.perf_counter() - t0) * 1000)
            return ModelResponse(
                content="",
                latency_ms=latency_ms,
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                error=f"http_status_{e.response.status_code}: {e}",
                trial_index=trial_index,
                temperature=temperature,
            )
        latency_ms = int((time.perf_counter() - t0) * 1000)

        usage = getattr(response, "usage", None)
        tokens_in = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
        tokens_out = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0

        # Anthropic returns a list of content blocks; concatenate every text
        # block so multi-block responses (rare for chat-only calls but legal)
        # round-trip into a single string for the judge.
        content_parts: list[str] = []
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", None) == "text":
                content_parts.append(getattr(block, "text", ""))
        content = "".join(content_parts)

        return ModelResponse(
            content=content,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=_estimate_cost(price_key, tokens_in, tokens_out),
            error=None,
            trial_index=trial_index,
            temperature=temperature,
        )
