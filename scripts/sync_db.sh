#!/usr/bin/env bash
# Sync the ROGUE database between local Docker Postgres and Neon (cloud).
# Both run Postgres 17, so this is a straight version-matched copy.
#
#   ./scripts/sync_db.sh pull   # Neon → local  : mirror the LIVE db into local (use after a harvest)
#   ./scripts/sync_db.sh push   # local → Neon  : publish local to the LIVE site (overwrites live — asks first)
#
# Connection strings come from .env (DATABASE_URL = Neon, LOCAL_DATABASE_URL = local Docker).
# Runs pg_dump/psql INSIDE the rogue-postgres container (pg17), so no local client install is needed.
set -euo pipefail
cd "$(dirname "$0")/.."

dir="${1:-}"

# pg_dump/psql want the plain postgresql:// scheme; the app uses +psycopg for SQLAlchemy.
neon=$(grep -E '^DATABASE_URL=' .env | head -1 | cut -d= -f2- | sed 's#^postgresql+psycopg://#postgresql://#')
flags="--clean --if-exists --no-owner --no-privileges"

case "$dir" in
  pull)
    echo "Mirroring Neon → local (REPLACES your local 'rogue' DB)…"
    docker compose exec -T postgres pg_dump $flags "$neon" \
      | docker compose exec -T postgres psql -q -U rogue -d rogue
    ;;
  push)
    echo "WARNING: this REPLACES the LIVE Neon database with your local data."
    read -r -p "Type 'yes' to push local → Neon: " ok
    [ "$ok" = "yes" ] || { echo "aborted."; exit 1; }
    docker compose exec -T postgres pg_dump $flags -U rogue -d rogue \
      | docker compose exec -T postgres psql -q "$neon"
    ;;
  *)
    echo "usage: $0 {pull|push}"; exit 2 ;;
esac

echo -n "done — local 'rogue' now has attack_primitives="
docker compose exec -T postgres psql -U rogue -d rogue -tAc "select count(*) from attack_primitives;" 2>/dev/null | tr -d '[:space:]'
echo
