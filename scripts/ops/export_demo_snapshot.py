"""Export a REDACTED snapshot of the live all-time matrix → a demo seed fixture.

The public dashboard (rogue-eosin.vercel.app/matrix) already serves the aggregate matrix
(verdicts → breach rates) openly, so the rates/metadata carry no new exposure. The SENSITIVE
parts are the free-text payloads + model responses — exactly what the gated HF dataset guards.
This exporter ships verdicts + rates + family/config/primitive METADATA only, and replaces every
free-text payload / response / rationale with a "[redacted]" placeholder (the cell drawer then
shows "[redacted]", identical to the live site). The pgvector embedding is dropped entirely.

Read-only against $DATABASE_URL (Neon). Writes tests/fixtures/demo_snapshot.json.gz.
Run deliberately: `uv run python scripts/ops/export_demo_snapshot.py`.
"""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path

from sqlalchemy import create_engine, text

REDACT = "[redacted]"
OUT = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "demo_snapshot.json.gz"

# Per-table: columns DROPPED from the export entirely (never shipped), and free-text columns
# REDACTED to a constant placeholder. Everything else (ids, enums, numbers, timestamps, booleans)
# is rate/label metadata and ships as-is — the same data the public matrix already exposes.
SPEC = {
    "deployment_configs": {"drop": set(), "redact": {"system_prompt"}, "nullify": set()},
    "attack_primitives": {
        "drop": {"payload_embedding"},
        "redact": {
            "short_description", "payload_template", "payload_slots",
            "multi_turn_sequence", "severity_rationale", "notes",
        },
        # Self-referential FK (mutation/escalation lineage) — not needed for the matrix, and some
        # parents fall outside the exported set; null it so the bundle inserts without FK ordering.
        "nullify": {"derived_from_primitive_id"},
    },
    "breach_results": {
        "drop": set(),
        "redact": {"rendered_payload", "model_response", "judge_rationale"},
        "nullify": set(),
    },
}


def _columns(conn, table: str) -> list[str]:
    rows = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = :t ORDER BY ordinal_position"
        ),
        {"t": table},
    ).fetchall()
    return [r[0] for r in rows]


def _redact_value(v):
    # A redacted column is forced to the placeholder string regardless of its original type
    # (JSON columns get a JSON string; the seed inserts it verbatim, the drawer shows "[redacted]").
    return REDACT


def main() -> None:
    db = os.environ["DATABASE_URL"]
    engine = create_engine(db)
    snapshot: dict[str, list[dict]] = {}
    with engine.connect() as conn:
        for table, spec in SPEC.items():
            cols = [c for c in _columns(conn, table) if c not in spec["drop"]]
            ship_cols = ", ".join(cols)
            rows = conn.execute(text(f"SELECT {ship_cols} FROM {table}")).mappings().all()
            out_rows = []
            for r in rows:
                d = {}
                for c in cols:
                    if c in spec["redact"]:
                        d[c] = _redact_value(r[c])
                    elif c in spec["nullify"]:
                        d[c] = None
                    else:
                        v = r[c]
                        # JSON/array/None pass through; timestamps → ISO strings for portability.
                        d[c] = v.isoformat() if hasattr(v, "isoformat") else v
                out_rows.append(d)
            snapshot[table] = out_rows
            print(f"  {table:22} {len(out_rows)} rows ({len(cols)} cols, "
                  f"dropped={sorted(spec['drop'])}, redacted={sorted(spec['redact'])})")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, default=str)
    print(f"\n  wrote {OUT}  ({OUT.stat().st_size / 1024:.0f} KB gzipped)")


if __name__ == "__main__":
    main()
