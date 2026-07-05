"""Repair same-source (arxiv) re-harvest duplicates in the live corpus.

Root cause (see scripts/research/p3_dedup_sensitivity.py): the harvest re-extracts
the same arxiv paper across days into slightly different wording, which slips past
the cosine-dedup gate and seeds a fresh singleton cluster. The forward fix lives
in fetch_cache.py (URL-level idempotency). This script cleans up the rows already
in the DB so the dashboard cells and breach cards stop listing one paper N times.

NON-DESTRUCTIVE by construction:
  * primitives are NOT deleted and breach_results are NOT re-pointed — P3's frozen
    snapshot pins primitives by primitive_id + ran_at, so deleting/moving trials
    would break the released reproducibility_gap_pairs.csv. We only rewrite
    ``cluster_id`` + ``canonical`` (columns P3 does not read), so every published
    number is unchanged.
  * for each arxiv URL backing >1 primitive, the earliest-discovered primitive
    stays canonical and the rest join its cluster as non-canonical. The dashboard
    then collapses each cell to one row per cluster (worst-breaching).
  * one hand-picked reclassification: the NEXTAUTH_SECRET blog primitive
    (a web-framework session-secret vuln misfiled under training_data_extraction)
    moves to system_prompt_leak.

Usage:
  uv run python scripts/research/repair_arxiv_dup_clusters.py           # dry-run
  uv run python scripts/research/repair_arxiv_dup_clusters.py --apply   # write
Idempotent: re-running --apply is a no-op once the corpus is clean.
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]
APPLY = "--apply" in sys.argv

NEXTAUTH_ID = "01KSGQK94NWYFAYMR54MC6KTPW"
NEXTAUTH_NEW_FAMILY = "system_prompt_leak"  # from training_data_extraction

os.environ.update({k: v for k, v in dotenv_values(ROOT / ".env").items() if v})
eng = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)

GROUPS_SQL = """
WITH pu AS (SELECT primitive_id, MIN(url) url FROM source_provenances GROUP BY primitive_id)
SELECT pu.url, ap.primitive_id, ap.discovered_at, ap.cluster_id, ap.canonical
FROM pu JOIN attack_primitives ap ON ap.primitive_id = pu.primitive_id
WHERE pu.url LIKE '%arxiv.org%'
  AND pu.url IN (SELECT url FROM pu WHERE url LIKE '%arxiv.org%' GROUP BY url HAVING COUNT(*) > 1)
ORDER BY pu.url, ap.discovered_at
"""


def main() -> None:
    with eng.begin() as c:
        rows = c.execute(text(GROUPS_SQL)).all()
        groups: dict[str, list] = defaultdict(list)
        for r in rows:
            groups[r.url].append(r)

        planned = []  # (dup_id, canonical_id)
        for url, ps in groups.items():
            canon = ps[0].primitive_id  # earliest discovered
            for d in ps[1:]:
                # already merged? (idempotent)
                if d.cluster_id == canon and d.canonical is False:
                    continue
                planned.append((d.primitive_id, canon))

        # NEXTAUTH reclassification (idempotent)
        cur_fam = c.execute(
            text("SELECT family::text FROM attack_primitives WHERE primitive_id = :p"),
            {"p": NEXTAUTH_ID},
        ).scalar()
        reclass = cur_fam is not None and cur_fam != NEXTAUTH_NEW_FAMILY

        print(f"arxiv dup groups: {len(groups)} | re-cluster merges pending: {len(planned)}")
        for dup, canon in planned:
            print(f"  cluster_id[{dup}] -> {canon}, canonical=False")
        print(
            f"NEXTAUTH reclass: {cur_fam} -> {NEXTAUTH_NEW_FAMILY}"
            if reclass
            else f"NEXTAUTH reclass: already {cur_fam} (skip)"
        )

        if not APPLY:
            print("\n[dry-run] no writes. Re-run with --apply to execute.")
            return

        for dup, canon in planned:
            c.execute(
                text(
                    "UPDATE attack_primitives SET cluster_id = :canon, canonical = false "
                    "WHERE primitive_id = :dup"
                ),
                {"canon": canon, "dup": dup},
            )
        if reclass:
            c.execute(
                text(
                    "UPDATE attack_primitives SET family = :fam WHERE primitive_id = :p"
                ),
                {"fam": NEXTAUTH_NEW_FAMILY, "p": NEXTAUTH_ID},
            )
        print(f"\n[applied] {len(planned)} re-clusters"
              + (", 1 reclassification" if reclass else ""))


if __name__ == "__main__":
    main()
