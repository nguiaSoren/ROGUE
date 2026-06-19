"""attestation_entries — the per-org append-only hash-chained attestation record (v2 ADR-0012)

Revision ID: 0031
Revises: 0030
Create Date: 2026-06-08

NET-NEW additive table for the ROGUE v2 signed-attestation layer (build 03,
`docs/v2/build/03_attestation.md` §A). One tamper-evident hash chain per
`org_id`: `seq` is per-org monotonic (genesis is 0), `entry_hash = sha256(prev_hash
|| canonical_json(payload))`. Storage twin of `rogue.platform.models.AttestationEntry`.

Append-only is *enforced*: a Postgres BEFORE UPDATE OR DELETE trigger RAISEs so an
entry can never be mutated or removed (a correction is a new entry, never an edit).
The trigger is Postgres-only and dialect-guarded — SQLite test backends skip it,
matching how the DB-only migration bits elsewhere guard on the dialect.

The `entry_type` CHECK vocabulary is derived from the single source of truth in
`rogue.attestation.chain.ENTRY_TYPES` (no duplication, per the CLAUDE.md schema
convention).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from rogue.attestation.chain import ENTRY_TYPES

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


_ENTRY_TYPE_CHECK = "entry_type IN (" + ", ".join(f"'{t}'" for t in ENTRY_TYPES) + ")"

# Postgres function + trigger that makes the table append-only. Any UPDATE or
# DELETE raises, so the chain is tamper-evident at the storage layer, not just by
# convention. Created/dropped only on Postgres (dialect-guarded below).
_APPEND_ONLY_FN = """
CREATE OR REPLACE FUNCTION attestation_entries_append_only()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'attestation_entries is append-only: % is not permitted (a correction is a new entry)', TG_OP;
END;
$$ LANGUAGE plpgsql;
"""

_CREATE_TRIGGER = """
CREATE TRIGGER trg_attestation_entries_append_only
BEFORE UPDATE OR DELETE ON attestation_entries
FOR EACH ROW EXECUTE FUNCTION attestation_entries_append_only();
"""

_DROP_TRIGGER = "DROP TRIGGER IF EXISTS trg_attestation_entries_append_only ON attestation_entries;"
_DROP_FN = "DROP FUNCTION IF EXISTS attestation_entries_append_only();"


def upgrade() -> None:
    op.create_table(
        "attestation_entries",
        sa.Column("entry_id", sa.String(length=48), primary_key=True),
        sa.Column("org_id", sa.String(length=40), sa.ForeignKey("organizations.org_id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("entry_type", sa.String(length=20), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("entry_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("reproducibility_ref", sa.String(length=64), nullable=True),
        sa.Column("ground_truth_ref", sa.String(length=64), nullable=True),
        sa.Column("corpus_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("org_id", "seq", name="uq_attestation_org_seq"),
        sa.UniqueConstraint("org_id", "entry_hash", name="uq_attestation_org_entry_hash"),
        sa.CheckConstraint(_ENTRY_TYPE_CHECK, name="ck_attestation_entry_type"),
    )
    op.create_index("ix_attestation_entries_org_id", "attestation_entries", ["org_id"])
    op.create_index("ix_attestation_org_seq", "attestation_entries", ["org_id", "seq"])
    op.create_index("ix_attestation_org_entry_type", "attestation_entries", ["org_id", "entry_type"])
    op.create_index(
        "ix_attestation_org_reproducibility_ref",
        "attestation_entries",
        ["org_id", "reproducibility_ref"],
    )

    # Append-only enforcement: Postgres-only trigger (dialect-guarded — SQLite has
    # no trigger language we rely on here and skips it cleanly).
    if op.get_bind().dialect.name == "postgresql":
        op.execute(_APPEND_ONLY_FN)
        op.execute(_CREATE_TRIGGER)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(_DROP_TRIGGER)
        op.execute(_DROP_FN)

    op.drop_index("ix_attestation_org_reproducibility_ref", table_name="attestation_entries")
    op.drop_index("ix_attestation_org_entry_type", table_name="attestation_entries")
    op.drop_index("ix_attestation_org_seq", table_name="attestation_entries")
    op.drop_index("ix_attestation_entries_org_id", table_name="attestation_entries")
    op.drop_table("attestation_entries")
