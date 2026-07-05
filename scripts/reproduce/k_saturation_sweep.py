#!/usr/bin/env python
"""K-saturation sweep driver (P1 scheduler paper).

Orchestrates the frozen-batch K-curve + the measured greedy 0/20 arm described in
`docs/research/k_saturation_run_spec.md`. It does NOT itself decide to spend: the
default is a FREE preview (per-K `--dry-run`, reporting pool depth + the frozen
candidate batch). Real spend happens only with `--execute`, and even then is
hard-capped per K via `--escalate-max-spend`.

Why a driver at all: each K-point must start from the SAME candidate pool, but a
growth sweep graduates candidates (status→ACTIVE) and bumps n_attempts_total, so
a naive re-run sees a different batch. Two isolation modes:

  --db-mode branch    (PREFERRED, safest)
      You pre-create one disposable Neon branch per K (Neon console / API — no
      neonctl on this box) and pass their URLs. Each K runs against its own
      branch; the base pool is never mutated. Botched run? Discard the branch.

  --db-mode snapshot  (fallback, mutates the target DB in place)
      Snapshots the CANDIDATE rows into `_ks_snapshot`, runs each K, and restores
      in a finally. Requires `--confirm`. A SIGKILL between run and restore leaves
      the pool mutated — recover with `--restore-from-snapshot`. Prefer running
      this against a branch too, so even a failed restore only harms a throwaway.

Critical safety baked in (discovered the hard way): `reproduce_once.main()` always
runs an idempotent `maybe_auto_sync` into NEON_DATABASE_URL and a local analytics
refresh, EVEN under --dry-run. For experimental runs that would leak branch data
into the primary display tables — so this driver UNSETS `NEON_DATABASE_URL` and
leaves `ROGUE_AUTO_PUBLISH_ANALYTICS` off for every child run. It also sets
`PYTHONPATH=.` (required: reproduce_once imports `scripts.*`).

Run order (per CLAUDE.md): paid runs only on explicit go, never on a loop.

    # FREE preview — pool depth + frozen batch, no spend, no experiment writes:
    uv run python scripts/reproduce/k_saturation_sweep.py --k-grid 3,10,20,40

    # PAID — branch mode (preferred):
    uv run python scripts/reproduce/k_saturation_sweep.py --execute \\
        --k-grid 3,10,20,40 --greedy-arm \\
        --db-mode branch --branch-urls "3=URL,10=URL,20=URL,40=URL,greedy=URL" \\
        --max-spend-per-k 16

    # recover a botched snapshot-mode run:
    uv run python scripts/reproduce/k_saturation_sweep.py --restore-from-snapshot
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

OUT = _ROOT / "data" / "research" / "k_saturation_runs.json"
REPRODUCE = "scripts/reproduce/reproduce_once.py"

# The published 6-model panel (recovered from breach_results volume: 5 primaries
# ~2.1-2.3k trials each + partial Claude-Opus 537). Restricting to these keeps the
# K-curve apples-to-apples with $14.57@K=20 AND excludes the post-publication
# Featherless `fl-*` leaderboard configs (Qwen/DeepSeek/GLM/MiniMax), most of which
# are unrouted by the escalation panel and would crash the sweep.
PUBLISHED_PANEL = ",".join([
    "acme-geminiflashlite-20260526", "acme-claudehaiku-20260526",
    "acme-gpt54nano-20260526", "acme-mistralsm-20260526",
    "acme-llama3-20260526", "acme-claudeopus-20260531",
])

# Columns graduate()/record_trial() mutate — the full restore set for snapshot mode.
_SNAP_COLS = (
    "status", "n_attempts_total", "n_valid_trials", "last_tried_at",
    "n_breaches", "first_breach_at", "first_breach_config_id",
    "last_breached_at", "resurrected",
)


# ---- notifications (best-effort, from the script per memory notify_dont_babysit) ----
def _slack(msg: str) -> None:
    url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not url:
        return
    try:
        import urllib.request

        req = urllib.request.Request(
            url, data=json.dumps({"text": f"[k-sat] {msg}"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as exc:  # noqa: BLE001  (notification must never crash the run)
        print(f"  (slack notify failed: {exc})")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- child-run env: isolate from primary Neon + the auto-sync/publish side effects ----
def _child_env(database_url: str | None, cap: int, ladder_order: str) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = "."                       # reproduce_once imports scripts.*
    env["CAND_LADDER_CAP"] = str(cap)             # selection cap K
    # ROGUE_LADDER_ORDER: deployed default is 'contextual' (candidates promoted to
    # the front → breach cheap/early, breaking the economic-inversion mechanism).
    # The published K-curve used 'starvation' (candidates LAST, quota forces the full
    # rotation = the fixed cost candidates ride). Must set it or the curve is wrong.
    env["ROGUE_LADDER_ORDER"] = ladder_order
    # CRITICAL: set these EMPTY, do NOT pop. The child calls load_dotenv(override=False),
    # which restores any var ABSENT from the env from .env — so popping NEON_DATABASE_URL
    # lets it come back and maybe_auto_sync mirrors the branch → PRIMARY Neon. A
    # present-but-empty value survives load_dotenv and makes maybe_auto_sync no-op
    # (`if not neon_url: return`). Same for the analytics auto-publish flag.
    env["NEON_DATABASE_URL"] = ""                 # do NOT mirror experiment → primary
    env["ROGUE_AUTO_PUBLISH_ANALYTICS"] = "0"     # do NOT publish experiment analytics
    if database_url:
        env["DATABASE_URL"] = database_url
    return env


def _assert_isolation(database_url: str, cap: int, ladder_order: str) -> str:
    """FAIL-CLOSED isolation gate. Runs load_dotenv() EXACTLY as the child does,
    inside the child's env, and verifies the END STATE rather than trusting the
    suppression mechanism: (a) the child's effective DATABASE_URL points at THIS
    branch, and (b) the sync target NEON_DATABASE_URL is empty so maybe_auto_sync
    no-ops. This is the durable lesson of the 2026-06-19 incident — suppression
    via env was silently reverted by the child's load_dotenv(); checking the
    post-load end state catches ANY future silent revert, not just that one.
    Raises (→ the arm is skipped, no spend) if either invariant fails.
    """
    # load_dotenv() with no args uses find_dotenv(), which fails under `python -c`
    # (no __file__); the explicit path has the same override=False semantics the
    # child relies on and faithfully shows whether .env would restore NEON.
    code = (f"from dotenv import load_dotenv; load_dotenv({str(_ROOT / '.env')!r}); "
            "import os; print((os.environ.get('DATABASE_URL') or '')+chr(9)+"
            "(os.environ.get('NEON_DATABASE_URL') or ''))")
    p = subprocess.run(["uv", "run", "python", "-c", code], cwd=str(_ROOT),
                       env=_child_env(database_url, cap, ladder_order),
                       capture_output=True, text=True)
    # NB: do NOT .strip() — when NEON is empty the line ends in a tab that strip()
    # would eat, making a clean (good) end-state look unparseable. Keep the tab.
    lines = [ln for ln in p.stdout.splitlines() if "\t" in ln]
    if not lines:
        raise RuntimeError(f"isolation probe produced no readable end-state: {p.stderr[-200:]}")
    eff_db, eff_neon = lines[-1].split("\t", 1)
    exp_host = database_url.split("@")[1].split("/")[0]
    eff_host = eff_db.split("@")[1].split("/")[0] if "@" in eff_db else "<none>"
    if eff_host != exp_host:
        raise RuntimeError(f"ISOLATION FAIL: child DATABASE_URL host {eff_host!r} != branch {exp_host!r}")
    if eff_neon.strip():
        raise RuntimeError("ISOLATION FAIL: child NEON_DATABASE_URL is non-empty "
                           "→ maybe_auto_sync would mirror to primary")
    return exp_host


def _run_reproduce(*, cap: int, quota: int, database_url: str | None, dry_run: bool,
                   primitive_limit: int, n_trials: int, ladder_order: str,
                   config_ids: str = "", max_spend: float | None = None) -> dict:
    """Invoke one reproduce_once escalation run; parse run_id/spend/plans/candidates.

    --primitive-limit + --n-trials bound the BASELINE reproduction. Without them
    main() runs the full 433-primitive sweep (~52k calls), which --escalate-max-spend
    does NOT cap. The published points used limit=12, n_trials=1; we match them so
    the baseline stays ~$3 and the curve is apples-to-apples with $14.57@K=20.
    """
    cmd = ["uv", "run", "python", REPRODUCE, "--escalate",
           "--candidate-quota", str(quota),
           "--primitive-limit", str(primitive_limit), "--n-trials", str(n_trials)]
    if config_ids:
        cmd += ["--config-ids", config_ids]
    if dry_run:
        cmd.append("--dry-run")
    if max_spend is not None and not dry_run:
        cmd += ["--escalate-max-spend", str(max_spend)]
    # DB is passed via env (DATABASE_URL in _child_env), NEVER on argv — so branch
    # credentials don't leak into the process list, this print, or any log.
    db_tag = (f"<branch:{cap}{'/greedy' if quota == 0 else ''} order={ladder_order}>"
              if database_url else f"<env order={ladder_order}>")
    print(f"  $ CAND_LADDER_CAP={cap} DATABASE_URL={db_tag} {' '.join(cmd)}")
    proc = subprocess.run(
        cmd, cwd=str(_ROOT), env=_child_env(database_url, cap, ladder_order),
        capture_output=True, text=True,
    )
    out = proc.stdout + "\n" + proc.stderr
    rec: dict = {"cap": cap, "quota": quota, "dry_run": dry_run,
                 "returncode": proc.returncode, "ts": _now()}
    # frozen batch (printed by the dry-run/plan): "candidates selected:    N [id, id, ...]"
    m = re.search(r"candidates selected:\s*(\d+)\s*\[([^\]]*)\]", out)
    if m:
        rec["candidates_selected"] = int(m.group(1))
        rec["candidate_ids"] = [s.strip() for s in m.group(2).split(",") if s.strip()]
    # paid run summary: "run_id=XXX done: ... escalation_spend=$Y ... plans=Z"
    m = re.search(r"run_id=(\w+)\s+done:", out)
    if m:
        rec["run_id"] = m.group(1)
    m = re.search(r"escalation_spend=\$([0-9.]+)", out)
    if m:
        rec["escalation_spend"] = float(m.group(1))
    m = re.search(r"plans=(\d+)", out)
    if m:
        rec["plans_generated"] = int(m.group(1))
    if proc.returncode != 0:
        rec["error_tail"] = "\n".join(out.strip().splitlines()[-15:])
    return rec


# ---- snapshot-mode DB helpers (fallback only) ----
def _engine(url: str):
    from sqlalchemy import create_engine

    return create_engine(url)


def _snapshot(url: str) -> None:
    from sqlalchemy import text

    cols = ", ".join(_SNAP_COLS)
    with _engine(url).begin() as c:
        c.execute(text("DROP TABLE IF EXISTS _ks_snapshot"))
        c.execute(text(
            f"CREATE TABLE _ks_snapshot AS SELECT technique_id, {cols} "
            "FROM attack_strategies WHERE status = 'CANDIDATE'"
        ))
        n = c.execute(text("SELECT count(*) FROM _ks_snapshot")).scalar()
    print(f"  snapshot: {n} candidate rows → _ks_snapshot")


def _restore(url: str) -> None:
    from sqlalchemy import text

    setters = ", ".join(f"{col} = s.{col}" for col in _SNAP_COLS)
    with _engine(url).begin() as c:
        if not c.execute(text("SELECT to_regclass('_ks_snapshot')")).scalar():
            print("  restore: no _ks_snapshot table — nothing to do")
            return
        n = c.execute(text(
            f"UPDATE attack_strategies a SET {setters} "
            "FROM _ks_snapshot s WHERE a.technique_id = s.technique_id"
        )).rowcount
    print(f"  restore: {n} candidate rows reset from _ks_snapshot")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--k-grid", default="3,10,20,40",
                    help="comma K values (default the 4-point bracket {3,10,20,40})")
    ap.add_argument("--greedy-arm", action="store_true",
                    help="also run quota=0 over the max-K cap (the measured 0/20 baseline)")
    ap.add_argument("--execute", action="store_true",
                    help="actually spend; without it, FREE dry-run preview only")
    ap.add_argument("--db-mode", choices=["branch", "snapshot"],
                    help="required with --execute: branch (preferred) or snapshot (in-place)")
    ap.add_argument("--branch-urls", default="",
                    help='branch mode: "3=URL,10=URL,...,greedy=URL" (one disposable branch per K)')
    ap.add_argument("--branch-urls-file", default="",
                    help="branch mode: JSON {tag: url | {url: ...}} — keeps URIs off argv")
    ap.add_argument("--max-spend-per-k", type=float, default=16.0,
                    help="hard $ cap per run (default 16; caps escalation, not baseline)")
    ap.add_argument("--primitive-limit", type=int, default=12,
                    help="baseline primitive cap (default 12, matches published methodology)")
    ap.add_argument("--n-trials", type=int, default=1,
                    help="baseline trials per cell (default 1, matches published methodology)")
    ap.add_argument("--config-ids", default=PUBLISHED_PANEL,
                    help="comma deployment config_ids (default: the published 6-model panel; "
                         "excludes post-publication fl-* leaderboard configs, many unrouted)")
    ap.add_argument("--ladder-order", default="starvation",
                    help="ROGUE_LADDER_ORDER for growth points (default 'starvation', the "
                         "published mode; deployed default 'contextual' breaks the cost curve). "
                         "The greedy arm always forces 'canonical'.")
    ap.add_argument("--confirm", action="store_true",
                    help="snapshot mode: acknowledge in-place mutation of the target DB")
    ap.add_argument("--restore-from-snapshot", action="store_true",
                    help="recovery: restore the candidate pool from _ks_snapshot and exit")
    args = ap.parse_args()

    if args.restore_from_snapshot:
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise SystemExit("DATABASE_URL not set")
        _restore(url)
        return 0

    ks = [int(x) for x in args.k_grid.split(",") if x.strip()]
    branch = dict(p.split("=", 1) for p in args.branch_urls.split(",") if "=" in p)
    if args.branch_urls_file:
        data = json.load(open(args.branch_urls_file))
        for tag, v in data.items():
            branch[tag] = v["url"] if isinstance(v, dict) else v

    # ---- FREE preview path ----
    if not args.execute:
        print(f"[{_now()}] PREVIEW (no spend). K grid: {ks}"
              f"{' + greedy arm' if args.greedy_arm else ''}")
        rec = _run_reproduce(cap=max(ks), quota=max(ks),
                             database_url=branch.get(str(max(ks))), dry_run=True,
                             primitive_limit=args.primitive_limit, n_trials=args.n_trials,
                             config_ids=args.config_ids, ladder_order=args.ladder_order)
        n = rec.get("candidates_selected")
        print(f"  pool depth at cap={max(ks)}: {n} candidates selected")
        if n is not None and n < max(ks):
            print(f"  ⚠ pool ({n}) < max K ({max(ks)}); top of grid is capped — "
                  "harvest more or trim the grid.")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({"preview": rec, "k_grid": ks}, indent=2))
        print(f"  frozen batch + preview → {OUT.relative_to(_ROOT)}")
        print("  to spend: re-run with --execute --db-mode {branch|snapshot} ...")
        return 0

    # ---- PAID path ----
    if not args.db_mode:
        raise SystemExit("--execute requires --db-mode {branch|snapshot}")
    runs = [(k, k) for k in ks]                       # (cap, quota) growth points
    if args.greedy_arm:
        runs.append((max(ks), 0))                     # greedy arm: cap=maxK, quota=0
    if args.db_mode == "branch":
        missing = [str(k) for k, q in runs
                   if (("greedy" if q == 0 else str(k)) not in branch)]
        if missing:
            raise SystemExit(f"branch mode: missing --branch-urls for: {missing}")
    if args.db_mode == "snapshot" and not args.confirm:
        raise SystemExit("snapshot mode mutates the target DB in place — pass --confirm "
                         "(prefer running it against a disposable branch)")

    _slack(f"START K-saturation: grid={ks} greedy={args.greedy_arm} "
           f"mode={args.db_mode} cap=${args.max_spend_per_k}/run")
    base_url = os.environ.get("DATABASE_URL")
    if args.db_mode == "snapshot":
        _snapshot(base_url)

    results = []
    try:
        for cap, quota in runs:
            tag = "greedy" if quota == 0 else str(cap)
            url = branch.get(tag) if args.db_mode == "branch" else base_url
            print(f"\n[{_now()}] RUN {tag}: cap={cap} quota={quota}")
            arm_order = "canonical" if quota == 0 else args.ladder_order
            try:
                if args.db_mode == "branch":          # fail-closed BEFORE any spend
                    host = _assert_isolation(url, cap, arm_order)
                    print(f"  isolation OK: child→{host}, NEON sync empty")
                rec = _run_reproduce(cap=cap, quota=quota,
                                     max_spend=args.max_spend_per_k,
                                     database_url=url, dry_run=False,
                                     primitive_limit=args.primitive_limit,
                                     n_trials=args.n_trials, config_ids=args.config_ids,
                                     ladder_order=arm_order)
            except Exception as exc:  # noqa: BLE001
                rec = {"cap": cap, "quota": quota, "error": str(exc), "ts": _now()}
            rec["tag"] = tag
            results.append(rec)
            ok = rec.get("returncode") == 0 and "run_id" in rec
            _slack(f"{tag}: {'ok' if ok else 'ERROR'} run_id={rec.get('run_id','?')} "
                   f"spend=${rec.get('escalation_spend','?')} plans={rec.get('plans_generated','?')}")
            if args.db_mode == "snapshot" and quota != 0:
                _restore(base_url)                    # reset pool before next K
    finally:
        if args.db_mode == "snapshot":
            _restore(base_url)                        # belt-and-suspenders
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({"k_grid": ks, "greedy_arm": args.greedy_arm,
                                   "db_mode": args.db_mode, "runs": results}, indent=2))
        print(f"\n  results → {OUT.relative_to(_ROOT)}")

    n_ok = sum(1 for r in results if r.get("returncode") == 0 and "run_id" in r)
    if n_ok == 0:                                     # all-errored guard
        _slack("⚠ K-saturation: ALL runs errored — no run_id captured. Check logs.")
        print("  ⚠ all runs errored")
        return 1
    _slack(f"DONE K-saturation: {n_ok}/{len(results)} runs ok. "
           "Next: update scheduler_results.json by_K -> scripts/research/p1_cost_fig.py -> make_overleaf_zips.sh p1")
    print(f"  {n_ok}/{len(results)} runs ok. Next: update data/research/scheduler_results.json "
          "cost_per_graduation_usd.by_K, then scripts/research/p1_cost_fig.py -> make_overleaf_zips.sh p1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
