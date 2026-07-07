"""Local-first extraction cascade (Q17) — cheap local tier, Haiku fallback.

What it is
----------
A drop-in wrapper around :class:`~rogue.extract.extraction_agent.ExtractionAgent`
that tries a **cheap local model first** and escalates to the paid Haiku
extractor **only when the local output can't be trusted**. It is the extraction
sibling of the judge cascade (Q2): a $0 cheap tier short-circuits the paid call
when — and only when — it is confidently right, so quality is never traded for
cost.

Why a cascade and not a swap (the honest version)
-------------------------------------------------
The two grounding papers (Lincoln 2605.05532, Bumgardner 2308.01727) only ever
validate a *fine-tuned* small model, and neither compares against a cheap hosted
small model like Haiku — so the literature does **not** establish an
off-the-shelf Haiku→local win. ROGUE's own measurement agrees: an off-the-shelf
3B (qwen2.5:3b) abstains on real attack disclosures. A naive model swap would
therefore *drop attacks*. The cascade removes that risk by construction:

  * the local tier can only ever *save* a Haiku call, never replace Haiku's
    verdict — every abstention / malformed / ungrounded local output escalates;
  * so with a weak local model the cascade escalates ~everything (≈0 saving, 0
    quality loss); the saving materialises only for a local model that clears
    the field-agreement bar (measure it first with
    ``scripts/extract/eval_extractor_fields.py``).

Acceptance gate (asymmetric, mirrors Q2's "never assert from the cheap tier")
-----------------------------------------------------------------------------
Accept the local extraction iff it is a schema-valid ``AttackPrimitive`` with a
non-empty ``payload_template`` that clears an **anti-fabrication grounding floor**
(``field_eval.grounding_score`` ≥ a low threshold — a wholesale-invention guard,
NOT a correctness gate: ROGUE payloads are synthesised, not copied spans, so they
ground only partially even when correct). Otherwise — abstention, error, or a
payload with almost no source overlap — escalate to Haiku. Never *drop* a
document on the local tier's say-so. The gate checks well-formedness +
anti-fabrication; genuine correctness is what the offline field-eval A/B
(``scripts/extract/eval_extractor_fields.py``) measures — clear that bar before
trusting any local model in production.

Off by default: unless ``ROGUE_EXTRACT_CASCADE`` is set truthy the harvest path
constructs the plain Haiku ``ExtractionAgent`` exactly as before (byte-identical).
No new dependency.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass

from rogue.extract.extraction_agent import ExtractionAgent, ExtractionImage
from rogue.extract.field_eval import grounding_score
from rogue.schemas import AttackPrimitive, RawDocument, TechniqueSpec

logger = logging.getLogger("rogue.extract.cascade")

_TRUTHY = {"1", "true", "on", "yes"}

#: Default local tier — an Ollama-served model via the ``local/`` prefix. Chosen
#: because it is what is commonly pulled locally; it is NOT a recommendation
#: (measure field agreement before trusting any local model in production).
DEFAULT_LOCAL_MODEL = "local/qwen2.5:3b"
#: Anti-fabrication FLOOR, not a correctness gate. ROGUE's ``payload_template`` is
#: a *synthesised* template, not a span copied from source (measured: the golden
#: research-paper fixture grounds at 0.26, a copied-blog-payload fixture at 0.67)
#: — so a high grounding bar would wrongly reject good reconstructed attacks. The
#: floor only catches a payload with almost no source overlap (wholesale
#: invention); correctness is established by the field-eval A/B, not by this gate.
DEFAULT_GROUNDING_THRESHOLD = 0.15


@dataclass(frozen=True)
class CascadeConfig:
    enabled: bool = False
    local_model: str = DEFAULT_LOCAL_MODEL
    fallback_model: str = "anthropic/claude-haiku-4-5"
    grounding_threshold: float = DEFAULT_GROUNDING_THRESHOLD


def resolve_cascade_config() -> CascadeConfig:
    """Read the cascade config from the environment (off unless flag is truthy)."""
    enabled = os.environ.get("ROGUE_EXTRACT_CASCADE", "").strip().lower() in _TRUTHY
    return CascadeConfig(
        enabled=enabled,
        local_model=os.environ.get("ROGUE_EXTRACT_LOCAL_MODEL", DEFAULT_LOCAL_MODEL),
        fallback_model=os.environ.get(
            "EXTRACTION_MODEL", "anthropic/claude-haiku-4-5"
        ),
        grounding_threshold=float(
            os.environ.get(
                "ROGUE_EXTRACT_GROUNDING_THRESHOLD", str(DEFAULT_GROUNDING_THRESHOLD)
            )
        ),
    )


@dataclass
class CascadeStats:
    """Telemetry surfaced to the harvest summary (no silent behaviour)."""

    n_docs: int = 0
    n_local_accepted: int = 0
    n_escalated_abstain: int = 0
    n_escalated_ungrounded: int = 0
    n_escalated_error: int = 0

    @property
    def n_escalated(self) -> int:
        return (
            self.n_escalated_abstain
            + self.n_escalated_ungrounded
            + self.n_escalated_error
        )

    @property
    def local_save_rate(self) -> float:
        return self.n_local_accepted / self.n_docs if self.n_docs else 0.0

    def to_dict(self) -> dict[str, float | int]:
        d = asdict(self)
        d["n_escalated"] = self.n_escalated
        d["local_save_rate"] = round(self.local_save_rate, 4)
        return d


class CascadeExtractionAgent:
    """Local-first, Haiku-fallback extractor with the same harvest-facing API.

    Presents :meth:`extract_from_raw_document` and
    :meth:`extract_any_from_raw_document` so it is a drop-in for the plain
    ``ExtractionAgent`` at every harvest construction site. The fallback tier
    runs the production v4 (3-way) extractor; the local tier runs v3 (payload or
    None) because plain json-mode local endpoints don't carry the technique
    branch reliably — a local *technique* judgement is exactly the kind of call
    we escalate anyway.
    """

    def __init__(self, config: CascadeConfig | None = None) -> None:
        self.config = config or resolve_cascade_config()
        self.local = ExtractionAgent(model=self.config.local_model, prompt_version="v3")
        self.fallback = ExtractionAgent(
            model=self.config.fallback_model, prompt_version="v4"
        )
        self.stats = CascadeStats()

    async def _try_local(self, raw_doc: RawDocument) -> AttackPrimitive | None:
        """Run the local tier text-only. Returns a primitive or None (abstain)."""
        # Local SLMs here are text-only — never forward images to the local tier.
        return await self.local.extract_from_raw_document(raw_doc, images=None)

    def _accept(self, prim: AttackPrimitive, raw_doc: RawDocument) -> bool:
        """Well-formedness + anti-fabrication floor (not a correctness gate).

        Accept iff the payload_template is non-empty and clears the grounding
        floor (a wholesale-invention guard). Enum/schema validity is already
        guaranteed by the Pydantic validation that produced ``prim``.
        """
        if not (prim.payload_template or "").strip():
            return False
        gs = grounding_score(prim.payload_template, raw_doc.raw_content)
        return gs >= self.config.grounding_threshold

    async def extract_any_from_raw_document(
        self,
        raw_doc: RawDocument,
        images: "list[ExtractionImage] | None" = None,
    ) -> AttackPrimitive | TechniqueSpec | None:
        """Cascade entry point matching ``ExtractionAgent.extract_any_from_raw_document``.

        Local first; accept only a grounded, schema-valid primitive; otherwise
        escalate to the Haiku 3-way extractor (which sees the images too).
        """
        self.stats.n_docs += 1
        try:
            local_prim = await self._try_local(raw_doc)
        except Exception as exc:  # noqa: BLE001 — any local failure => escalate
            logger.warning(
                "local extraction failed (%s: %s); escalating to %s; url=%s",
                type(exc).__name__,
                str(exc)[:120],
                self.config.fallback_model,
                raw_doc.url,
            )
            self.stats.n_escalated_error += 1
            return await self.fallback.extract_any_from_raw_document(
                raw_doc, images=images
            )

        if local_prim is None:
            self.stats.n_escalated_abstain += 1
        elif not self._accept(local_prim, raw_doc):
            logger.info(
                "local primitive ungrounded (payload not in source); escalating; url=%s",
                raw_doc.url,
            )
            self.stats.n_escalated_ungrounded += 1
        else:
            self.stats.n_local_accepted += 1
            return local_prim

        return await self.fallback.extract_any_from_raw_document(
            raw_doc, images=images
        )

    async def extract_from_raw_document(
        self,
        raw_doc: RawDocument,
        images: "list[ExtractionImage] | None" = None,
    ) -> AttackPrimitive | None:
        """Payload-only projection (technique -> None), matching the base agent."""
        out = await self.extract_any_from_raw_document(raw_doc, images=images)
        return out if not isinstance(out, TechniqueSpec) else None


def maybe_build_cascade_extractor(
    config: CascadeConfig | None = None,
    *,
    fallback_model: str | None = None,
) -> CascadeExtractionAgent | None:
    """Return a cascade extractor iff enabled, else None (caller uses plain agent).

    The single seam the harvest surfaces call: keeps the off-path byte-identical
    (returns None => the caller constructs its usual ``ExtractionAgent``).
    ``fallback_model`` lets a caller pin the Haiku tier to the exact model it
    would otherwise have used (harvest passes its resolved ``extraction_model``),
    so turning the cascade on only *adds* a local pre-tier — the paid tier is
    unchanged.
    """
    cfg = config or resolve_cascade_config()
    if not cfg.enabled:
        return None
    if fallback_model:
        cfg = CascadeConfig(
            enabled=cfg.enabled,
            local_model=cfg.local_model,
            fallback_model=fallback_model,
            grounding_threshold=cfg.grounding_threshold,
        )
    logger.info(
        "extraction cascade ON: local=%s fallback=%s grounding>=%.2f",
        cfg.local_model,
        cfg.fallback_model,
        cfg.grounding_threshold,
    )
    return CascadeExtractionAgent(cfg)
