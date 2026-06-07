#!/usr/bin/env bash
# Publish the analytics snapshot to the LIVE site — git-free (Vercel CLI, no push).
#
# Pipeline: regenerate data/analytics.json (live Neon, $0) -> copy into the frontend's
# public/ so it ships static -> `vercel --prod` (uploads + builds remotely; no local
# dev server, no git commit, repo untouched). The /analytics page fetches the bundled
# /analytics.json.
#
# AUTH — use an explicit Vercel access token (deterministic, non-interactive, and
# unaffected by session/plugin/OIDC mess). One-time:
#   1. create a token: https://vercel.com/account/settings/tokens
#   2. add it to .env (gitignored), UNQUOTED:   ROGUE_VERCEL_TOKEN=xxxxxxxx
#   3. link the project once:  cd frontend && vercel link --token "$ROGUE_VERCEL_TOKEN"
# Then this script just works (and so does the auto-publish-on-harvest hook).
#
#   scripts/ops/publish_analytics.sh            # regenerate + copy + deploy to prod
#   scripts/ops/publish_analytics.sh --preview  # deploy to a PREVIEW url (verify first)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Resolve the access token: env var first, else read it from .env (unquoted value).
TOKEN="${ROGUE_VERCEL_TOKEN:-}"
if [ -z "$TOKEN" ] && [ -f .env ]; then
  # value must be UNQUOTED in .env:  ROGUE_VERCEL_TOKEN=xxxx
  TOKEN="$(grep -E '^ROGUE_VERCEL_TOKEN=' .env | head -1 | cut -d= -f2-)"
fi
# Clear any stale/short-lived tokens that would otherwise be "specified" and rejected.
unset VERCEL_TOKEN VERCEL_OIDC_TOKEN || true
if [ -f frontend/.env.local ] && grep -q '^VERCEL_OIDC_TOKEN=' frontend/.env.local; then
  sed -i.bak '/^VERCEL_OIDC_TOKEN=/d' frontend/.env.local
fi

echo "[1/3] regenerate analytics.json (live Neon, read-only)…"
uv run python scripts/ops/build_analytics.py >/dev/null
cp data/analytics.json frontend/public/analytics.json
echo "      data/analytics.json -> frontend/public/analytics.json"

# Build the vercel flag list. --token (when present) takes precedence over everything.
VFLAGS=()
[ -n "$TOKEN" ] && VFLAGS+=(--token "$TOKEN") || echo "      (no ROGUE_VERCEL_TOKEN — falling back to the vercel login session)"
if [[ "${1:-}" == "--preview" ]]; then
  echo "[2/3] vercel deploy (PREVIEW)…"
  ( cd frontend && vercel "${VFLAGS[@]}" --yes )
else
  echo "[2/3] vercel deploy (PRODUCTION)…"
  ( cd frontend && vercel "${VFLAGS[@]}" --prod --yes )
fi
echo "[3/3] done — live site now serves the fresh /analytics snapshot (no git push)."
