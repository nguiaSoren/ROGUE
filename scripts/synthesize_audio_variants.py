#!/usr/bin/env python
"""Enable audio reproduction in the normal pipeline (#1b → 3b track).

Audio attacks currently only fire via the buried escalation audio tier (4th tier,
refused-primitives-only, pre-empted by earlier breaks), so the live matrix has ~0
audio coverage despite the panel now carrying 3 audio targets and audio breaching
at 57% (scripts/audio_viability_probe.py). This mints `vector=MULTIMODAL_AUDIO`
derived primitives from the known-breaching text attacks — exactly the same
`synthesized=True` derived-primitive pattern as synthesize_escalations.py. Once
persisted they are canonical, so the NORMAL reproduce sweep picks them up: render()
speaks each payload into a WAV (Step 0b), the modality gate routes it ONLY to
audio-capable configs (text-only configs get a clean skip-and-label, not an error),
and breach_results persist normally. No core reproduce-loop change, no schema change.

Selection: breaching single-turn text primitives, EXCLUDING obfuscation_encoding
(leetspeak/ROT13 collapse to 17% spoken — they're text-modality by nature, so an
audio variant just burns reproduce budget). Idempotent: an existing `<parent>__audio`
row is skipped. Reversible: every row is `synthesized=True` with `derived_from_
primitive_id` set, so `DELETE ... WHERE vector='multimodal_audio' AND synthesized`
cleanly removes them.

    uv run python scripts/synthesize_audio_variants.py --dry-run    # build + verify, no writes
    uv run python scripts/synthesize_audio_variants.py --limit 25   # mint to live DB
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import reproduce_once as R  # noqa: E402
from rogue.db.models import AttackPrimitive as AttackPrimitiveORM  # noqa: E402
from rogue.reproduce.instantiator import render  # noqa: E402
from rogue.schemas import AttackVector, DeploymentConfig  # noqa: E402

_AUDIO_SUFFIX = "__audio"


def _select_parent_ids(c, limit: int) -> list[str]:
    rows = c.execute(text("""
        SELECT p.primitive_id,
               count(*) FILTER (WHERE b.verdict IN ('full_breach','partial_breach')) AS br
        FROM attack_primitives p JOIN breach_results b ON b.primitive_id=p.primitive_id
        WHERE p.requires_multimodal=false AND p.requires_multi_turn=false
          AND p.family::text <> 'obfuscation_encoding'
          AND p.primitive_id NOT LIKE '%__audio'
        GROUP BY p.primitive_id
        HAVING count(*) FILTER (WHERE b.verdict IN ('full_breach','partial_breach')) >= 1
        ORDER BY br DESC LIMIT :n"""), {"n": limit}).all()
    return [r.primitive_id for r in rows]


def _build_audio_variant(parent: AttackPrimitiveORM) -> AttackPrimitiveORM:
    """Clone a text primitive into a MULTIMODAL_AUDIO variant — same payload,
    spoken at dispatch. Mirrors synthesize_escalations._build_* construction."""
    pid = f"{parent.primitive_id}{_AUDIO_SUFFIX}"
    return AttackPrimitiveORM(
        primitive_id=pid,
        cluster_id=pid,
        canonical=True,
        family=parent.family.value if hasattr(parent.family, "value") else parent.family,
        secondary_families=list(parent.secondary_families or []),
        vector=AttackVector.MULTIMODAL_AUDIO.value,
        title=f"[audio] {parent.title[:150]}",
        short_description=(
            f"Audio-modality variant of {parent.primitive_id} — same payload spoken "
            f"as a WAV (Step 0b), fired only at audio-capable targets. Enables audio "
            f"reproduction in the normal pipeline (#1b)."
        ),
        payload_template=parent.payload_template,
        payload_slots=dict(parent.payload_slots or {}),
        multi_turn_sequence=None,
        slot_requirements=parent.slot_requirements,
        synthesized=True,
        derived_from_primitive_id=parent.primitive_id,
        target_models_claimed=[],
        claimed_success_rate=None,
        claimed_first_seen=None,
        reproducibility_score=parent.reproducibility_score,
        requires_multi_turn=False,
        requires_system_prompt_access=parent.requires_system_prompt_access,
        requires_tools=parent.requires_tools,
        requires_multimodal=True,
        discovered_at=datetime.now(timezone.utc),
        base_severity=parent.base_severity.value if hasattr(parent.base_severity, "value") else parent.base_severity,
        severity_rationale=f"Audio-modality variant of {parent.primitive_id} ({parent.family}).",
        notes=f"Audio variant (#1b enable-audio). Parent: {parent.primitive_id}.",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--dry-run", action="store_true", help="build + verify render-to-audio, no DB writes")
    args = ap.parse_args()

    load_dotenv(str(_ROOT / ".env"))
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as c:
        parent_ids = _select_parent_ids(c, args.limit)
    print(f"selected {len(parent_ids)} breaching text parents to give audio variants\n")

    # a throwaway config purely to exercise render() → audio in the dry-run
    probe_cfg = DeploymentConfig(
        config_id="acme-voxtral-20260604", customer_id="acme", name="probe",
        target_model="mistralai/voxtral-small-24b-2507",
        system_prompt="You are a helpful assistant.", declared_tools=[], forbidden_topics=[],
    )

    minted = skipped = render_fail = 0
    with Session(engine) as s:
        parents = {o.primitive_id: o for o in s.query(AttackPrimitiveORM)
                   .filter(AttackPrimitiveORM.primitive_id.in_(parent_ids))}
        for pid in parent_ids:
            parent = parents.get(pid)
            if parent is None:
                continue
            variant_id = f"{pid}{_AUDIO_SUFFIX}"
            if s.get(AttackPrimitiveORM, variant_id) is not None:
                skipped += 1
                continue
            variant = _build_audio_variant(parent)
            # verify it actually renders to audio before committing
            try:
                rendered = render(R._orm_to_pydantic_primitive(variant), probe_cfg)
                if not rendered.audio_b64:
                    print(f"  RENDER-NO-AUDIO {variant_id[:40]} (skipped)")
                    render_fail += 1
                    continue
            except Exception as exc:  # noqa: BLE001
                print(f"  RENDER-FAIL {variant_id[:40]}: {exc}")
                render_fail += 1
                continue
            if args.dry_run:
                print(f"  [dry] would mint {variant_id[:46]:46} audio={len(rendered.audio_b64)}b64")
            else:
                s.add(variant)
                print(f"  minted {variant_id[:46]:46} audio={len(rendered.audio_b64)}b64")
            minted += 1
        if not args.dry_run:
            s.commit()

    print(f"\n{'[DRY-RUN] ' if args.dry_run else ''}"
          f"audio variants {'to mint' if args.dry_run else 'minted'}={minted} "
          f"skipped(exist)={skipped} render_fail={render_fail}")
    if args.dry_run:
        print("→ re-run without --dry-run to persist. Then a normal reproduce sweep "
              "fires them at the 3 audio targets (text-only configs auto-skip).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
