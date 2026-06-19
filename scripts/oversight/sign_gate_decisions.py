"""Sign a gated-decision run into the area-03 attestation hash chain (build-07 §5 capstone).

Turns an owner-exported ``oversight_decisions.json`` (from the click-to-review HTML) into a SIGNED,
replayable, tamper-evident record: one ``decision`` entry per decision, scored against the independent
key, framed as "threat-informed assurance … not a safety guarantee" (measure-don't-claim).

Run-deliberately. By default it signs into a LOCAL sqlite chain (a portable artifact you can verify
offline) — it does NOT touch Neon/production. Mirrors ``tests/attestation/test_service.py``'s offline
service setup.

    uv run python scripts/oversight/sign_gate_decisions.py --decisions oversight_decisions.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rogue.attestation.service import AttestationService
from rogue.db.models import Base
from rogue.oversight.attestation import append_gate_run
from rogue.oversight.case_corpus import GatedDecision, load_corpus
from rogue.oversight.disposition_judge import classify_decision, is_breach
from rogue.oversight.independence_lint import assert_corpus_independent
from rogue.oversight.scorer import score
from rogue.platform.models import AttestationEntry, Organization  # noqa: F401  (register tables)


def _build_service(db_path: str) -> AttestationService:
    url = "sqlite://" if db_path == ":memory:" else f"sqlite:///{db_path}"
    engine = create_engine(url)
    Base.metadata.create_all(
        engine, tables=[Organization.__table__, AttestationEntry.__table__]
    )
    return AttestationService(sessionmaker(bind=engine, expire_on_commit=False))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--decisions", required=True, help="owner-exported oversight_decisions.json")
    ap.add_argument("--corpus", default=None, help="corpus path (default: bundled fixture)")
    ap.add_argument("--org-id", default="oversight-demo")
    ap.add_argument("--reviewer", default="human-1")
    ap.add_argument("--db", default="data/oversight_attestation.db",
                    help="local sqlite chain file (':memory:' for ephemeral)")
    ap.add_argument("--corpus-as-of", default="2026-06-11",
                    help="the date the answer key is fixed against (YYYY-MM-DD)")
    args = ap.parse_args()

    cases = load_corpus(args.corpus)
    raw = json.loads(Path(args.decisions).read_text())
    decided_at = datetime.now(timezone.utc)
    decisions = [
        GatedDecision(
            case_id=r["case_id"],
            reviewer=r.get("reviewer", args.reviewer),
            decision=r["decision"],
            deliberation_notes=r.get("deliberation_notes"),
            decision_latency_s=r.get("decision_latency_s"),
            decided_at=decided_at,
        )
        for r in raw
    ]

    # 1) the key must be independent before any signed claim ships (ADR-0011, spec §3 + §5).
    assert_corpus_independent(cases)
    print("✅ answer key passed independence_lint (regulation/vote/verifier-independent)")

    # 2) the number being signed.
    report = score(decisions, cases)
    print(f"\nmeasurement: {report.summary_line()}")

    # 3) sign the COMPLETE run — one tamper-evident `decision` entry per decision.
    corpus_as_of = datetime.fromisoformat(args.corpus_as_of).replace(tzinfo=timezone.utc)
    if args.db != ":memory:":
        Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    service = _build_service(args.db)
    entries = append_gate_run(service, args.org_id, decisions, cases, corpus_as_of=corpus_as_of)
    print(f"\nsigned {len(entries)} `decision` entries into the chain (org={args.org_id}, db={args.db})")

    # 4) verify the chain + show a sample breach entry.
    v = service.verify(args.org_id)
    head = service.list_entries(args.org_id, limit=1)[0] if entries else None
    print(f"chain verify: ok={v.ok}" + ("" if v.ok else f" broken_at_seq={v.broken_at_seq}"))
    if head is not None:
        print(f"chain head: seq={head.seq} entry_hash={head.entry_hash[:16]}…")
    sample = next(
        (d for d in decisions if is_breach(classify_decision(d, {c.case_id: c for c in cases}[d.case_id]))),
        None,
    )
    if sample is not None:
        case = {c.case_id: c for c in cases}[sample.case_id]
        print(
            f"\nsample SIGNED false-approve: case={sample.case_id} ({case.case_class}) "
            f"decided=APPROVE vs key=DENY → breach recorded, ground_truth_ref=oversight-corpus:{sample.case_id}"
        )
    print("\nframing: threat-informed assurance, NOT a safety guarantee — measured against this "
          f"constructed corpus as of {args.corpus_as_of}; no claim the gate improves accuracy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
