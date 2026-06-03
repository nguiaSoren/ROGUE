#!/usr/bin/env bash
# Publish the analytics snapshot to the LIVE site — git-free (Vercel CLI, no push).
#
# Pipeline: regenerate data/analytics.json (live Neon, $0) -> copy into the frontend's
# public/ so it ships static -> `vercel --prod` (uploads + builds remotely; no local
# dev server, no git commit, repo untouched). The /analytics page fetches the bundled
# /analytics.json. One-time setup: `vercel login` && `vercel link` inside frontend/.
#
#   scripts/publish_analytics.sh            # regenerate + copy + deploy to prod
#   scripts/publish_analytics.sh --preview  # deploy to a PREVIEW url (verify first)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "[1/3] regenerate analytics.json (live Neon, read-only)…"
uv run python scripts/build_analytics.py >/dev/null
cp data/analytics.json frontend/public/analytics.json
echo "      data/analytics.json -> frontend/public/analytics.json"

if [[ "${1:-}" == "--preview" ]]; then
  echo "[2/3] vercel deploy (PREVIEW)…"
  ( cd frontend && vercel --yes )
else
  echo "[2/3] vercel deploy (PRODUCTION)…"
  ( cd frontend && vercel --prod --yes )
fi
echo "[3/3] done — live site now serves the fresh /analytics snapshot (no git push)."
