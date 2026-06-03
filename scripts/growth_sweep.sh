#!/usr/bin/env bash
# §10.10 GROWTH MODE — a dedicated repertoire-growth escalation sweep.
#
# Two operating modes were discovered empirically (2026-06-03):
#
#   Canonical mode (the default reproduce_once behaviour) — goal: find breaches
#   cheaply. K=3, quota=0, order=canonical. ~$0.35/escalation-breach, median winner
#   rank 0. This stays the default for routine reproduction; do NOT change it.
#
#   Growth mode (THIS script) — goal: grow the repertoire. K=quota, order=starvation.
#   Suppresses early-stop so harvested candidates are actually evaluated; ~$7/graduation.
#   Run deliberately, not on every reproduce.
#
# Evidence for the growth-mode defaults: two growth sweeps graduated 7 of 8 evaluated
# candidates (87.5%), and cost-per-graduation IMPROVED as K rose ($8.37 at K=3 →
# $7.02 at K=5) — because the candidates ride along inside ladders that run the full
# rotation anyway, so extra slots are nearly free. Hence K is promoted 3 → 5.
#
# This wrapper encodes the load-bearing invariant the hard way so it can't drift:
# **quota is ALWAYS set equal to K**. (A K>quota run silently evaluates only `quota`
# of the K selected candidates — the mis-config that nearly wasted a paid run.)
#
# Usage:
#   scripts/growth_sweep.sh [K] [primitive_limit] [max_spend_usd]
#   K=8 scripts/growth_sweep.sh                       # raise K to probe the bend
#   RUN_ID=my_run DEADLINE=18000 scripts/growth_sweep.sh 5 40 28
#
# Stopping rule (the next-K decision): after each growth sweep, read cost-per-
# graduation (analyze_sweep.py / the done: line). While it stays flat or improves,
# raise K next time; when it rises sharply, you've found the saturation point — stop.
# Current evidence justifies K=5, NOT "max everything" (only 8 candidates evaluated).
set -euo pipefail
cd "$(dirname "$0")/.."

K="${K:-${1:-5}}"
LIMIT="${LIMIT:-${2:-40}}"
SPEND="${SPEND:-${3:-28}}"
DEADLINE="${DEADLINE:-14400}"          # 4h wall-clock safety net
RUN_ID="${RUN_ID:-growth_K${K}_$(date +%s)}"

echo ">>> GROWTH MODE sweep"
echo "    K=$K  quota=$K (locked equal)  order=starvation  n_trials=1"
echo "    primitive_limit=$LIMIT  escalate_max_spend=\$$SPEND  wall_clock=${DEADLINE}s"
echo "    run_id=$RUN_ID"
echo "    (background + watch it yourself; analyze with: analyze_sweep.py --run-id $RUN_ID)"

CAND_LADDER_CAP="$K" ROGUE_LADDER_ORDER=starvation PYTHONPATH=. \
  uv run python scripts/run_with_deadline.py "$DEADLINE" \
  uv run python scripts/reproduce_once.py \
    --escalate --primitive-limit "$LIMIT" --n-trials 1 \
    --candidate-quota "$K" --escalate-max-spend "$SPEND" --escalate-n-trials 1 \
    --run-id "$RUN_ID"
