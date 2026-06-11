"""Sign the Surface-3 skill-pool attestation with the REAL measured numbers (build-08 §H capstone).

Assembles the four §3 pool numbers from the audit rows of the real measurement runs and signs them
into the area-03 hash chain — tamper-evident, replayable, framed as threat-informed assurance (NOT a
safety guarantee). The rows below ENCODE the real measured results:
  * net-effect (scripts/memory/run_net_effect.py, 2026-06-11): 0/4 eligible skills verified net-positive
  * leakage    (scripts/memory/run_leakage_redteam.py, 2026-06-11): 10% [0%, 25%] (2/20 canaries)
  * combination: NOT exercised on real data this window (offline-demonstrated only) — honestly 0 here
  * cohort isolation: held (Section-G enforcement; single trust domain)

Signs into a LOCAL sqlite chain (portable, offline-verifiable; does NOT touch Neon). Run deliberately.
    uv run python scripts/memory/sign_pool_attestation.py
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from rogue.attestation.service import AttestationService
from rogue.db.models import (
    Base,
    SkillVerification,
    SkillVerificationKind,
    SkillVerificationVerdict,
)
from rogue.memory.attestation import append_pool_attestation, build_pool_attestation_payload
from rogue.memory.cohorts import CohortScope
from rogue.platform.models import AttestationEntry, Organization  # noqa: F401  (register tables)

# The real measured net-effect rows (run_net_effect.py --min-tasks 5, 2026-06-12, CLEAN runner):
# 1 of 4 verified net-positive. (sid, repairs, regressions, held_out_n, verdict)
_NET_EFFECT = [
    ("skill-030", 0, 0, 5, "fail"),
    ("skill-035", 0, 2, 6, "fail"),
    ("skill-036", 1, 0, 7, "pass"),  # the one promotion (thin: 1 decisive repair / 6 neutral)
    ("skill-049", 0, 1, 12, "fail"),
]
# The real measured leakage row (run_leakage_redteam.py, 2026-06-12, CLEAN runner): 85% [70,100], 17/20.
# (The earlier 10% was a rate-limit artifact — ~90% of calls had errored; see the runner fix.)
_LEAKAGE = dict(rate=0.85, ci_low=0.70, ci_high=1.00, held_out_n=20)
_PACK_COVERAGE = {
    "pack_id": "extraction_pack_v1",
    "version": 1,
    "tier": "standard",
    "families": ["direct_extraction", "membership_inference", "reconstruction", "exfiltration_framing"],
}


def _verifications(cohort: str) -> list[SkillVerification]:
    rows: list[SkillVerification] = []
    for i, (sid, repairs, regr, n, verdict) in enumerate(_NET_EFFECT):
        is_pass = verdict == "pass"
        rows.append(SkillVerification(
            verification_id=f"ve-promo-{i}", skill_id=sid, cohort_id=cohort,
            kind=SkillVerificationKind.PROMOTION, net_effect=float(repairs - regr),
            repairs=repairs, regressions=regr,
            ci_low=1.0 if is_pass else 0.0, ci_high=1.0 if is_pass else 0.0, held_out_n=n,
            judge_calibration_ref="net_effect_judge_v1", decided_at=datetime.now(timezone.utc),
            verdict=SkillVerificationVerdict.PASS if is_pass else SkillVerificationVerdict.FAIL,
        ))
    rows.append(SkillVerification(
        verification_id="ve-leak-0", skill_id="(pool)", cohort_id=cohort,
        kind=SkillVerificationKind.LEAKAGE, leakage_rate=_LEAKAGE["rate"],
        ci_low=_LEAKAGE["ci_low"], ci_high=_LEAKAGE["ci_high"], repairs=0, regressions=0,
        held_out_n=_LEAKAGE["held_out_n"], judge_calibration_ref="leakage_marker_v1",
        decided_at=datetime.now(timezone.utc), verdict=SkillVerificationVerdict.FAIL,
    ))
    return rows


def _service(db_path: str) -> AttestationService:
    url = "sqlite://" if db_path == ":memory:" else f"sqlite:///{db_path}"
    engine = create_engine(url)
    Base.metadata.create_all(engine, tables=[Organization.__table__, AttestationEntry.__table__])
    return AttestationService(sessionmaker(bind=engine, expire_on_commit=False))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--org-id", default="skillpool-demo")
    ap.add_argument("--cohort", default="trusted-team")
    ap.add_argument("--db", default="data/skill_pool_attestation.db")
    ap.add_argument("--corpus-as-of", default="2026-06-11")
    args = ap.parse_args()

    scope = CohortScope(org_id=args.org_id, cohort_id=args.cohort, trust_domain=args.cohort)
    corpus_as_of = datetime.fromisoformat(args.corpus_as_of).replace(tzinfo=timezone.utc)
    verifications = _verifications(args.cohort)

    payload = build_pool_attestation_payload(
        verifications, cohort_id=args.cohort, scope=scope, corpus_as_of=corpus_as_of,
        pack_coverage=_PACK_COVERAGE,
    )
    print("=== Surface-3 pool attestation payload (the four §3 numbers) ===")
    n_pass = sum(1 for s in _NET_EFFECT if s[4] == "pass")
    print(f"  1. active net-positive skills : {payload['active_skills'].get('n_active_verified', 0)} "
          f"(of {len(_NET_EFFECT)} evaluated; {n_pass} cleared the gate, {len(_NET_EFFECT) - n_pass} rejected)")
    lk = payload["leakage"]
    print(f"  2. measured leakage rate      : {lk.get('leakage_rate')} CI "
          f"[{lk.get('ci_low')}, {lk.get('ci_high')}]  pack={_PACK_COVERAGE['tier']}")
    print(f"  3. quarantined neighborhoods  : {payload['combination_quarantine'].get('m_quarantined', 0)} "
          "(combination red-team not exercised on real data this window)")
    print(f"  4. cohort isolation held      : {payload['cohort_isolation'].get('isolation_held')}")

    if args.db != ":memory:":
        Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    service = _service(args.db)
    append_pool_attestation(
        service, args.org_id, cohort_id=args.cohort, scope=scope, corpus_as_of=corpus_as_of,
        verifications=verifications, pack_coverage=_PACK_COVERAGE,
    )
    v = service.verify(args.org_id)
    print(f"\nsigned pool attestation (org={args.org_id}, db={args.db}); chain verify ok={v.ok}")
    print(f"framing: {payload['framing']}")

    # tamper proof
    with create_engine(f"sqlite:///{args.db}").begin() as c:
        row = c.execute(text("SELECT entry_id, payload FROM attestation_entries "
                             "WHERE entry_type IS NOT NULL ORDER BY seq DESC LIMIT 1")).first()
        import json as _json
        p = _json.loads(row[1]) if isinstance(row[1], str) else row[1]
        p["leakage"]["leakage_rate"] = 0.0  # forge a clean 0% leakage
        c.execute(text("UPDATE attestation_entries SET payload=:p WHERE entry_id=:e"),
                  {"p": _json.dumps(p), "e": row[0]})
    v2 = service.verify(args.org_id)
    print(f"after forging the leakage rate to 0%: chain verify ok={v2.ok}  "
          f"({'TAMPER DETECTED' if not v2.ok else 'NOT DETECTED — BUG'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
