"""TargetPanel — multi-provider dispatch for one rendered attack × N trials.

Pipeline position (ROGUE_PLAN.md §A.23 / §10.1):

    instantiator.render(...)   ->   RenderedAttack
                                         |
                                         v
       TargetPanel.run_attack(rendered, config, n_trials=N)
                                         |
                                         v
                                list[ModelResponse]   ->   judge.py

Consumed by `scripts/reproduce/reproduce_once.py` and the FastAPI `/api/reproduce` endpoint. For each
(RenderedAttack, DeploymentConfig) pair we issue `n_trials` independent calls in parallel
(asyncio.gather) so a single breach run produces a bootstrap-able sample of model behaviour (§10.3).

**Week-2 migration.** Provider-specific dispatch (request shaping, the OpenAI/Anthropic SDK calls,
retry, response parsing, cost) now lives behind ``rogue.adapters.TargetAdapter``. This module is the
dispatch *layer*: it maps a ``DeploymentConfig.target_model`` prefix to a registered adapter, builds a
provider-neutral ``CanonicalMessage`` list, calls ``adapter.invoke(...)``, and projects the canonical
``InvocationResult`` (or a typed ``AdapterError``) back onto the legacy ``ModelResponse`` its callers
expect. There are no provider SDK imports here anymore — routing keys on a small prefix→adapter map,
never on provider behavior.

Per-trial capture is unchanged: response text, end-to-end latency, prompt/completion tokens, USD cost
(now sourced from ``adapters.model_specs``), and a flat ``error`` string that downstream §10.3 storage
maps to ``verdict=ERROR`` / ``verdict=REFUSED`` rows. The ``rate_limit_exhausted`` /
``content_policy_or_bad_request`` / ``http_status_<n>`` error tags are preserved verbatim.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any

from pydantic import BaseModel

from rogue.adapters import AdapterConfig, model_specs, registry
from rogue.core import CanonicalMessage, ImageBlock, MessageRole, from_legacy_messages
from rogue.core.content_blocks import AudioBlock
from rogue.core.errors import (
    AdapterError,
    AuthenticationError,
    ContentPolicyError,
    ProviderError,
    RateLimitError,
)
from rogue.reproduce.instantiator import RenderedAttack
from rogue.schemas import DeploymentConfig

__all__ = ["ModelResponse", "TargetPanel", "supports_audio", "supports_image"]

_log = logging.getLogger(__name__)


# ---------- Multimodal capability gate (Step 0a/0b) ----------
#
# Modality capability now lives in ``adapters.model_specs`` (the single source consolidating the old
# ``_IMAGE_CAPABLE_MODELS`` / ``_AUDIO_CAPABLE_MODELS`` frozensets). These thin wrappers are retained
# because the orchestration / dashboard / scripts import them by name to render an honest
# "modality-unsupported" skip rather than a fake ERROR cell. Unknown models default to NOT capable.


def supports_image(target_model: str) -> bool:
    """True iff ``target_model`` accepts image input (delegates to ``adapters.model_specs``)."""
    return model_specs.supports_image(target_model)


def supports_audio(target_model: str) -> bool:
    """True iff ``target_model`` accepts audio input (delegates to ``adapters.model_specs``)."""
    return model_specs.supports_audio(target_model)


# ---------- Provider routing (prefix -> registered adapter name) ----------
#
# The dispatch layer's one legitimate place to map a model id to an adapter. This is selection, not
# behavior-branching: every route resolves to a `registry.create(provider, ...)` call and the panel
# then talks only to the TargetAdapter interface. `mistralai/`, `google/`, `meta-llama/` all route to
# OpenRouter (the OpenAI-compatible surface), exactly as before. `groq/` is retained but unused.
_PROVIDER_ROUTES: tuple[tuple[str, str], ...] = (
    ("openai/", "openai"),
    ("groq/", "groq"),
    ("mistralai/", "openrouter"),
    ("google/", "openrouter"),
    ("meta-llama/", "openrouter"),
    ("anthropic/", "anthropic"),
)


def _resolve_provider(model_id: str) -> str:
    """Map a ``provider/model`` id to a registered adapter name. Raises for an unrouted prefix."""
    for prefix, provider in _PROVIDER_ROUTES:
        if model_id.startswith(prefix):
            return provider
    raise NotImplementedError(f"unrouted provider: {model_id}")


# ---------- Output model ----------


class ModelResponse(BaseModel):
    """One target-model trial result. Immutable; one per (rendered, cfg, trial).

    `content` is the model's response text — empty string when `error` is set. `error` is None on
    success; a short string on a recordable failure (content-policy block, rate-limit-exhausted,
    provider error). Downstream §10.3 storage maps non-None `error` to BreachResult.verdict=ERROR,
    and a content-policy block specifically is a valid REFUSED outcome per §10.1.
    """

    content: str
    latency_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    error: str | None
    trial_index: int
    temperature: float
    # The reasoning trace (thinking tokens) when the target exposes one; "" otherwise. Carried
    # separately from `content` (the answer) so ROGUE can scan the hidden scratchpad for leakage
    # (Leaky Thoughts, 2506.15674) without changing how the answer is judged.
    reasoning: str = ""

    model_config = {"frozen": True}


# ---------- The panel ----------


class TargetPanel:
    """Dispatches a RenderedAttack against a DeploymentConfig over N trials, via TargetAdapters.

    One instance is safe to share across a whole reproduction run: each (provider, model) adapter is
    constructed lazily on first use and cached (the adapter in turn lazily builds its provider client),
    so importing this module never requires API keys.
    """

    def __init__(self, *, adapter_extra: dict[str, Any] | None = None) -> None:
        # Cache one adapter per (provider, model_id). The adapter owns its provider client + retry.
        self._adapters: dict[tuple[str, str], Any] = {}
        # Extra config merged into every AdapterConfig.extra — a DI seam for tests (e.g. inject a
        # mocked provider client via {"client": ...}); empty in production.
        self._adapter_extra: dict[str, Any] = dict(adapter_extra or {})

    async def aclose(self) -> None:
        """Release every cached adapter (and its provider client). Idempotent.

        Callers (e.g. ``scripts/reproduce/reproduce_once.py``) should invoke this in a ``finally:`` so asyncio
        doesn't log unclosed-transport warnings on process exit.
        """
        for adapter in self._adapters.values():
            try:
                await adapter.aclose()
            except Exception:  # pragma: no cover — cleanup must never raise
                pass
        self._adapters.clear()

    # ----- Construction -----

    @classmethod
    def from_env(cls) -> TargetPanel:
        """Symmetric to ``BrightDataClient.from_env()`` — returns a ready panel.

        No env-var assertions: adapters only read keys when an actual dispatch fires, so a
        partially-configured environment still constructs cleanly. The first call needing a missing
        key surfaces the provider auth error.
        """
        return cls()

    # ----- Public API -----

    @staticmethod
    def modality_skip_reason(
        rendered: RenderedAttack, config: DeploymentConfig
    ) -> str | None:
        """Why this (rendered, config) pair would be skipped for modality, or None if it dispatches.

        Returns a short human-readable reason string when ``run_attack`` would skip the pair
        (image attack vs a text-only target, audio attack vs a non-audio target), else ``None``.
        Callers (``scan.py`` / ``endpoint_scan.py``) use this to surface an honest "skipped: target
        not multimodal" finding instead of silently producing zero rows — the skip is a real signal
        (you tested a media attack against a model that can't even read it), not a no-op.
        """
        if rendered.image_b64 is not None and not supports_image(config.target_model):
            return f"target not multimodal (image attack vs text-only model {config.target_model})"
        if rendered.audio_b64 is not None and not supports_audio(config.target_model):
            return f"target not multimodal (audio attack vs non-audio model {config.target_model})"
        return None

    async def run_attack(
        self,
        rendered: RenderedAttack,
        config: DeploymentConfig,
        temperature: float = 0.7,
        n_trials: int = 5,
    ) -> list[ModelResponse]:
        """Fan out `n_trials` independent calls; return list ordered by trial_index.

        Temperature is varied across trials as `temperature + 0.1 * i` capped at 1.5 (§10.3 wants
        i.i.d.-ish samples; a small monotonic walk guarantees variation without drifting far from the
        operator baseline; 1.5 is the safe shared ceiling — the Anthropic adapter re-clamps to 1.0).

        Multimodal gate (Step 0a/0b): if the rendered attack carries an image/audio payload but the
        target model is not capable, return an EMPTY list rather than dispatching — an honest
        "modality-unsupported" skip (an image sent to a text-only model would 400 and pollute the
        matrix as a fake ERROR). The caller simply produces no breach rows for that pair; callers that
        want to *report* the skip (rather than drop it silently) first consult
        :meth:`modality_skip_reason`.

        SINGLE-TURN ONLY: this stacks every user turn into one ``invoke`` with no interleaved model
        reply. For a primitive whose render has multiple user turns (Crescendo / gradient escalation),
        callers should use :meth:`run_conversation` instead, which drives a real back-and-forth.
        """
        skip = self.modality_skip_reason(rendered, config)
        if skip is not None:
            _log.info(
                "skip: %s — modality_unsupported (not an error; no trials dispatched)", skip
            )
            return []
        temperatures = [min(temperature + 0.1 * i, 1.5) for i in range(n_trials)]
        coros = [
            self._dispatch_one(rendered, config, trial_index=i, temperature=t)
            for i, t in enumerate(temperatures)
        ]
        # Per-call concurrency stays bounded by n_trials; the OUTER fan-out over
        # (primitives × configs) in scripts/reproduce/reproduce_once.py owns the Semaphore (§11.3).
        responses = await asyncio.gather(*coros)
        return sorted(responses, key=lambda r: r.trial_index)

    @staticmethod
    def user_turn_count(rendered: RenderedAttack) -> int:
        """How many user turns the rendered attack carries (system/assistant turns excluded).

        A count ≥ 2 means the primitive is a real multi-turn (Crescendo / gradient) attack that
        :meth:`run_conversation` should drive turn-by-turn rather than stacking into one ``invoke``.
        """
        return sum(1 for m in rendered.messages if m.get("role") == "user")

    async def run_conversation(
        self,
        rendered: RenderedAttack,
        config: DeploymentConfig,
        temperature: float = 0.7,
        n_trials: int = 5,
    ) -> list[ModelResponse]:
        """Drive a TRUE multi-turn back-and-forth; return the FINAL model reply per trial.

        This is the default path for a primitive whose render has multiple user turns. For each
        trial it sends user turn 1, gets the model's reply, appends that assistant reply to the
        running history, sends user turn 2, … and so on until the last user turn. The returned
        ``ModelResponse`` for the trial carries the FINAL reply (the one the judge grades), with
        latency/tokens/cost SUMMED across every turn in the exchange so the cost ledger stays honest.

        Adapter selection, the canonical message build (incl. the out-of-band image/audio payload on
        the LAST user turn), and the RateLimit/ContentPolicy/ProviderError → legacy-tag projection are
        identical to :meth:`run_attack` (they share ``_adapter_for`` / ``_build_messages`` /
        ``_error_response``) — only the dispatch shape (sequential with interleaved replies) differs.

        Multimodal gate and temperature walk match ``run_attack`` exactly: an image/audio attack
        against an incapable target returns ``[]`` (see :meth:`modality_skip_reason`), and trial ``i``
        runs at ``temperature + 0.1 * i`` capped at 1.5. A single-turn render is handled too (it
        degrades to one invoke), but callers should prefer ``run_attack`` for the single-turn case.
        """
        skip = self.modality_skip_reason(rendered, config)
        if skip is not None:
            _log.info(
                "skip: %s — modality_unsupported (not an error; no trials dispatched)", skip
            )
            return []
        temperatures = [min(temperature + 0.1 * i, 1.5) for i in range(n_trials)]
        coros = [
            self._drive_conversation_once(rendered, config, trial_index=i, temperature=t)
            for i, t in enumerate(temperatures)
        ]
        responses = await asyncio.gather(*coros)
        return sorted(responses, key=lambda r: r.trial_index)

    # ----- Internals -----

    def _adapter_for(self, provider: str, model_id: str, base_url: str | None = None):
        """Lazily create + cache the adapter for one (provider, model, endpoint)."""
        key = (provider, model_id, base_url)
        adapter = self._adapters.get(key)
        if adapter is None:
            adapter = registry.create(
                provider,
                AdapterConfig(
                    model=model_id,
                    base_url=base_url,
                    api_key=self._adapter_extra.get("api_key"),
                    extra=dict(self._adapter_extra),
                ),
            )
            self._adapters[key] = adapter
        return adapter

    def _build_messages(self, rendered: RenderedAttack) -> list[CanonicalMessage]:
        """Translate a RenderedAttack into provider-neutral CanonicalMessages.

        The legacy ``{role, content:str}`` turns become text messages; an out-of-band image/audio
        payload is attached to the LAST user turn as an ``ImageBlock``/``AudioBlock`` (the adapter
        renders the provider-specific wire format). System turns are never given media.
        """
        messages = from_legacy_messages(rendered.messages)
        if rendered.image_b64 is None and rendered.audio_b64 is None:
            return messages
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].role != MessageRole.USER:
                continue
            if rendered.image_b64 is not None:
                messages[i].content.append(
                    ImageBlock(
                        data=base64.b64decode(rendered.image_b64),
                        mime_type=rendered.image_media_type,
                    )
                )
            if rendered.audio_b64 is not None:
                messages[i].content.append(
                    AudioBlock(
                        data=base64.b64decode(rendered.audio_b64),
                        mime_type=f"audio/{rendered.audio_format}",
                    )
                )
            break
        return messages

    async def _dispatch_one(
        self,
        rendered: RenderedAttack,
        config: DeploymentConfig,
        trial_index: int,
        temperature: float,
    ) -> ModelResponse:
        """Route a single trial to the right adapter and project the result onto ModelResponse."""
        # A config carrying a base_url targets a custom OpenAI-compatible endpoint (the
        # CustomHTTPAdapter); otherwise route by the model-id prefix.
        provider = "custom" if config.base_url else _resolve_provider(config.target_model)
        adapter = self._adapter_for(provider, config.target_model, config.base_url)
        messages = self._build_messages(rendered)

        t0 = time.perf_counter()
        try:
            result = await adapter.invoke(messages, temperature=temperature)
        except RateLimitError as e:
            return self._error_response("rate_limit_exhausted", e, trial_index, temperature, t0)
        except ContentPolicyError as e:  # subclass of ProviderError — must precede it
            return self._error_response(
                "content_policy_or_bad_request", e, trial_index, temperature, t0
            )
        except (ProviderError, AuthenticationError) as e:
            status = getattr(e, "status_code", None) or "unknown"
            return self._error_response(f"http_status_{status}", e, trial_index, temperature, t0)

        return ModelResponse(
            content=result.text,
            reasoning=getattr(result, "reasoning", "") or "",
            latency_ms=result.latency_ms,
            tokens_in=result.usage.input_tokens,
            tokens_out=result.usage.output_tokens,
            cost_usd=result.usage.estimated_cost_usd or 0.0,
            error=None,
            trial_index=trial_index,
            temperature=temperature,
        )

    async def _drive_conversation_once(
        self,
        rendered: RenderedAttack,
        config: DeploymentConfig,
        trial_index: int,
        temperature: float,
    ) -> ModelResponse:
        """Run ONE trial as a real multi-turn exchange; return the FINAL reply as a ModelResponse.

        Mirrors ``_dispatch_one``'s adapter selection + error projection exactly, but instead of one
        ``invoke`` it walks the user turns: send up through user turn k → get reply → append the
        assistant reply to the running history → send up through user turn k+1 → … The final turn's
        reply is what the caller judges. Latency/tokens/cost are SUMMED across every invoke so the
        per-trial ModelResponse reflects the whole conversation, not just its last leg.

        If any turn errors (rate-limit exhausted, content-policy block, provider error), the exchange
        stops there and that error is returned as the trial's ModelResponse — exactly the same typed
        legacy tags ``_dispatch_one`` produces. A content-policy block mid-crescendo is a legitimate
        REFUSED outcome and is preserved verbatim.
        """
        provider = "custom" if config.base_url else _resolve_provider(config.target_model)
        adapter = self._adapter_for(provider, config.target_model, config.base_url)
        full = self._build_messages(rendered)

        # Indices of the user turns we advance through, in order. Everything before the first user
        # turn (a system turn) is carried as the standing prefix; assistant replies are interleaved.
        user_idxs = [i for i, m in enumerate(full) if m.role == MessageRole.USER]
        if not user_idxs:
            # No user turn to send — degrade to a single invoke of whatever was built (defensive;
            # render() guarantees at least one user turn for every primitive).
            return await self._dispatch_one(rendered, config, trial_index, temperature)

        history: list[CanonicalMessage] = []
        total_latency_ms = 0
        total_tokens_in = 0
        total_tokens_out = 0
        total_cost = 0.0
        last_text = ""
        prev_idx = 0
        for turn_no, idx in enumerate(user_idxs):
            # Append the slice from the previous user turn (exclusive) through this user turn
            # (inclusive): the leading system prefix on the first leg, then each subsequent user turn.
            history.extend(full[prev_idx : idx + 1])
            prev_idx = idx + 1

            t0 = time.perf_counter()
            try:
                result = await adapter.invoke(history, temperature=temperature)
            except RateLimitError as e:
                return self._error_response(
                    "rate_limit_exhausted", e, trial_index, temperature, t0
                )
            except ContentPolicyError as e:  # subclass of ProviderError — must precede it
                return self._error_response(
                    "content_policy_or_bad_request", e, trial_index, temperature, t0
                )
            except (ProviderError, AuthenticationError) as e:
                status = getattr(e, "status_code", None) or "unknown"
                return self._error_response(
                    f"http_status_{status}", e, trial_index, temperature, t0
                )

            total_latency_ms += result.latency_ms
            total_tokens_in += result.usage.input_tokens
            total_tokens_out += result.usage.output_tokens
            total_cost += result.usage.estimated_cost_usd or 0.0
            last_text = result.text
            # Interleave the model's reply before the next user turn (skip after the final turn —
            # there's no further user turn to follow it, and the final reply is what we return).
            if turn_no < len(user_idxs) - 1:
                history.append(result.to_message())

        return ModelResponse(
            content=last_text,
            latency_ms=total_latency_ms,
            tokens_in=total_tokens_in,
            tokens_out=total_tokens_out,
            cost_usd=total_cost,
            error=None,
            trial_index=trial_index,
            temperature=temperature,
        )

    @staticmethod
    def _error_response(
        tag: str, exc: AdapterError, trial_index: int, temperature: float, t0: float
    ) -> ModelResponse:
        """Build the structured ModelResponse for a recordable provider failure."""
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return ModelResponse(
            content="",
            latency_ms=latency_ms,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            error=f"{tag}: {exc}",
            trial_index=trial_index,
            temperature=temperature,
        )
