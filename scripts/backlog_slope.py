#!/usr/bin/env python
"""Build the backlog SLOPE from one wide harvest, bucketed by source age.

After a `harvest_once --since 60d`, classify the harvested techniques by the age
of their source and accumulate the campaign metrics over widening windows — the
slope that decides 3b-v2 (growing → build; flat → parked), without running seven
separate harvests.

GRANULARITY (honest): the only stored age signal is the arXiv ID's year-month
(`claimed_first_seen` is unpopulated), so resolution is MONTHLY, not daily. The
7/14/21/30-day sub-buckets within the current month collapse to one point. Buckets
are therefore per arXiv month (≈ this-month / last-month / 2-months-ago = the
30/60/90-day cumulative points). Non-arXiv sources (no parseable date) bucket as
`undated` and are reported separately, not silently dropped.

Metrics per bucket (cumulative, newest→oldest): needs_implementation, discoverable
(data/discoverability.json), testable (panel modality support), actionable
(disc∩test), audio/image split.

    uv run python scripts/backlog_slope.py
"""

from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from track_backlog import _load_disc, _testable_modalities  # noqa: E402

_ARXIV = re.compile(r"arxiv\.org/(?:abs|pdf|html)/(\d{2})(\d{2})\.\d{4,5}", re.I)
# today is fixed-context (2026-06-04); month index = year*12+month for ordering
_TODAY_YM = 2026 * 12 + 6


def _ym(source_url: str) -> tuple[int, int] | None:
    """(year, month) from an arXiv id like 2606.03793 → (2026, 6). None if no id."""
    m = _ARXIV.search(source_url or "")
    if not m:
        return None
    yy, mm = int(m.group(1)), int(m.group(2))
    if not (1 <= mm <= 12):
        return None
    return 2000 + yy, mm


def main() -> int:
    load_dotenv(str(_ROOT / ".env"))
    e = create_engine(os.environ["DATABASE_URL"])
    disc = _load_disc()
    with e.connect() as c:
        testable_mods = _testable_modalities(c)
        rows = c.execute(text("""SELECT technique_id, modality, source_url
                                 FROM attack_strategies WHERE status='needs_implementation'""")).all()

    # bucket each parked technique by arXiv month
    by_ym: dict[tuple[int, int], list] = defaultdict(list)
    undated = []
    for r in rows:
        ym = _ym(r.source_url)
        if ym:
            by_ym[ym].append(r)
        else:
            undated.append(r)

    def metrics(items):
        nd = sum(1 for r in items if disc.get(r.technique_id) is True)
        nt = sum(1 for r in items if r.modality in testable_mods)
        na = sum(1 for r in items if disc.get(r.technique_id) is True and r.modality in testable_mods)
        au = sum(1 for r in items if r.modality == "audio")
        im = sum(1 for r in items if r.modality == "image")
        un = sum(1 for r in items if disc.get(r.technique_id) is None)
        return len(items), nd, nt, na, au, im, un

    months = sorted(by_ym, reverse=True)  # newest first
    print(f"parked techniques: {len(rows)}  ({len(undated)} undated/non-arXiv)\n")
    print("CUMULATIVE slope (newest month → older), the 3b-v2 decision curve:")
    print(f"  {'window':22} {'needs':>6} {'disc':>5} {'test':>5} {'action':>7} "
          f"{'audio':>6} {'image':>6} {'unassessed':>11}")
    cum: list = []
    approx_days = {0: "≤~30d (this month)", 1: "≤~60d (+last month)", 2: "≤~90d (+2mo)"}
    for i, ym in enumerate(months):
        cum.extend(by_ym[ym])
        n, nd, nt, na, au, im, un = metrics(cum)
        label = f"{ym[0]}-{ym[1]:02d}  {approx_days.get(i, f'+{ym[0]}-{ym[1]:02d}')}"
        print(f"  {label:22} {n:>6} {nd:>5} {nt:>5} {na:>7} {au:>6} {im:>6} {un:>11}")

    print("\nPER-MONTH (non-cumulative — the monthly arrival rate):")
    for ym in months:
        n, nd, nt, na, au, im, un = metrics(by_ym[ym])
        age = (_TODAY_YM - (ym[0] * 12 + ym[1]))
        print(f"  {ym[0]}-{ym[1]:02d} (~{age}mo ago): needs={n} disc={nd} test={nt} "
              f"action={na} (audio={au} image={im}) unassessed={un}")
    if undated:
        n, nd, nt, na, au, im, un = metrics(undated)
        print(f"  undated/non-arXiv: needs={n} (audio={au} image={im}) unassessed={un}")

    total_un = sum(1 for r in rows if disc.get(r.technique_id) is None)
    if total_un:
        print(f"\n  ⚠ {total_un} parked techniques are unassessed for discoverability — "
              f"run `track_backlog.py --assess` and fill data/discoverability.json so the "
              f"disc/action columns are complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
