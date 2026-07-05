#!/usr/bin/env python
"""Emit CREATE TABLE DDL for a named subset of tables — a focused, anonymous
schema artifact for the TMLR supplements. Per-paper subsets only (NOT the whole
models.py, which would reveal the full product scope and cross-link papers).

    uv run python scripts/dump_schema.py breach_results ladder_attempts ...
"""
from __future__ import annotations

import sys

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from rogue.db import models  # noqa: F401  (populates Base.metadata)
from rogue.db.models import Base

md = Base.metadata
dialect = postgresql.dialect()
tables = sys.argv[1:]

print("-- Schema (CREATE TABLE DDL) for the append-only telemetry and results")
print("-- tables this paper's released slices are drawn from. Structure only —")
print("-- no rows. Generated from the system's SQLAlchemy models.\n")
for name in tables:
    if name not in md.tables:
        print(f"-- (table {name!r} not found in metadata)\n")
        continue
    tbl = md.tables[name]
    try:
        print(str(CreateTable(tbl).compile(dialect=dialect)).strip() + ";")
        for idx in tbl.indexes:
            print(str(CreateIndex(idx).compile(dialect=dialect)).strip() + ";")
    except Exception as exc:  # noqa: BLE001
        print(f"-- (could not compile {name}: {exc})")
    print()
