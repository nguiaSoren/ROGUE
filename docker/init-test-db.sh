#!/usr/bin/env bash
# Postgres init script — runs ONCE on a fresh `postgres-data` volume.
#
# Creates the `rogue_test` database for pytest use, so the smoke test's
# `alembic upgrade head → downgrade base` round-trip never wipes the dev
# `rogue` DB. Wired via docker-entrypoint-initdb.d in docker-compose.yml.
#
# This script does NOT run if the volume already exists. For pre-existing
# volumes (anyone who ran `docker compose up` before this script landed),
# create the test DB manually one time:
#
#     docker compose exec -T postgres psql -U rogue -d rogue \
#       -c "CREATE DATABASE rogue_test;"
#
# Spec: tasks/LESSONS.md 2026-05-24 entry on test_alembic_upgrade_head_dry_run
# (resolved 2026-05-26).
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE rogue_test;
    GRANT ALL PRIVILEGES ON DATABASE rogue_test TO $POSTGRES_USER;
EOSQL
