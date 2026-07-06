"""Synthesize surface-obfuscation children for the §10.7 augmentation sweep.

The deterministic, zero-LLM-cost sibling of ``synthesize_mutations.py``. Where
that script paraphrases an almost-defended parent with an LLM, this one skins it
with the ten obfuscation operators (``rogue.obfuscation.operators`` — leetspeak,
homoglyph, zero-width, fullwidth, zalgo + base64/rot13/hex/unicode-escape/
html-entity decode-wraps) and persists each as a ``synthesized=True`` child
primitive. ``reproduce_once.py`` then fires those children through the panel
like any other primitive, so the breach matrix shows whether a target defends
the *technique* or merely the *exact surface string* — the "pattern-matching,
not understanding" question, now part of the normal pipeline rather than a
standalone research runner.

Design notes:

  * **Render-then-obfuscate, persist slotless.** We render the parent against a
    reference config (filling ``{{slots}}`` from defaults), obfuscate the
    *concrete* user turn, and persist a child with ``payload_slots = {}``. This
    is the only way the WRAP operators work (base64-encoding a ``{{slot}}`` would
    freeze an unfilled marker inside the blob) and it keeps INLINE operators from
    corrupting slot markers. The child is a fixed concrete attack; reproduce
    tests the same obfuscated text against every config's system prompt.
  * **No semantic dedup.** Unlike mutations, obfuscation variants are
    *intentionally* near-identical in meaning — that is the experiment. We drop
    only exact-duplicate text and no-op variants (an operator that didn't change
    the input, e.g. homoglyph on text with no a/e/o/p/c/y/x/i).
  * **Tagged for analysis.** Each child's title is ``[obf:<operator>]`` and its
    notes carry ``OBFUSCATION_AUGMENTATION op=<name> kind=<inline|wrap>``, so the
    breach matrix can be grouped by operator without a schema change.
  * **Text-only.** Multimodal parents are skipped (obfuscating an image carrier
    is out of scope here).

Idempotency: parents that already have obfuscation children (notes LIKE
'OBFUSCATION_AUGMENTATION%') are skipped, so a re-run is a no-op.

Spend: $0 — operators are deterministic. The cost is the later reproduce.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

import ulid
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from rogue.db.models import AttackPrimitive as AttackPrimitiveORM  # noqa: E402
from rogue.obfuscation.operators import OBFUSCATION_OPERATORS  # noqa: E402
from rogue.reproduce.instantiator import render  # noqa: E402
from rogue.schemas import AttackPrimitive, DeploymentConfig  # noqa: E402

# Reuse the parent-selection + ORM→pydantic helpers from the mutation harness.
from scripts.reproduce.synthesize_mutations import (  # noqa: E402
    _assert_schema_present,
    _load_almost_defended_primitives,
    _orm_to_pydantic_primitive,
)

logger = logging.getLogger("synthesize_obfuscations")

_NOTE_MARKER = "OBFUSCATION_AUGMENTATION"


@dataclass
class ObfuscationStats:
    candidates_considered: int = 0
    skipped_already_done: int = 0
    skipped_multimodal: int = 0
    variants_persisted: int = 0
    variants_skipped_noop: int = 0
    persist_errors: int = 0
    per_operator: dict[str, int] = field(default_factory=dict)

    def summary_line(self) -> str:
        return (
            f"candidates={self.candidates_considered} "
            f"persisted={self.variants_persisted} "
            f"noop={self.variants_skipped_noop} "
            f"skipped_done={self.skipped_already_done} "
            f"skipped_multimodal={self.skipped_multimodal} "
            f"persist_errors={self.persist_errors}"
        )


def _reference_config() -> DeploymentConfig:
    """A throwaway config whose only job is to render slot defaults into text.

    The target_model is never called (render() does no inference); an empty
    system prompt keeps the rendered user turn clean for obfuscation.
    """
    return DeploymentConfig(
        config_id="obf-render-ref",
        customer_id="adhoc",
        name="obf-render-ref",
        target_model="meta-llama/llama-3.1-8b-instruct",
        system_prompt="",
        declared_tools=[],
        forbidden_topics=[],
    )


def _rendered_user_text(parent: AttackPrimitive, ref: DeploymentConfig) -> str | None:
    """Render the parent and return its last user-turn text, or None if the
    render is not plain text (multimodal carrier)."""
    rendered = render(parent, ref)
    if rendered.image_b64 or rendered.audio_b64:
        return None
    for msg in reversed(rendered.messages):
        if msg.get("role") == "user" and isinstance(msg.get("content"), str):
            return msg["content"]
    return None


def _build_obfuscated_primitive(
    parent: AttackPrimitive, obf_text: str, operator_name: str, kind: str,
) -> AttackPrimitiveORM:
    """A ``synthesized=True`` child carrying one obfuscated, fully-rendered payload.

    Family + vector are inherited (a leetspeak DAN is still a DAN). ``payload_slots``
    is empty because slots are already resolved into ``obf_text``.
    """
    primitive_id = ulid.new().str
    return AttackPrimitiveORM(
        primitive_id=primitive_id,
        cluster_id=primitive_id,
        canonical=True,
        family=parent.family.value,
        secondary_families=[],
        vector=parent.vector.value,
        title=f"[obf:{operator_name}] {parent.title[:150]}",
        short_description=(
            f"§10.7 surface-obfuscation child ({operator_name}/{kind}) of "
            f"{parent.primitive_id}. Family + vector unchanged; the rendered "
            "payload is skinned to test surface-pattern-matching vs technique."
        ),
        payload_template=obf_text,
        payload_slots={},
        multi_turn_sequence=None,
        slot_requirements=None,
        synthesized=True,
        derived_from_primitive_id=parent.primitive_id,
        target_models_claimed=[],
        claimed_success_rate=None,
        claimed_first_seen=None,
        reproducibility_score=parent.reproducibility_score,
        requires_multi_turn=False,
        requires_system_prompt_access=parent.requires_system_prompt_access,
        requires_tools=parent.requires_tools,
        requires_multimodal=False,
        discovered_at=datetime.now(timezone.utc),
        base_severity=parent.base_severity.value,
        severity_rationale=(
            f"§10.7 obfuscation: parent={parent.primitive_id} "
            f"operator={operator_name} kind={kind} (surface form only)"
        ),
        notes=f"{_NOTE_MARKER} op={operator_name} kind={kind} parent={parent.primitive_id}",
    )


def run_obfuscation_synthesis(
    *,
    database_url: str,
    limit: int,
    evade_threshold: float,
    min_defended_configs: int,
    kinds: tuple[str, ...],
    primitive_id: str | None = None,
) -> ObfuscationStats:
    _assert_schema_present(database_url)
    operators = [op for op in OBFUSCATION_OPERATORS if op.kind in kinds]

    engine = create_engine(database_url)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    stats = ObfuscationStats()
    ref = _reference_config()

    try:
        with SessionLocal() as session:
            if primitive_id is not None:
                orm = session.get(AttackPrimitiveORM, primitive_id)
                if orm is None:
                    raise RuntimeError(f"primitive_id not found: {primitive_id!r}")
                orms = [orm]
            else:
                orms = _load_almost_defended_primitives(
                    session,
                    limit=limit,
                    evade_threshold=evade_threshold,
                    min_defended_configs=min_defended_configs,
                )
            stats.candidates_considered = len(orms)
            if not orms:
                return stats

            # Idempotency: parents that already have obfuscation children.
            already = set(
                session.execute(
                    text(
                        "SELECT DISTINCT derived_from_primitive_id FROM attack_primitives "
                        "WHERE synthesized = true AND derived_from_primitive_id IS NOT NULL "
                        "AND notes LIKE :marker"
                    ),
                    {"marker": f"{_NOTE_MARKER}%"},
                ).scalars()
            )

            for orm in orms:
                parent = _orm_to_pydantic_primitive(orm)
                if parent.primitive_id in already:
                    stats.skipped_already_done += 1
                    continue
                base_text = _rendered_user_text(parent, ref)
                if base_text is None:
                    stats.skipped_multimodal += 1
                    continue

                seen: set[str] = {base_text}
                for op in operators:
                    obf = op.apply(base_text)
                    if obf in seen:  # no-op or exact dup of baseline/another op
                        stats.variants_skipped_noop += 1
                        continue
                    seen.add(obf)
                    try:
                        child = _build_obfuscated_primitive(parent, obf, op.name, op.kind)
                        session.add(child)
                        session.flush()
                        stats.variants_persisted += 1
                        stats.per_operator[op.name] = stats.per_operator.get(op.name, 0) + 1
                    except Exception as exc:  # noqa: BLE001
                        stats.persist_errors += 1
                        session.rollback()
                        logger.exception(
                            "persist failed: parent=%s op=%s err=%s",
                            parent.primitive_id, op.name, exc,
                        )
            session.commit()
    finally:
        engine.dispose()
    return stats


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=15, help="max almost-defended parents")
    ap.add_argument("--evade-threshold", type=float, default=0.5)
    ap.add_argument("--min-defended-configs", type=int, default=3)
    ap.add_argument("--kinds", default="inline,wrap", help="comma-separated: inline,wrap")
    ap.add_argument("--primitive-id", default=None, help="obfuscate one specific parent")
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be created without writing (no parent load skip)")
    args = ap.parse_args(argv)

    if not args.database_url:
        print("error: DATABASE_URL not set", file=sys.stderr)
        return 2
    kinds = tuple(k.strip() for k in args.kinds.split(",") if k.strip())

    if args.dry_run:
        n_ops = len([op for op in OBFUSCATION_OPERATORS if op.kind in kinds])
        print(f"DRY-RUN: up to {args.limit} parents x {n_ops} operators "
              f"({','.join(kinds)}) → up to {args.limit * n_ops} synthesized children. "
              "No DB writes. Drop --dry-run to persist.")
        return 0

    stats = run_obfuscation_synthesis(
        database_url=args.database_url,
        limit=args.limit,
        evade_threshold=args.evade_threshold,
        min_defended_configs=args.min_defended_configs,
        kinds=kinds,
        primitive_id=args.primitive_id,
    )
    print("done:", stats.summary_line())
    if stats.per_operator:
        print("per-operator:", stats.per_operator)
    print("Next: run scripts/reproduce/reproduce_once.py to fire the new children through the panel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
