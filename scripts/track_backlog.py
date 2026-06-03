#!/usr/bin/env python
"""Track the 3b-v2 trigger over time — backlog SIZE × DISCOVERABILITY × TESTABILITY.

The decision to build 3b-v2 is gated on backlog GROWTH RATE, not the absolute
(Soren 2026-06-04): 7→8→9 keeps 3b parked, 7→12→18 makes it inevitable. But size
alone is noise — a backlog of 14 gradient-optimization papers with no impl path is
worthless. What's actionable is:

    needs_implementation  ×  discoverable (has an open impl path)  ×  testable (panel
                                                                       has a target)

So each snapshot records all three. `needs_implementation`, modality split, and
`testable` are AUTOMATIC; `discoverable` is a per-technique human judgment stored in
`data/discoverability.json` (a search per technique — can't be free/auto). `--assess`
lays out the parked techniques with everything needed to make that judgment in ~2 min
and flags any not-yet-assessed; `snapshot()` then folds the counts into the campaign
CSV. snapshot() runs automatically at the end of every harvest (no cron).

    uv run python scripts/track_backlog.py --assess   # per-technique discoverable/testable view
    uv run python scripts/track_backlog.py --show      # the campaign trend (size + discoverable + testable)
    uv run python scripts/track_backlog.py             # take a snapshot now
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

HISTORY = _ROOT / "data" / "backlog_history.csv"
DISCOVERABILITY = _ROOT / "data" / "discoverability.json"
_FIELDS = ["ts", "run_id", "needs_implementation", "audio", "image",
           "discoverable", "testable", "actionable", "candidate", "active", "total_strategies"]


def _load_disc() -> dict[str, bool]:
    if DISCOVERABILITY.exists():
        return json.loads(DISCOVERABILITY.read_text())
    return {}


def _testable_modalities(c) -> set[str]:
    """Modalities the live panel can actually test, from its configs' target models."""
    from sqlalchemy import text

    from rogue.reproduce.target_panel import supports_audio, supports_image
    mods: set[str] = set()
    for (model,) in c.execute(text("SELECT target_model FROM deployment_configs")):
        if supports_audio(model):
            mods.add("audio")
        if supports_image(model):
            mods.add("image")
    return mods


def _parked(c) -> list[dict]:
    """The needs_implementation techniques with the fields a discoverability read needs."""
    from sqlalchemy import text
    rows = c.execute(text("""SELECT technique_id, modality, name, principle, source_url
                             FROM attack_strategies WHERE status='needs_implementation'
                             ORDER BY modality, created_at""")).all()
    return [{"id": r.technique_id, "modality": r.modality, "name": r.name,
             "principle": r.principle or "", "source_url": r.source_url or ""} for r in rows]


def _counts(database_url: str | None = None) -> dict[str, int]:
    from dotenv import load_dotenv
    from sqlalchemy import create_engine, text
    load_dotenv(str(_ROOT / ".env"))
    url = database_url or os.environ["DATABASE_URL"]
    disc = _load_disc()
    with create_engine(url).connect() as c:
        def scal(q: str) -> int:
            return c.execute(text(q)).scalar() or 0
        parked = _parked(c)
        testable_mods = _testable_modalities(c)
        n_testable = sum(1 for p in parked if p["modality"] in testable_mods)
        n_disc = sum(1 for p in parked if disc.get(p["id"]) is True)
        n_actionable = sum(1 for p in parked
                           if disc.get(p["id"]) is True and p["modality"] in testable_mods)
        return {
            "needs_implementation": len(parked),
            "audio": sum(1 for p in parked if p["modality"] == "audio"),
            "image": sum(1 for p in parked if p["modality"] == "image"),
            "discoverable": n_disc,
            "testable": n_testable,
            "actionable": n_actionable,
            "candidate": scal("SELECT count(*) FROM attack_strategies WHERE status='candidate'"),
            "active": scal("SELECT count(*) FROM attack_strategies WHERE status='active'"),
            "total_strategies": scal("SELECT count(*) FROM attack_strategies"),
        }


def snapshot(database_url: str | None = None, run_id: str = "", ts: str = "") -> dict[str, int]:
    """Append one campaign snapshot. ``ts`` is passed by the caller (the harvest has
    its own UTC clock) — this module never calls now() so it stays import-safe.
    Best-effort: callers wrap in try/except so a tracking failure never fails a harvest."""
    c = _counts(database_url)
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    new = not HISTORY.exists()
    with HISTORY.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=_FIELDS)
        if new:
            w.writeheader()
        w.writerow({"ts": ts, "run_id": run_id, **c})
    return c


def _assess(database_url: str | None = None) -> None:
    """Per-technique discoverable/testable view — the 2-minute discoverability read."""
    from dotenv import load_dotenv
    from sqlalchemy import create_engine
    load_dotenv(str(_ROOT / ".env"))
    url = database_url or os.environ["DATABASE_URL"]
    disc = _load_disc()
    with create_engine(url).connect() as c:
        parked = _parked(c)
        testable_mods = _testable_modalities(c)
    print(f"panel can test modalities: {sorted(testable_mods) or '(none)'}\n")
    print(f"{'discoverable':>12} {'testable':>9}  modality  technique")
    unassessed = []
    for p in parked:
        d = disc.get(p["id"])
        dstr = "yes" if d is True else "NO" if d is False else "??"
        if d is None:
            unassessed.append(p)
        t = "yes" if p["modality"] in testable_mods else "no"
        print(f"{dstr:>12} {t:>9}  {p['modality']:8}  {p['name'][:46]}")
        if d is None:
            print(f"{'':24}  └ {p['principle'][:80]}")
            print(f"{'':24}    {p['source_url']}")
    n = len(parked)
    nd = sum(1 for p in parked if disc.get(p["id"]) is True)
    nt = sum(1 for p in parked if p["modality"] in testable_mods)
    na = sum(1 for p in parked if disc.get(p["id"]) is True and p["modality"] in testable_mods)
    print(f"\n  needs_implementation={n}  discoverable={nd}  testable={nt}  ACTIONABLE(disc∩test)={na}")
    if unassessed:
        print(f"\n  ⚠ {len(unassessed)} not yet assessed — add a verdict to "
              f"{DISCOVERABILITY.relative_to(_ROOT)}:")
        print("    " + json.dumps({p["id"]: "true|false" for p in unassessed}))


def _show() -> None:
    if not HISTORY.exists():
        print("no history yet — run a harvest (or this script) to seed it.")
        return
    rows = list(csv.DictReader(HISTORY.open()))
    print(f"{'timestamp':17} {'needs_impl':>10} {'disc':>5} {'test':>5} {'actionable':>11} "
          f"{'cand':>5} {'active':>7}")
    prev = None
    for r in rows:
        ni = int(r["needs_implementation"])
        delta = f" {ni - prev:+d}" if prev is not None else ""
        g = lambda k: r.get(k, "") or "-"  # noqa: E731 — old rows lack the new columns
        print(f"{r['ts'][:16]:17} {ni:>7}{delta:3} {g('discoverable'):>5} {g('testable'):>5} "
              f"{g('actionable'):>11} {g('candidate'):>5} {g('active'):>7}")
        prev = ni
    if len(rows) >= 3:
        series = [int(r["needs_implementation"]) for r in rows][-3:]
        act = [r.get("actionable") for r in rows][-1]
        trend = ("GROWING → 3b-v2 trigger approaching" if series[-1] - series[0] >= 4
                 else "flat/slow → 3b stays parked" if series[-1] - series[0] <= 1 else "watch")
        print(f"\n  last-3 needs_impl: {series}  →  {trend}")
        print(f"  but the number that decides 3b is ACTIONABLE (disc∩test), now: {act}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--assess", action="store_true", help="per-technique discoverable/testable view")
    ap.add_argument("--show", action="store_true", help="print the campaign trend, no snapshot")
    ap.add_argument("--run-id", default="manual")
    args = ap.parse_args()
    if args.assess:
        _assess()
        return 0
    if args.show:
        _show()
        return 0
    import datetime
    c = snapshot(run_id=args.run_id, ts=datetime.datetime.now(datetime.timezone.utc).isoformat())
    print(f"snapshot: needs_implementation={c['needs_implementation']} "
          f"discoverable={c['discoverable']} testable={c['testable']} actionable={c['actionable']} "
          f"→ {HISTORY.relative_to(_ROOT)}")
    _show()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
