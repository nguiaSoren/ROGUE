"""ExtractionAgent — converts a raw open-web document into an AttackPrimitive (or None).

Pipeline position (ROGUE_PLAN.md §3.1 LAYER 2):

    harvest (RawDocument)  ->  ExtractionAgent  ->  AttackPrimitive | None  ->  dedup

The agent wraps the canonical extraction prompt (`prompts/extraction_v{N}.md`,
spec'd in §A.8) around a structured-output LLM call (spec'd in §A.21). It is
provider-agnostic at the surface — it routes on the `provider/model` prefix of
the configured `EXTRACTION_MODEL` env var (default `anthropic/claude-haiku-4-5`).
The prompt is loaded once at construction time so a single agent instance can be
reused across thousands of documents without re-reading the file.

Output contract:

    - If the document is an attack disclosure -> a validated `AttackPrimitive`.
    - If the document is commentary / news / mitigation / benchmark -> `None`.
    - If the LLM call itself fails transiently -> tenacity retries (3, expo).
    - If the LLM emits invalid JSON / fails schema validation -> Pydantic raises.

Day 0 status: prompt load + class shape + provider routing implemented; the
actual tool-call wire is conservative and marked where Day 1 §9.4 still needs
to land (real network calls + RawDocument adapter).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ulid

from pydantic import ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from rogue.schemas import AttackPrimitive, RawDocument


# Structured logger for failed extractions. Day-1 §9.4 wires this so the
# harvest dashboard's freshness panel can surface bad LLM output instead of
# silently re-raising. Uses the stdlib logger so consumers can configure
# handlers/levels via their own logging.config without taking a dep.
logger = logging.getLogger("rogue.extract.extraction_agent")


# Transient errors we want tenacity to retry on. Kept as a tuple of base
# exception classes so provider SDKs (anthropic, openai) can raise their own
# subclasses and still be caught. Network/IO + generic transient failures.
_TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
)


# ---------------------------------------------------------------------------
# TPM-conservation truncation (Tier 1 Anthropic = 50K input tokens/min)
# ---------------------------------------------------------------------------
#
# Long RawDocuments (Pliny excluded) get a head+tail cut before being sent
# to the extraction LLM so we don't saturate Anthropic's TPM ceiling on a
# single big doc and stall the whole harvest. Numbers picked conservatively:
# only the longest ~20% of corpus docs trip the threshold, and when cut,
# the LLM still sees the intro (likely TLDR + first code block) and the
# conclusion (likely summary). ``archive_hash`` is always computed on the
# ORIGINAL raw_document; only the LLM input is truncated.
#
# Pliny L1B3RT4S / CL4R1T4S files are exempt because their content IS the
# attack corpus — densely packed, no narrative; truncating loses primitives
# at a 1:1 rate with chars dropped. Detected by URL prefix.
#
# Tuning: bump TRUNCATE_THRESHOLD_CHARS up to disable for more docs, or
# lower TRUNCATE_HEAD/TAIL to be more aggressive. Set to None on the agent
# instance via `agent._truncate_threshold_chars = None` to disable entirely.
_TRUNCATE_THRESHOLD_CHARS: int = 40_000   # ~10K tokens; trips ~20% of corpus
_TRUNCATE_HEAD_CHARS: int = 12_000        # ~3K tokens; preserves intro + 1-2 code blocks
_TRUNCATE_TAIL_CHARS: int = 4_000         # ~1K tokens; preserves conclusion/summary
_TRUNCATE_EXEMPT_URL_PREFIXES: tuple[str, ...] = (
    "https://raw.githubusercontent.com/elder-plinius/",
)


def _maybe_truncate_for_extraction(
    raw_document: str,
    source_url: str,
    *,
    threshold_chars: int | None = _TRUNCATE_THRESHOLD_CHARS,
    head_chars: int = _TRUNCATE_HEAD_CHARS,
    tail_chars: int = _TRUNCATE_TAIL_CHARS,
) -> tuple[str, bool]:
    """Apply TPM-conservation truncation to ``raw_document`` for LLM input.

    Returns ``(maybe_truncated_text, was_truncated)``. The original text is
    never mutated; the caller continues to use ``raw_document`` for archive_hash
    computation. Pliny URLs are exempt by design.

    Module-level constants drive the default thresholds; the agent's
    ``extract()`` lets callers override per-call via kwargs (or disable by
    passing ``threshold_chars=None``).
    """
    if threshold_chars is None or len(raw_document) <= threshold_chars:
        return raw_document, False
    if any(source_url.startswith(p) for p in _TRUNCATE_EXEMPT_URL_PREFIXES):
        return raw_document, False
    head = raw_document[:head_chars]
    tail = raw_document[-tail_chars:] if tail_chars > 0 else ""
    marker = (
        f"\n\n[...content truncated for TPM; original was {len(raw_document)} "
        f"chars, kept head {head_chars} + tail {tail_chars}...]\n\n"
    )
    return head + marker + tail, True


# ---------------------------------------------------------------------------
# Post-LLM payload normalization (defense in depth — paired with prompt v2+)
# ---------------------------------------------------------------------------
#
# Haiku-tier models deviate from the AttackPrimitive schema in 8 known
# ways. Each is encoded as a rule below. The normalizer is conservative:
# it only mutates known-failure shapes, never invents semantic content
# (e.g. it WILL synth `sources` from harvest-side fields the LLM never had,
# but will NOT invent a `family` value when none was emitted — that's a
# validation failure on the LLM, not something we can fix).
#
# As of prompt v2 (extraction_v2.md, 2026-05-27), each R# rule is mirrored
# by a D# directive in the prompt's §"Output discipline" section — the
# prompt prevents the malformation at source, the normalizer catches the
# residual. Keep both layers; one without the other regresses the §9.5
# proof-of-life hardening.
#
# Rules (each tested in isolation in test_extraction.py):
#  R1. primitive_id          → ALWAYS overwrite with fresh ULID (LLM copies the example)        [v2 §D1]
#  R2. sources               → SYNTH from harvest-side fields when missing                       [v2 §D2]
#  R3. discovered_at         → default to fetched_at when missing/empty                          [v2 §D3]
#  R4. datetime fields       → strip {"..."} JSON-wrap + Z-suffix tolerance                       [v2 §D4]
#  R5. payload_template      → demote to is_attack=false when empty (unreproducible)             [v2 §D5]
#  R6. list-typed fields     → json.loads when string-encoded; wrap scalars in [x]                [v2 §D6]
#  R7. reproducibility_score → clamp to [1, 10] when out of range                                 [v2 §D7]
#  R8. bright_data_product   → ALWAYS overwrite per-source with harvest-side truth (LLM hallucinates) [v2 §D8]
#
# Returns the normalized dict OR ``{"is_attack": False, "reason": ...}``
# when a demote-to-skip rule fired. Caller passes to `_validate_or_none`.
#
# Why a module-level function (not a method): keeps the normalizer
# stateless + testable in isolation; agent.extract() just calls through.

# Fields declared as list-typed on AttackPrimitive (per schemas/attack_primitive.py).
_LIST_TYPED_FIELDS: tuple[str, ...] = (
    "multi_turn_sequence",
    "secondary_families",
    "target_models_claimed",
    "requires_tools",
)
# Fields declared as datetime-typed on AttackPrimitive.
_DATETIME_FIELDS: tuple[str, ...] = (
    "discovered_at",
    "claimed_first_seen",
)
# {"...."} → "..." for any datetime emitted as a JSON-object literal string.
_JSON_OBJECT_WRAP_RE = re.compile(r'\{\s*"([^"]*)"\s*\}')
# Reasonable ISO-date prefix gate (we only accept strings that LOOK like a date).
_ISO_DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _normalize_extraction_payload(
    data: Any,
    *,
    raw_document: str,
    source_url: str,
    source_type: str,
    fetched_at: datetime,
    bright_data_product: str,
) -> Any:
    """Coerce LLM tool-use output into something AttackPrimitive can validate.

    See module-level docstring for the rule list. Skip path (``is_attack:
    false`` or non-dict input) returns the input unchanged. Pliny / heavy-
    content sources benefit the most because Haiku's deviations cluster on
    long inputs.
    """
    if not isinstance(data, dict) or data.get("is_attack") is False:
        return data

    # R1 — overwrite primitive_id with a fresh ULID. LLM copies the prompt's
    # example across every call, causing PK collisions on every save.
    data["primitive_id"] = ulid.new().str

    # R2 — synth sources from harvest-side facts if LLM omitted.
    if not data.get("sources"):
        data["sources"] = [
            {
                "url": source_url,
                "source_type": source_type,
                "author": None,
                "published_at": None,
                "fetched_at": fetched_at.isoformat(),
                "archive_hash": hashlib.sha256(
                    raw_document.encode("utf-8"),
                ).hexdigest(),
                "bright_data_product": bright_data_product,
            },
        ]

    # R8 — overwrite `bright_data_product` in every source entry with the
    # harvest-side truth. The LLM hallucinates this field freely (it has
    # no way to know which BD product actually fetched the doc — it's
    # harvest-side metadata, not document content). This was caught
    # post-§9.5-proof-of-life when the source_type × bright_data_product
    # distribution showed 27 `blog | web_scraper_api` rows that should
    # have been `blog | web_unlocker`. Same trust-the-server pattern as
    # R1 (primitive_id) — the LLM is the wrong source of truth for
    # provenance metadata. Harmless if LLM was right; corrects when wrong.
    if isinstance(data.get("sources"), list):
        for src in data["sources"]:
            if isinstance(src, dict):
                src["bright_data_product"] = bright_data_product

    # R3 — synth discovered_at = fetched_at if missing/empty.
    if "discovered_at" not in data or data.get("discovered_at") in (None, ""):
        data["discovered_at"] = fetched_at.isoformat()

    # R4 — strip JSON-object-literal wrapping from EVERY datetime field;
    # drop to None (Optional) or default-to-fetched_at (required) on
    # unparseable values.
    for dt_field in _DATETIME_FIELDS:
        val = data.get(dt_field)
        if not isinstance(val, str):
            continue
        cleaned = val.strip()
        m = _JSON_OBJECT_WRAP_RE.fullmatch(cleaned)
        if m:
            cleaned = m.group(1)
        if _ISO_DATE_PREFIX_RE.match(cleaned):
            data[dt_field] = cleaned
        else:
            # Unparseable — Optional fields go to None; required ones
            # (discovered_at) re-default to fetched_at so validation passes.
            if dt_field == "discovered_at":
                data[dt_field] = fetched_at.isoformat()
            else:
                data[dt_field] = None

    # R5 — demote to is_attack=false when payload_template is missing/empty.
    # An attack we can't reproduce is useless to Layer 4; skip cleanly.
    pt = data.get("payload_template")
    if not isinstance(pt, str) or not pt.strip():
        logger.warning(
            "extraction demoted to is_attack=false: missing payload_template "
            "(LLM emitted classification metadata without attack content); url=%s",
            source_url,
        )
        return {
            "is_attack": False,
            "reason": "payload_template missing or empty — unreproducible",
        }

    # R6 — coerce list-typed fields. Haiku sometimes serializes lists as
    # JSON-encoded strings; less often emits a scalar instead of a single-
    # element list. Both are auto-fixed below.
    import json as _json
    for list_field in _LIST_TYPED_FIELDS:
        val = data.get(list_field)
        if isinstance(val, str):
            stripped = val.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                try:
                    data[list_field] = _json.loads(stripped)
                    continue
                except (ValueError, TypeError):
                    pass
            # Non-JSON string in a list field — treat as a single-element list
            # IF the field accepts strings (multi_turn_sequence /
            # target_models_claimed / requires_tools). Otherwise null out so
            # Pydantic's enum validator can raise loudly.
            if list_field == "secondary_families":
                data[list_field] = None
            else:
                data[list_field] = [stripped] if stripped else []
        elif val is not None and not isinstance(val, list):
            # Scalar non-string (e.g., int leaked into a string-list field).
            data[list_field] = [val]

    # R7 — clamp reproducibility_score to the declared [1, 10] range.
    # Haiku occasionally emits 0 or 11+; clamp + warn instead of crashing.
    rs = data.get("reproducibility_score")
    if isinstance(rs, (int, float)):
        if rs < 1 or rs > 10:
            logger.warning(
                "reproducibility_score=%r out of range [1, 10]; clamping; url=%s",
                rs, source_url,
            )
            data["reproducibility_score"] = max(1, min(10, int(rs)))

    return data


class ExtractionAgent:
    """LLM-driven extractor: raw document -> `AttackPrimitive` or `None`.

    The agent is stateless across `extract()` calls — every call is independent
    so a single instance is safe to share across an `asyncio.gather()` fan-out.

    Args:
        model: provider-prefixed model id, e.g. ``"anthropic/claude-haiku-4-5"``
            or ``"openai/gpt-4o-mini"``. If omitted, reads ``EXTRACTION_MODEL``
            from the environment (default ``anthropic/claude-haiku-4-5``).
        prompt_version: which prompt revision to load from the ``prompts/``
            directory. Default ``"v2"`` (2026-05-27 — adds the §"Output
            discipline" section that prevents R1–R8 normalizer failure modes
            at source); ``"v1"`` is preserved for re-extraction of primitives
            that cited it. Primitives record this in their provenance so
            re-extraction is reproducible.
    """

    def __init__(self, model: str | None = None, prompt_version: str = "v2") -> None:
        self.model: str = model or os.environ.get(
            "EXTRACTION_MODEL", "anthropic/claude-haiku-4-5"
        )
        self.prompt_version: str = prompt_version

        prompt_path = (
            Path(__file__).parent / "prompts" / f"extraction_{prompt_version}.md"
        )
        if not prompt_path.exists():
            raise FileNotFoundError(
                f"Extraction prompt not found: {prompt_path}. "
                f"Expected a file named extraction_{prompt_version}.md."
            )
        self.prompt: str = prompt_path.read_text(encoding="utf-8")

        # Lazy provider client init — constructed on first `extract()` call so
        # importing the agent does not require API keys to be set (useful in
        # tests / static checks).
        self._anthropic_client: Any | None = None
        self._openai_client: Any | None = None

    # ----- Public API -----

    async def extract(
        self,
        raw_document: str,
        source_url: str,
        source_type: str,
        fetched_at: datetime | None = None,
        *,
        bright_data_product: str = "web_unlocker",
    ) -> AttackPrimitive | None:
        """Extract an `AttackPrimitive` from a raw document, or return `None`.

        Args:
            raw_document: the document text (markdown / plain / HTML stripped).
            source_url: canonical URL of the source.
            source_type: one of the literal values from `SourceType` (reddit,
                x, arxiv, github, blog, ...).
            fetched_at: when ROGUE fetched the document; defaults to "now UTC".
            bright_data_product: which BD product fetched the doc — used only
                if the extraction LLM omits ``sources`` (which it routinely
                does on simple docs). When that happens we synth a minimal
                SourceProvenance from these harvest-side fields so the
                AttackPrimitive validates. Defaults to ``"web_unlocker"``
                because that's the most common fetch path; callers with
                better information (``extract_from_raw_document``) pass the
                actual product label.

        Returns:
            A validated `AttackPrimitive` if the LLM judges the document an
            attack disclosure, else `None`.
        """
        fetched_at = fetched_at or datetime.now(timezone.utc)

        # TPM-conservation truncation. Original `raw_document` is preserved
        # for archive_hash computation in the synth-sources block below; only
        # the LLM input is truncated. Pliny URLs are exempt by URL prefix.
        # See `_maybe_truncate_for_extraction` docstring for the rationale.
        extraction_text, was_truncated = _maybe_truncate_for_extraction(
            raw_document=raw_document,
            source_url=source_url,
        )
        if was_truncated:
            logger.warning(
                "truncated content for extraction: url=%s orig_chars=%d truncated_chars=%d",
                source_url,
                len(raw_document),
                len(extraction_text),
            )

        user_message = self._build_user_message(
            raw_document=extraction_text,
            source_url=source_url,
            source_type=source_type,
            fetched_at=fetched_at,
        )

        if self.model.startswith("anthropic/"):
            data = await self._call_anthropic(user_message)
        elif self.model.startswith("openai/"):
            data = await self._call_openai(user_message)
        else:
            raise NotImplementedError(
                f"provider for {self.model} not wired — Day 1"
            )

        # Post-LLM payload normalization. Consolidated into one place
        # because Haiku-tier models deviate from the AttackPrimitive schema
        # in ~7 known ways (primitive_id copying, omitted sources/discovered_at,
        # JSON-wrapped dates, missing payload_template, string-encoded lists,
        # out-of-range scores). See `_normalize_extraction_payload` for the
        # rule list and per-rule rationale.
        data = _normalize_extraction_payload(
            data,
            raw_document=raw_document,
            source_url=source_url,
            source_type=source_type,
            fetched_at=fetched_at,
            bright_data_product=bright_data_product,
        )

        return self._validate_or_none(data)

    def extract_sync(
        self,
        raw_document: str,
        source_url: str,
        source_type: str,
        fetched_at: datetime | None = None,
    ) -> AttackPrimitive | None:
        """Blocking wrapper around `extract()` for use from scripts / notebooks."""
        return asyncio.run(
            self.extract(
                raw_document=raw_document,
                source_url=source_url,
                source_type=source_type,
                fetched_at=fetched_at,
            )
        )

    async def extract_from_raw_document(
        self,
        raw_doc: RawDocument,
    ) -> AttackPrimitive | None:
        """Adapter: project a harvest-layer :class:`RawDocument` onto :meth:`extract`.

        This is the pipeline-facing entry point — DiscoveryAgent emits a flat
        ``list[RawDocument]`` (per §3.1 LAYER 1 → LAYER 2 wire contract), and
        Day 1 §9.4 fan-out is just ``await asyncio.gather(*[agent.extract_from_raw_document(d)
        for d in raw_docs])``. The single-`str` :meth:`extract` is kept for
        ad-hoc / notebook use against pre-stripped text.

        ValidationErrors from the underlying LLM call are logged + re-raised
        with the source URL attached so the caller can drop the bad row in
        the dedup layer without losing the upstream pointer.
        """
        try:
            return await self.extract(
                raw_document=raw_doc.raw_content,
                source_url=str(raw_doc.url),
                source_type=str(raw_doc.source_type),
                fetched_at=raw_doc.fetched_at,
                # Pass the actual BD product so the synth-sources fallback
                # (fires when the LLM omits `sources`) records the correct
                # label rather than the `extract()` default of "web_unlocker".
                bright_data_product=str(raw_doc.bright_data_product),
            )
        except ValidationError:
            logger.exception(
                "extraction validation failed: url=%s source_type=%s archive_hash=%s",
                raw_doc.url,
                raw_doc.source_type,
                raw_doc.archive_hash,
            )
            raise

    # ----- Internals -----

    def _build_user_message(
        self,
        raw_document: str,
        source_url: str,
        source_type: str,
        fetched_at: datetime,
    ) -> str:
        """Render the user-turn template (shared shape across extraction_v1.md / v2.md)."""
        return (
            f"Document URL: {source_url}\n"
            f"Source type: {source_type}\n"
            f"Fetched at: {fetched_at.isoformat()}\n\n"
            f"Document content:\n---\n{raw_document}\n---\n\n"
            'Extract the AttackPrimitive. If the document does not describe '
            'an attack, respond with {"is_attack": false, "reason": "..."}.'
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(_TRANSIENT_ERRORS),
        reraise=True,
    )
    async def _call_anthropic(self, user_message: str) -> dict[str, Any]:
        """Anthropic tool-use call. Returns the raw tool-call input dict.

        Tool-use mode pins the model output to a JSON object validating against
        `AttackPrimitive.model_json_schema()`. The "or skip" branch is encoded
        as the optional `is_attack: false` top-level field handled by
        `_validate_or_none`.
        """
        # IMPLEMENT Day 1 §9.4 — replace the lazy import + bare client init
        # with a wired-up `rogue.config.settings.ANTHROPIC_API_KEY` once the
        # settings loader (§A.3) is in. Day 0: rely on the SDK's default env
        # var pickup so this module is importable without keys.
        from anthropic import AsyncAnthropic

        if self._anthropic_client is None:
            self._anthropic_client = AsyncAnthropic()

        # Strip the "anthropic/" provider prefix to get the bare model id.
        bare_model = self.model.split("/", 1)[1]

        response = await self._anthropic_client.messages.create(
            model=bare_model,
            max_tokens=4096,
            system=self.prompt,
            messages=[{"role": "user", "content": user_message}],
            tools=[
                {
                    "name": "extract_attack_primitive",
                    "description": (
                        "Output the extracted AttackPrimitive, or "
                        '{"is_attack": false, "reason": "..."} if the '
                        "document is not an attack disclosure."
                    ),
                    "input_schema": AttackPrimitive.model_json_schema(),
                }
            ],
            tool_choice={"type": "tool", "name": "extract_attack_primitive"},
        )

        # Parse tool_use response blocks — first matching block wins.
        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                # `block.input` is the structured tool-call payload.
                return dict(block.input)

        # No tool_use block returned — treat as a soft "not an attack" so the
        # pipeline can move on rather than crashing on a malformed response.
        logger.warning(
            "anthropic response contained no tool_use block: model=%s",
            self.model,
        )
        return {"is_attack": False, "reason": "no tool_use block in response"}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(_TRANSIENT_ERRORS),
        reraise=True,
    )
    async def _call_openai(self, user_message: str) -> dict[str, Any]:
        """OpenAI structured-output call via Pydantic-aware `.parse()`.

        Uses the SDK's `response_format=AttackPrimitive` so the parsed object
        comes back already validated against the schema.
        """
        # IMPLEMENT Day 1 §9.4 — same caveat as the Anthropic branch: switch
        # to `rogue.config.settings.OPENAI_API_KEY` once §A.3 lands.
        from openai import AsyncOpenAI

        if self._openai_client is None:
            self._openai_client = AsyncOpenAI()

        bare_model = self.model.split("/", 1)[1]

        completion = await self._openai_client.beta.chat.completions.parse(
            model=bare_model,
            messages=[
                {"role": "system", "content": self.prompt},
                {"role": "user", "content": user_message},
            ],
            response_format=AttackPrimitive,
        )

        # The SDK returns a parsed Pydantic object on `.parsed`. We dump it back
        # to a dict so `_validate_or_none` can handle the "is_attack: false"
        # case uniformly across providers.
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            return {
                "is_attack": False,
                "reason": "openai .parsed was None (refusal or schema mismatch)",
            }
        return parsed.model_dump(mode="json")

    def _validate_or_none(self, data: dict[str, Any]) -> AttackPrimitive | None:
        """Common post-LLM validation. Returns `None` on the explicit skip flag.

        Raises `pydantic.ValidationError` if the model claimed `is_attack: true`
        but produced a payload that does not validate against `AttackPrimitive`
        — surfaced rather than swallowed so the harvest run can flag bad LLM
        output during dev. The validation failure is logged via the module
        logger (Day-1 §9.4 dashboard freshness panel reads this).
        """
        if data.get("is_attack") is False:
            logger.debug(
                "extraction skipped (is_attack=false): reason=%s",
                data.get("reason"),
            )
            return None

        # Drop the bookkeeping flag before handing to Pydantic — `is_attack`
        # is a prompt-level signal, not a schema field.
        payload = {k: v for k, v in data.items() if k != "is_attack"}

        try:
            return AttackPrimitive.model_validate(payload)
        except ValidationError as exc:
            logger.error(
                "extraction primitive failed Pydantic validation: model=%s error_count=%d",
                self.model,
                exc.error_count(),
            )
            raise
