"""TargetPanel — multi-provider dispatch for one rendered attack × N trials.

Pipeline position (ROGUE_PLAN.md §A.23 / §10.1):

    instantiator.render(...)   ->   RenderedAttack
                                         |
                                         v
       TargetPanel.run_attack(rendered, config, n_trials=N)
                                         |
                                         v
                                list[ModelResponse]   ->   judge.py

Consumed by `scripts/reproduce_once.py` and the FastAPI `/api/reproduce` endpoint. For each
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

        Callers (e.g. ``scripts/reproduce_once.py``) should invoke this in a ``finally:`` so asyncio
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
        matrix as a fake ERROR). The caller simply produces no breach rows for that pair.
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
        # Per-call concurrency stays bounded by n_trials; the OUTER fan-out over
        # (primitives × configs) in scripts/reproduce_once.py owns the Semaphore (§11.3).
        responses = await asyncio.gather(*coros)
        return sorted(responses, key=lambda r: r.trial_index)

    # ----- Internals -----

    def _adapter_for(self, provider: str, model_id: str):
        """Lazily create + cache the adapter for one (provider, model)."""
        key = (provider, model_id)
        adapter = self._adapters.get(key)
        if adapter is None:
            adapter = registry.create(
                provider, AdapterConfig(model=model_id, extra=dict(self._adapter_extra))
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
        provider = _resolve_provider(config.target_model)  # raises for an unrouted prefix
        adapter = self._adapter_for(provider, config.target_model)
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
            latency_ms=result.latency_ms,
            tokens_in=result.usage.input_tokens,
            tokens_out=result.usage.output_tokens,
            cost_usd=result.usage.estimated_cost_usd or 0.0,
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
