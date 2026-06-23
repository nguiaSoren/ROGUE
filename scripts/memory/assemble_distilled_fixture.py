#!/usr/bin/env python3
"""Assemble + validate the real-Trace2Skill-distilled canary fixture (caveat 4a).

Merges the 5 per-domain shards in data/research/trace2skill_fixture/shard_*.json (each a
list of canary entries produced by the Wave-A distillation team) into a single fixture in
the exact schema rogue.memory.leakage._load_canaries reads, then enforces the invariants a
reviewer would check before this can back a published number:

  - 7 required fields per entry (+ provenance) ; skill_ids globally unique
  - canary_value contains the literal "CANARY" sentinel
  - canary_value appears verbatim in original_md_with_canary
  - canary_value is ABSENT from scrubbed_md (the shared/leak-tested body), and the body
    carries a [REDACTED] placeholder where the secret was
  - >=1 recovery_markers, and every marker is a substring of original_md_with_canary
  - provenance records a real source_skill_url + distilled_by=trace2skill

Writes tests/fixtures/memory/leakage_canaries_distilled.json (drop-in for --canary-path).
Exit 0 = clean; exit 1 = at least one invariant violated (prints every violation).

Usage:  uv run python scripts/memory/assemble_distilled_fixture.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHARD_DIR = ROOT / "data" / "research" / "trace2skill_fixture"
OUT = ROOT / "tests" / "fixtures" / "memory" / "leakage_canaries_distilled.json"

REQUIRED = {"skill_id", "canary_type", "canary_value", "original_md_with_canary",
            "scrubbed_md", "recovery_markers"}
FIXTURE_FIELDS = ["skill_id", "canary_type", "canary_value", "original_md_with_canary",
                  "scrubbed_md", "recovery_markers", "provenance"]


def main() -> int:
    shards = sorted(SHARD_DIR.glob("shard_*.json"))
    if not shards:
        print(f"no shards under {SHARD_DIR}")
        return 1

    entries: list[dict] = []
    violations: list[str] = []
    seen_ids: set[str] = set()
    by_domain: dict[str, int] = {}
    by_type: dict[str, int] = {}

    for shard in shards:
        recs = json.loads(shard.read_text())
        if not isinstance(recs, list):
            violations.append(f"{shard.name}: not a JSON list")
            continue
        for rec in recs:
            sid = rec.get("skill_id", "<no-id>")
            missing = REQUIRED - set(rec)
            if missing:
                violations.append(f"{sid}: missing fields {sorted(missing)}")
                continue
            if sid in seen_ids:
                violations.append(f"{sid}: duplicate skill_id")
            seen_ids.add(sid)
            cv = rec["canary_value"]
            if "CANARY" not in cv:
                violations.append(f"{sid}: canary_value lacks 'CANARY' sentinel ({cv!r})")
            if cv not in rec["original_md_with_canary"]:
                violations.append(f"{sid}: canary_value not present in original_md_with_canary")
            if cv in rec["scrubbed_md"]:
                violations.append(f"{sid}: LEAK — canary_value present in scrubbed_md (shared body)")
            if "[REDACTED]" not in rec["scrubbed_md"]:
                violations.append(f"{sid}: no [REDACTED] placeholder in scrubbed_md")
            markers = rec.get("recovery_markers") or []
            if not markers:
                violations.append(f"{sid}: empty recovery_markers")
            for m in markers:
                if m not in rec["original_md_with_canary"]:
                    violations.append(f"{sid}: recovery_marker {m!r} not in original_md_with_canary")
            prov = rec.get("provenance") or {}
            if not prov.get("source_skill_url"):
                violations.append(f"{sid}: provenance missing source_skill_url")
            if prov.get("distilled_by") != "trace2skill":
                violations.append(f"{sid}: provenance.distilled_by != 'trace2skill'")
            by_domain[prov.get("domain", "?")] = by_domain.get(prov.get("domain", "?"), 0) + 1
            by_type[rec["canary_type"]] = by_type.get(rec["canary_type"], 0) + 1
            entries.append({k: rec[k] for k in FIXTURE_FIELDS if k in rec})

    print(f"shards: {[s.name for s in shards]}")
    print(f"entries: {len(entries)}   unique skill_ids: {len(seen_ids)}")
    print(f"canary types: {by_type}")
    print(f"domains: {len(by_domain)} distinct")

    # sanity: every entry must load as a ScrubbedSkill and read as a canary
    sys.path.insert(0, str(ROOT / "src"))
    from rogue.memory.leakage import ScrubbedSkill  # noqa: E402
    for e in entries:
        s = ScrubbedSkill(skill_id=e["skill_id"], scrubbed_md=e["scrubbed_md"],
                          recovery_markers=tuple(e["recovery_markers"]),
                          protected_content=e["canary_value"], canary_type=e["canary_type"])
        if not s.is_canary:
            violations.append(f"{e['skill_id']}: loads as non-canary (no recovery_markers)")

    if violations:
        print(f"\n{len(violations)} VIOLATIONS:")
        for v in violations:
            print(f"  X {v}")
        return 1

    OUT.write_text(json.dumps(entries, indent=2, ensure_ascii=False))
    print(f"\nOK — wrote {len(entries)} validated distilled canary skills to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
