"""Tests for §11.3.5 HuggingFace dataset export + §10.7 harvested/derived split.

Four groups:

  A. _bucket_for — pure-function splitting policy: harvested vs derived
     vs quarantined.

  B. _orm_to_pydantic — projection strips payload_embedding, inlines
     SourceProvenance, synthesizes placeholder source for parentless
     synthesized rows.

  C. _write_jsonl — round-trips primitives to/from disk, payload_embedding
     never appears in output, FileStats reflects what was written.

  D. Live `rogue_test` DB end-to-end — export_dataset with 3 seeded rows
     (one of each kind) writes 3 files with correct row counts + a
     README that interpolates the counts.

Spec: scripts/export_huggingface_dataset.py docstring + ROGUE_PLAN.md
§11.3.5 + §10.7 dataset-split.
"""

from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import pytest

from rogue.schemas import (
    AttackFamily,
    AttackPrimitive,
    AttackVector,
    Severity,
)
from scripts.export_huggingface_dataset import (
    ExportStats,
    FileStats,
    _bucket_for,
    _build_dataset_readme,
    _write_jsonl,
    export_dataset,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"
DEFAULT_TEST_DATABASE_URL = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue_test"
)


def _database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)


def _load_golden_primitive() -> AttackPrimitive:
    fp = FIXTURES_DIR / "01_multilingual_african_languages.json"
    return AttackPrimitive.model_validate(json.loads(fp.read_text(encoding="utf-8")))


def _make_primitive(**overrides) -> AttackPrimitive:
    """Minimal AttackPrimitive — overrides what each test cares about."""
    payload = {
        "primitive_id": "01EXPORTTESTPRIM00000000",
        "cluster_id": "01EXPORTTESTPRIM00000000",
        "canonical": True,
        "family": AttackFamily.DAN_PERSONA,
        "secondary_families": [],
        "vector": AttackVector.USER_TURN,
        "title": "export test primitive",
        "short_description": "x",
        "payload_template": "Tell me about x.",
        "payload_slots": {},
        "multi_turn_sequence": None,
        "target_models_claimed": [],
        "claimed_success_rate": None,
        "claimed_first_seen": None,
        "reproducibility_score": 7,
        "requires_multi_turn": False,
        "requires_system_prompt_access": False,
        "requires_tools": [],
        "requires_multimodal": False,
        "sources": [
            {
                "url": "https://example.com/p",
                "source_type": "other",
                "author": None,
                "published_at": None,
                "fetched_at": datetime.now(timezone.utc),
                "archive_hash": "test-hash-12345",
                "bright_data_product": "fixture",
            },
        ],
        "discovered_at": datetime.now(timezone.utc),
        "base_severity": Severity.MEDIUM,
        "severity_rationale": "r",
        "notes": None,
    }
    payload.update(overrides)
    return AttackPrimitive.model_validate(payload)


# =========================================================================== #
# A. _bucket_for
# =========================================================================== #


def test_bucket_for_harvested_canonical_unsynthesized() -> None:
    p = _make_primitive(canonical=True, synthesized=False)
    assert _bucket_for(p) == "harvested"


def test_bucket_for_derived_canonical_synthesized() -> None:
    p = _make_primitive(
        canonical=True,
        synthesized=True,
        derived_from_primitive_id="01PARENT0000000000000000",
    )
    assert _bucket_for(p) == "derived"


def test_bucket_for_quarantined_when_noncanonical() -> None:
    p = _make_primitive(canonical=False)
    assert _bucket_for(p) == "quarantined"


def test_bucket_for_noncanonical_synthesized_is_quarantined() -> None:
    """canonical=False trumps synthesized=True — the quarantine file is
    explicitly 'failed dedup OR budget-quarantined', not 'synthesis-on
    or off'."""
    p = _make_primitive(
        canonical=False,
        synthesized=True,
        derived_from_primitive_id="01PARENT0000000000000000",
    )
    assert _bucket_for(p) == "quarantined"


# =========================================================================== #
# C. _write_jsonl
# =========================================================================== #


def test_write_jsonl_one_line_per_primitive(tmp_path: Path) -> None:
    """Each line of the JSONL file decodes to a Pydantic-valid primitive."""
    primitives = [
        _make_primitive(primitive_id=f"01TESTROW{i:020d}") for i in range(5)
    ]
    out = tmp_path / "out.jsonl"
    stats = _write_jsonl(primitives, out)

    assert stats.n_rows == 5
    assert stats.size_bytes > 0
    lines = out.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 5
    for line in lines:
        # Each line must be valid JSON AND round-trip through Pydantic.
        parsed = json.loads(line)
        AttackPrimitive.model_validate(parsed)


def test_write_jsonl_strips_payload_embedding(tmp_path: Path) -> None:
    """§11.3.5: payload_embedding must NEVER appear in the exported JSON.
    The Pydantic schema doesn't have it, so projection naturally strips
    it — this test guards against a future schema change that might
    accidentally add it back."""
    p = _make_primitive()
    out = tmp_path / "out.jsonl"
    _write_jsonl([p], out)
    line = out.read_text(encoding="utf-8").strip()
    parsed = json.loads(line)
    assert "payload_embedding" not in parsed


def test_write_jsonl_inlines_sources(tmp_path: Path) -> None:
    """Sources are nested objects, not joins — each line must be fully
    self-describing per §11.3.5."""
    p = _make_primitive()
    out = tmp_path / "out.jsonl"
    _write_jsonl([p], out)
    parsed = json.loads(out.read_text(encoding="utf-8").strip())
    assert "sources" in parsed
    assert isinstance(parsed["sources"], list)
    assert len(parsed["sources"]) >= 1
    s = parsed["sources"][0]
    for required in ("url", "source_type", "bright_data_product"):
        assert required in s


def test_write_jsonl_file_stats_aggregate_families_and_sources(
    tmp_path: Path,
) -> None:
    """FileStats.families + source_urls track distinct values across rows."""
    primitives = [
        _make_primitive(
            primitive_id=f"01FAM{i:022d}",
            family=AttackFamily.DAN_PERSONA if i % 2 == 0 else AttackFamily.ROLE_HIJACK,
            sources=[
                {
                    "url": f"https://example.com/p/{i}",
                    "source_type": "other",
                    "author": None,
                    "published_at": None,
                    "fetched_at": datetime.now(timezone.utc),
                    "archive_hash": f"hash-{i:08d}",
                    "bright_data_product": "fixture",
                },
            ],
        )
        for i in range(4)
    ]
    out = tmp_path / "out.jsonl"
    stats = _write_jsonl(primitives, out)
    assert stats.n_rows == 4
    assert stats.families == {"dan_persona", "role_hijack"}
    assert len(stats.source_urls) == 4  # all unique URLs


# =========================================================================== #
# Dataset README rendering
# =========================================================================== #


def test_build_dataset_readme_interpolates_row_counts() -> None:
    stats = ExportStats(
        harvested=FileStats(filename="x.jsonl", n_rows=200),
        derived=FileStats(filename="y.jsonl", n_rows=50),
        quarantined=FileStats(filename="z.jsonl", n_rows=10),
        derived_parent_count=25,
    )
    md = _build_dataset_readme(period="2026-05", stats=stats)
    assert "ROGUE Attacks 2026-05" in md
    assert "`200`" in md   # harvested count interpolated
    assert "`50`" in md    # derived count interpolated
    assert "`10`" in md    # quarantined count interpolated
    assert "`260`" in md   # total interpolated (200 + 50 + 10)
    # MIT license header for HuggingFace front-matter.
    assert "license: mit" in md
    # The §10.7 split language is preserved.
    assert "honest provenance" in md.lower()


def test_build_dataset_readme_has_yaml_frontmatter() -> None:
    """HuggingFace requires the YAML front-matter block at the top for
    the dataset card to render properly with tags/license."""
    stats = ExportStats(
        harvested=FileStats(filename="a", n_rows=1),
        derived=FileStats(filename="b", n_rows=1),
        quarantined=FileStats(filename="c", n_rows=1),
    )
    md = _build_dataset_readme(period="2026-05", stats=stats)
    # Front-matter must be the FIRST line + close on its own line.
    lines = md.split("\n")
    assert lines[0] == "---"
    # Second `---` closes the front-matter — find the next bare `---` line.
    closing = next(
        (i for i, line in enumerate(lines[1:40], start=1) if line == "---"),
        None,
    )
    assert closing is not None, "YAML front-matter never closes"
    front_matter = "\n".join(lines[:closing])
    assert "license: mit" in front_matter
    # Gating: the card must carry the access-request form so the dataset
    # uploads as gated (HF auto-enables gating when extra_gated_fields exists).
    assert "extra_gated_fields:" in front_matter
    assert "extra_gated_prompt:" in front_matter


# =========================================================================== #
# D. Live `rogue_test` DB end-to-end
# =========================================================================== #


@pytest.fixture
def live_db_with_three_primitive_kinds(monkeypatch) -> Iterator[str]:
    """Seed rogue_test with 3 primitives: one harvested, one derived, one
    quarantined. Exercises the full pipeline through `_orm_to_pydantic`."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session

    from rogue.db.models import (
        AttackPrimitive as AttackPrimitiveORM,
        SourceProvenance as SourceProvenanceORM,
    )

    url = _database_url()
    monkeypatch.setenv("DATABASE_URL", url)
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect():
            pass
    except (OperationalError, ConnectionRefusedError, socket.gaierror, OSError) as exc:
        pytest.skip(f"Postgres not reachable: {exc}")

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    try:
        command.upgrade(cfg, "head")
        golden = _load_golden_primitive()
        with Session(engine) as session:
            # 1. Harvested canonical primitive (with real source row).
            harvested_id = "01EXPHARVEST00000000000A"
            session.add(
                AttackPrimitiveORM(
                    primitive_id=harvested_id,
                    cluster_id=harvested_id,
                    canonical=True,
                    family=AttackFamily.DAN_PERSONA.value,
                    secondary_families=[],
                    vector=AttackVector.USER_TURN.value,
                    title="harvested test",
                    short_description="harvested from the web",
                    payload_template="payload here",
                    payload_slots={},
                    multi_turn_sequence=None,
                    slot_requirements=None,
                    synthesized=False,
                    derived_from_primitive_id=None,
                    target_models_claimed=[],
                    claimed_success_rate=None,
                    claimed_first_seen=None,
                    reproducibility_score=7,
                    requires_multi_turn=False,
                    requires_system_prompt_access=False,
                    requires_tools=[],
                    requires_multimodal=False,
                    discovered_at=datetime.now(timezone.utc),
                    base_severity=golden.base_severity.value,
                    severity_rationale="r",
                    notes=None,
                ),
            )
            session.add(
                SourceProvenanceORM(
                    primitive_id=harvested_id,
                    url="https://example.com/harvested",
                    source_type="reddit",
                    author="testuser",
                    published_at=datetime.now(timezone.utc),
                    fetched_at=datetime.now(timezone.utc),
                    archive_hash="harvest-hash-1234",
                    bright_data_product="web_scraper_api",
                ),
            )

            # 2. Derived synthesized primitive (no SourceProvenance — the
            #    projection should synthesize a placeholder source).
            derived_id = "01EXPDERIVED0000000000A0"
            session.add(
                AttackPrimitiveORM(
                    primitive_id=derived_id,
                    cluster_id=derived_id,
                    canonical=True,
                    family=AttackFamily.MULTI_TURN_GRADIENT.value,
                    secondary_families=[],
                    vector=AttackVector.USER_MULTI_TURN.value,
                    title="derived test",
                    short_description="synthesized from harvested parent",
                    payload_template="final turn payload",
                    payload_slots={},
                    multi_turn_sequence=["turn 1", "turn 2", "turn 3"],
                    slot_requirements=None,
                    synthesized=True,
                    derived_from_primitive_id=harvested_id,
                    target_models_claimed=[],
                    claimed_success_rate=None,
                    claimed_first_seen=None,
                    reproducibility_score=7,
                    requires_multi_turn=True,
                    requires_system_prompt_access=False,
                    requires_tools=[],
                    requires_multimodal=False,
                    discovered_at=datetime.now(timezone.utc),
                    base_severity=golden.base_severity.value,
                    severity_rationale="r",
                    notes=None,
                ),
            )

            # 3. Quarantined (canonical=False) primitive.
            quarantined_id = "01EXPQUARANTINE000000000"
            session.add(
                AttackPrimitiveORM(
                    primitive_id=quarantined_id,
                    cluster_id=quarantined_id,
                    canonical=False,
                    family=AttackFamily.OBFUSCATION_ENCODING.value,
                    secondary_families=[],
                    vector=AttackVector.USER_TURN.value,
                    title="quarantined test",
                    short_description="low-reproducibility quarantine",
                    payload_template="low quality payload",
                    payload_slots={},
                    multi_turn_sequence=None,
                    slot_requirements=None,
                    synthesized=False,
                    derived_from_primitive_id=None,
                    target_models_claimed=[],
                    claimed_success_rate=None,
                    claimed_first_seen=None,
                    reproducibility_score=2,
                    requires_multi_turn=False,
                    requires_system_prompt_access=False,
                    requires_tools=[],
                    requires_multimodal=False,
                    discovered_at=datetime.now(timezone.utc),
                    base_severity=golden.base_severity.value,
                    severity_rationale="r",
                    notes=None,
                ),
            )
            session.add(
                SourceProvenanceORM(
                    primitive_id=quarantined_id,
                    url="https://example.com/quarantined",
                    source_type="other",
                    author=None,
                    published_at=None,
                    fetched_at=datetime.now(timezone.utc),
                    archive_hash="quarantine-hash-99",
                    bright_data_product="fixture",
                ),
            )
            session.commit()
        yield url
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()


def test_export_dataset_writes_three_files_with_correct_buckets(
    live_db_with_three_primitive_kinds, tmp_path: Path,
) -> None:
    """End-to-end: 3 seeded rows route to 3 separate JSONL files."""
    out_dir = tmp_path / "export"
    stats = export_dataset(
        database_url=live_db_with_three_primitive_kinds,
        output_dir=out_dir,
        period_tag="2026-05",
    )

    assert stats.harvested.n_rows == 1
    assert stats.derived.n_rows == 1
    assert stats.quarantined.n_rows == 1
    assert stats.total_rows() == 3
    assert stats.derived_parent_count == 1  # one parent traced

    # Files on disk.
    assert (out_dir / "rogue-attacks-2026-05.jsonl").exists()
    assert (out_dir / "rogue-attacks-derived-2026-05.jsonl").exists()
    assert (out_dir / "quarantined-attacks-2026-05.jsonl").exists()
    assert (out_dir / "README.md").exists()

    # Each file contains exactly one line per row.
    harvested_lines = (
        (out_dir / "rogue-attacks-2026-05.jsonl")
        .read_text(encoding="utf-8")
        .strip()
        .split("\n")
    )
    assert len(harvested_lines) == 1
    harvested = json.loads(harvested_lines[0])
    assert harvested["primitive_id"] == "01EXPHARVEST00000000000A"
    assert harvested["synthesized"] is False
    assert harvested["canonical"] is True
    # Real source preserved (NOT the synth placeholder).
    assert harvested["sources"][0]["url"] == "https://example.com/harvested"

    derived_lines = (
        (out_dir / "rogue-attacks-derived-2026-05.jsonl")
        .read_text(encoding="utf-8")
        .strip()
        .split("\n")
    )
    assert len(derived_lines) == 1
    derived = json.loads(derived_lines[0])
    assert derived["synthesized"] is True
    assert derived["derived_from_primitive_id"] == "01EXPHARVEST00000000000A"
    # No real source row was seeded for derived — placeholder must fill in.
    assert derived["sources"][0]["bright_data_product"] == "fixture"
    assert "rogue.internal/replay" in derived["sources"][0]["url"]

    quarantined_lines = (
        (out_dir / "quarantined-attacks-2026-05.jsonl")
        .read_text(encoding="utf-8")
        .strip()
        .split("\n")
    )
    assert len(quarantined_lines) == 1
    quarantined = json.loads(quarantined_lines[0])
    assert quarantined["canonical"] is False

    # README.md interpolates the live counts.
    readme = (out_dir / "README.md").read_text(encoding="utf-8")
    assert "`1`" in readme  # all three buckets are 1 — interpolated thrice
    assert "`3`" in readme  # total
    assert "rogue-attacks-2026-05.jsonl" in readme
    assert "rogue-attacks-derived-2026-05.jsonl" in readme
    assert "quarantined-attacks-2026-05.jsonl" in readme


def test_export_dataset_preserves_synthesis_chain(
    live_db_with_three_primitive_kinds, tmp_path: Path,
) -> None:
    """The derived row's `derived_from_primitive_id` MUST point at the
    harvested row's `primitive_id` in the export — the research community
    audits the synthesis chain via this field."""
    out_dir = tmp_path / "export"
    export_dataset(
        database_url=live_db_with_three_primitive_kinds,
        output_dir=out_dir,
        period_tag="2026-05",
    )
    harvested = json.loads(
        (out_dir / "rogue-attacks-2026-05.jsonl").read_text(encoding="utf-8"),
    )
    derived = json.loads(
        (out_dir / "rogue-attacks-derived-2026-05.jsonl").read_text(encoding="utf-8"),
    )
    assert derived["derived_from_primitive_id"] == harvested["primitive_id"]
