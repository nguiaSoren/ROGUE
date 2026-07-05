#!/usr/bin/env bash
# Local demo helper — red-team a Featherless-hosted model and persist the results into the
# LOCAL dashboard DB so /matrix?config=acme-support-bot fills with a real, named deployment.
#
#   prereq:  SEED_DEMO=0 docker compose -f docker-compose.full.yml up -d   (or default for a demo board)
#   run:     bash run_featherless_demo.sh
#
# NOT for production, NOT committed. Writes ONLY to the local Docker Postgres (never Neon).
set -euo pipefail
cd "$(dirname "$0")"

# Pull ONLY the two API keys from .env (don't `source` it — that would also import the Neon
# DATABASE_URL and point the scan at prod). Strip surrounding quotes if present.
_key() { grep -E "^$1=" .env | head -1 | cut -d= -f2- | sed 's/^"//; s/"$//'; }
export FEATHERLESS_API_KEY="$(_key FEATHERLESS_API_KEY)"
export ANTHROPIC_API_KEY="$(_key ANTHROPIC_API_KEY)"   # judge = calibrated default (anthropic/claude-sonnet-4-6)

# CRITICAL: persist to the LOCAL Docker Postgres the dashboard reads — never the Neon prod URL in .env.
export DATABASE_URL="postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"

TARGET="https://api.featherless.ai/v1"
MODEL="mistralai/Mistral-7B-Instruct-v0.3"   # permissive open model → the breach matrix actually lights up
CONFIG="acme-support-bot"

echo "→ [1/2] validating $MODEL on Featherless (cheap, no scan)..."
uv run rogue validate --endpoint "$TARGET" --api-key "$FEATHERLESS_API_KEY" --model "$MODEL"

echo "→ [2/2] scanning + persisting to the local dashboard DB (config: $CONFIG, 30 tests)..."
uv run rogue scan --endpoint "$TARGET" \
  --model "$MODEL" \
  --api-key "$FEATHERLESS_API_KEY" \
  --system-prompt-file ./demo_support_prompt.txt \
  --persist --config-name "$CONFIG" \
  --max-tests 30

echo
echo "✓ done — screenshot: http://localhost:3000/matrix?config=$CONFIG"
