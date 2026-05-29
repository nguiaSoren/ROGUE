#!/usr/bin/env bash
# One command: harvest new attacks + reproduce them against the deployment configs
# (both write to Neon = the LIVE db), then mirror Neon → local.
#
#   ./scripts/refresh.sh            # harvest --since 1d, FULL reproduce (~$35), then pull
#   ./scripts/refresh.sh 3d 20      # harvest --since 3d, reproduce top-20 primitives (~$10), then pull
#
# WARNING: this SPENDS money — harvest hits Bright Data, reproduce hits the LLM panel +
# judge. Run it deliberately, not on a tight timer. Both DBs end up in sync; the live
# site reflects the new data within ~5 min (ISR cache).
set -euo pipefail
cd "$(dirname "$0")/.."

since="${1:-1d}"
limit="${2:-}"   # optional: cap reproduce to the top-N primitives by reproducibility_score

echo "==> 1/3  harvest (--since $since) → Neon (live)"
uv run python scripts/harvest_once.py --since "$since"

echo "==> 2/3  reproduce → Neon (live)"
if [ -n "$limit" ]; then
  uv run python scripts/reproduce_once.py --primitive-limit "$limit"
else
  uv run python scripts/reproduce_once.py
fi

echo "==> 3/3  mirror Neon → local"
./scripts/sync_db.sh pull

echo "✅ done — Neon (live) + local both updated. Live site refreshes within ~5 min."
