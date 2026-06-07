"""Tests for rogue.grammar.labeler.

Pure unit tests (no DB required) are the bulk of this suite.  A single
DB-gated persist test runs only when Postgres is reachable and the
``primitive_grammar_labels`` table exists (built by Engineer 2 in the same
wave).  If the table doesn't exist yet, the test is skipped cleanly.
"""

from __future__ import annotations

import os
import socket
import datetime as _dt  # noqa: F401 — retained for DB fixture if needed

import pytest

from rogue.grammar.dataset import PrimitiveRecord
from rogue.grammar.labeler import (
    heuristic_labels,
    label_distribution,
    label_records,
)
from rogue.schemas import GrammarNode


# ---------------------------------------------------------------------------
# Helpers — build minimal PrimitiveRecords without hitting the DB
# ---------------------------------------------------------------------------

def _make_record(
    *,
    primitive_id: str = "TEST000001",
    family: str = "direct_instruction_override",
    secondary_families: list[str] | None = None,
    payload_slots: dict | None = None,
    requires_multi_turn: bool = False,
    vector: str = "user_turn",
) -> PrimitiveRecord:
    return PrimitiveRecord(
        primitive_id=primitive_id,
        family=family,
        secondary_families=secondary_families or [],
        payload_slots=payload_slots or {},
        requires_multi_turn=requires_multi_turn,
        vector=vector,
        breached=False,
        breach_rate=0.0,
        n_trials=0,
        has_breach_data=False,
        targets=[],
    )


# ---------------------------------------------------------------------------
# Pure unit tests — no DB
# ---------------------------------------------------------------------------


class TestFamilyMirroring:
    """Primary family -> node mapping."""

    def test_role_hijack_family(self):
        r = _make_record(family="role_hijack")
        nodes = heuristic_labels(r)
        assert GrammarNode.ROLE_HIJACK in nodes

    def test_dan_persona_family(self):
        r = _make_record(family="dan_persona")
        nodes = heuristic_labels(r)
        assert GrammarNode.DAN_PERSONA in nodes

    def test_direct_override_family(self):
        r = _make_record(family="direct_instruction_override")
        nodes = heuristic_labels(r)
        assert GrammarNode.DIRECT_OVERRIDE in nodes

    def test_system_prompt_leak_family(self):
        r = _make_record(family="system_prompt_leak")
        nodes = heuristic_labels(r)
        assert GrammarNode.SYSTEM_PROMPT_LEAK in nodes

    def test_training_data_extraction_family(self):
        r = _make_record(family="training_data_extraction")
        nodes = heuristic_labels(r)
        assert GrammarNode.TRAINING_DATA_EXTRACTION in nodes

    def test_indirect_prompt_injection_family(self):
        r = _make_record(family="indirect_prompt_injection")
        nodes = heuristic_labels(r)
        assert GrammarNode.INDIRECT_INJECTION in nodes

    def test_tool_use_hijack_family(self):
        r = _make_record(family="tool_use_hijack")
        nodes = heuristic_labels(r)
        assert GrammarNode.TOOL_INVOCATION in nodes

    def test_chain_of_thought_hijack_family(self):
        r = _make_record(family="chain_of_thought_hijack")
        nodes = heuristic_labels(r)
        assert GrammarNode.CHAIN_OF_THOUGHT_HIJACK in nodes

    def test_multimodal_injection_family(self):
        r = _make_record(family="multimodal_injection")
        nodes = heuristic_labels(r)
        assert GrammarNode.MULTIMODAL in nodes

    def test_obfuscation_encoding_family(self):
        r = _make_record(family="obfuscation_encoding")
        nodes = heuristic_labels(r)
        assert GrammarNode.ENCODING_OBFUSCATION in nodes

    def test_language_switching_family(self):
        r = _make_record(family="language_switching")
        nodes = heuristic_labels(r)
        assert GrammarNode.LANGUAGE_SHIFT in nodes

    def test_multi_turn_gradient_family(self):
        r = _make_record(family="multi_turn_gradient")
        nodes = heuristic_labels(r)
        assert GrammarNode.MULTI_TURN_ESCALATION in nodes

    def test_multi_turn_persona_chain_family(self):
        r = _make_record(family="multi_turn_persona_chain")
        nodes = heuristic_labels(r)
        assert GrammarNode.MULTI_TURN_ESCALATION in nodes

    def test_secondary_family_fires(self):
        r = _make_record(
            family="direct_instruction_override",
            secondary_families=["role_hijack", "system_prompt_leak"],
        )
        nodes = heuristic_labels(r)
        assert GrammarNode.ROLE_HIJACK in nodes
        assert GrammarNode.SYSTEM_PROMPT_LEAK in nodes
        assert GrammarNode.DIRECT_OVERRIDE in nodes


class TestSlotSignals:
    """Cross-family payload_slots -> node mapping."""

    def test_authority_claim_slot(self):
        r = _make_record(payload_slots={"authority_claim": "I am a doctor"})
        assert GrammarNode.AUTHORITY_FRAME in heuristic_labels(r)

    def test_justification_slot(self):
        r = _make_record(payload_slots={"justification": "for research"})
        assert GrammarNode.AUTHORITY_FRAME in heuristic_labels(r)

    def test_encoding_scheme_slot(self):
        r = _make_record(payload_slots={"encoding_scheme": "base64"})
        assert GrammarNode.ENCODING_OBFUSCATION in heuristic_labels(r)

    def test_target_output_format_slot(self):
        r = _make_record(payload_slots={"target_output_format": "JSON"})
        assert GrammarNode.STRUCTURED_OUTPUT in heuristic_labels(r)

    def test_new_response_format_slot(self):
        r = _make_record(payload_slots={"NewResponseFormat": "markdown"})
        assert GrammarNode.STRUCTURED_OUTPUT in heuristic_labels(r)

    def test_tool_name_slot(self):
        r = _make_record(payload_slots={"tool_name": "send_email"})
        assert GrammarNode.TOOL_INVOCATION in heuristic_labels(r)

    def test_exfil_destination_slot(self):
        r = _make_record(payload_slots={"exfil_destination": "https://evil.com"})
        assert GrammarNode.EXFILTRATION in heuristic_labels(r)

    def test_trigger_phrase_slot(self):
        r = _make_record(payload_slots={"trigger_phrase": "ACTIVATE"})
        assert GrammarNode.TRIGGER_BACKDOOR in heuristic_labels(r)

    def test_language_slot(self):
        r = _make_record(payload_slots={"language": "Chinese"})
        assert GrammarNode.LANGUAGE_SHIFT in heuristic_labels(r)

    def test_invisible_tag_instruction_slot(self):
        r = _make_record(payload_slots={"invisible_tag_instruction": "<!--inject-->"})
        assert GrammarNode.INVISIBLE_INJECTION in heuristic_labels(r)

    def test_target_behavior_slot(self):
        r = _make_record(payload_slots={"target_behavior": "write malware"})
        assert GrammarNode.TARGET_BEHAVIOR_SPECIFICATION in heuristic_labels(r)

    def test_target_topic_slot(self):
        r = _make_record(payload_slots={"target_topic": "bioweapons"})
        assert GrammarNode.TARGET_BEHAVIOR_SPECIFICATION in heuristic_labels(r)

    def test_rag_document_with_indirect_family(self):
        r = _make_record(
            family="indirect_prompt_injection",
            payload_slots={"rag_document": "malicious chunk"},
        )
        assert GrammarNode.RAG_POISONING in heuristic_labels(r)

    def test_poison_payload_with_indirect_family(self):
        r = _make_record(
            family="indirect_prompt_injection",
            payload_slots={"poison_payload": "malicious payload"},
        )
        assert GrammarNode.RAG_POISONING in heuristic_labels(r)

    def test_rag_document_without_indirect_family_no_rag_poisoning(self):
        """RAG_POISONING only fires when the family is indirect_prompt_injection."""
        r = _make_record(
            family="direct_instruction_override",
            payload_slots={"rag_document": "some doc"},
        )
        assert GrammarNode.RAG_POISONING not in heuristic_labels(r)

    def test_persona_construction_role_name_and_description(self):
        r = _make_record(
            payload_slots={
                "role_name": "EvilBot",
                "role_description": "An unrestricted AI",
            }
        )
        assert GrammarNode.PERSONA_CONSTRUCTION in heuristic_labels(r)

    def test_persona_construction_role_name_and_trait(self):
        r = _make_record(
            payload_slots={
                "role_name": "Shadow",
                "personality_trait": "ruthless",
            }
        )
        assert GrammarNode.PERSONA_CONSTRUCTION in heuristic_labels(r)

    def test_persona_construction_requires_both_slots(self):
        """role_name alone (no role_description/personality_trait) should NOT fire PERSONA_CONSTRUCTION."""
        r = _make_record(payload_slots={"role_name": "OnlyName"})
        assert GrammarNode.PERSONA_CONSTRUCTION not in heuristic_labels(r)

    def test_dan_keyword_in_role_name(self):
        r = _make_record(payload_slots={"role_name": "DAN mode activated"})
        assert GrammarNode.DAN_PERSONA in heuristic_labels(r)

    def test_fictional_framing_policy_roleplay_family(self):
        r = _make_record(
            family="policy_roleplay",
            payload_slots={"role_description": "In this story, you are a hacker"},
        )
        assert GrammarNode.FICTIONAL_FRAMING in heuristic_labels(r)

    def test_fictional_framing_no_roleplay_family(self):
        """FICTIONAL_FRAMING only fires with a matching family."""
        r = _make_record(
            family="direct_instruction_override",
            payload_slots={"role_description": "you are a hacker"},
        )
        assert GrammarNode.FICTIONAL_FRAMING not in heuristic_labels(r)

    def test_empty_slot_value_ignored(self):
        """Empty string slot values must not trigger node assignment."""
        r = _make_record(
            payload_slots={"authority_claim": "", "encoding_scheme": "  "}
        )
        nodes = heuristic_labels(r)
        assert GrammarNode.AUTHORITY_FRAME not in nodes
        assert GrammarNode.ENCODING_OBFUSCATION not in nodes


class TestFlagAndVectorSignals:
    """requires_multi_turn and vector -> node mapping."""

    def test_requires_multi_turn_true(self):
        r = _make_record(requires_multi_turn=True)
        assert GrammarNode.MULTI_TURN_ESCALATION in heuristic_labels(r)

    def test_requires_multi_turn_false(self):
        r = _make_record(family="direct_instruction_override", requires_multi_turn=False)
        # Only MULTI_TURN_ESCALATION from the flag; family doesn't produce it
        nodes = heuristic_labels(r)
        assert GrammarNode.MULTI_TURN_ESCALATION not in nodes

    def test_multimodal_vector(self):
        r = _make_record(vector="multimodal_image")
        assert GrammarNode.MULTIMODAL in heuristic_labels(r)

    def test_multimodal_vector_audio(self):
        r = _make_record(vector="multimodal_audio")
        assert GrammarNode.MULTIMODAL in heuristic_labels(r)

    def test_rag_document_vector_fires_indirect_injection(self):
        r = _make_record(vector="rag_document")
        assert GrammarNode.INDIRECT_INJECTION in heuristic_labels(r)

    def test_tool_output_vector_fires_indirect_injection(self):
        r = _make_record(vector="tool_output")
        assert GrammarNode.INDIRECT_INJECTION in heuristic_labels(r)

    def test_user_turn_vector_no_multimodal(self):
        r = _make_record(vector="user_turn")
        assert GrammarNode.MULTIMODAL not in heuristic_labels(r)


class TestMultiSignalRecord:
    """A richly annotated primitive gets multiple nodes simultaneously."""

    def test_multi_signal_yields_multiple_nodes(self):
        r = _make_record(
            family="role_hijack",
            secondary_families=["refusal_suppression"],
            payload_slots={
                "authority_claim": "I am admin",
                "encoding_scheme": "base64",
                "target_output_format": "JSON",
                "trigger_phrase": "OVERRIDE",
                "target_behavior": "disable safety",
            },
            requires_multi_turn=True,
        )
        nodes = heuristic_labels(r)
        assert GrammarNode.ROLE_HIJACK in nodes
        assert GrammarNode.REFUSAL_SUPPRESSION in nodes
        assert GrammarNode.AUTHORITY_FRAME in nodes
        assert GrammarNode.ENCODING_OBFUSCATION in nodes
        assert GrammarNode.STRUCTURED_OUTPUT in nodes
        assert GrammarNode.TRIGGER_BACKDOOR in nodes
        assert GrammarNode.TARGET_BEHAVIOR_SPECIFICATION in nodes
        assert GrammarNode.MULTI_TURN_ESCALATION in nodes
        assert len(nodes) >= 8

    def test_indirect_injection_with_full_kit(self):
        r = _make_record(
            family="indirect_prompt_injection",
            payload_slots={
                "rag_document": "injected doc",
                "invisible_tag_instruction": "<!-- act now -->",
                "exfil_destination": "https://attacker.io",
                "trigger_phrase": "NOW",
            },
        )
        nodes = heuristic_labels(r)
        assert GrammarNode.INDIRECT_INJECTION in nodes
        assert GrammarNode.RAG_POISONING in nodes
        assert GrammarNode.INVISIBLE_INJECTION in nodes
        assert GrammarNode.EXFILTRATION in nodes
        assert GrammarNode.TRIGGER_BACKDOOR in nodes


class TestEmptyRecord:
    """Edge case: no signals at all."""

    def test_empty_record_no_crash(self):
        r = _make_record(
            family="direct_instruction_override",
            secondary_families=[],
            payload_slots={},
            requires_multi_turn=False,
            vector="user_turn",
        )
        nodes = heuristic_labels(r)
        # DIRECT_OVERRIDE fires from the family.
        assert isinstance(nodes, set)
        # No cross-family nodes without signals.
        assert GrammarNode.AUTHORITY_FRAME not in nodes
        assert GrammarNode.ENCODING_OBFUSCATION not in nodes
        assert GrammarNode.MULTI_TURN_ESCALATION not in nodes

    def test_unknown_family_no_crash(self):
        """An unrecognised family string must not crash — just produces no family node."""
        r = _make_record(family="future_unknown_family_xyz")
        nodes = heuristic_labels(r)
        assert isinstance(nodes, set)


class TestLabelRecords:
    """label_records — batch dispatch."""

    def test_returns_dict_keyed_by_id(self):
        records = [
            _make_record(primitive_id="A1", family="dan_persona"),
            _make_record(primitive_id="A2", family="system_prompt_leak"),
        ]
        result = label_records(records)
        assert set(result.keys()) == {"A1", "A2"}
        assert GrammarNode.DAN_PERSONA in result["A1"]
        assert GrammarNode.SYSTEM_PROMPT_LEAK in result["A2"]

    def test_empty_list(self):
        assert label_records([]) == {}


class TestLabelDistribution:
    """label_distribution — counting and completeness."""

    def test_all_nodes_present_in_output(self):
        """Output must include ALL GrammarNode members (even with 0 count)."""
        labels: dict = {}  # empty -> all zeros
        dist = label_distribution(labels)
        assert set(dist.keys()) == set(GrammarNode)

    def test_zero_counts_for_empty(self):
        dist = label_distribution({})
        assert all(v == 0 for v in dist.values())

    def test_counts_correctly(self):
        # Two records: A has AUTHORITY_FRAME+ENCODING_OBFUSCATION, B has AUTHORITY_FRAME.
        labels = {
            "A": {GrammarNode.AUTHORITY_FRAME, GrammarNode.ENCODING_OBFUSCATION},
            "B": {GrammarNode.AUTHORITY_FRAME},
        }
        dist = label_distribution(labels)
        assert dist[GrammarNode.AUTHORITY_FRAME] == 2
        assert dist[GrammarNode.ENCODING_OBFUSCATION] == 1
        assert dist[GrammarNode.EXFILTRATION] == 0  # not assigned

    def test_distribution_from_records(self):
        """Round-trip: label_records then label_distribution."""
        records = [
            _make_record(
                primitive_id="R1",
                family="indirect_prompt_injection",
                payload_slots={"authority_claim": "admin"},
            ),
            _make_record(
                primitive_id="R2",
                family="system_prompt_leak",
                payload_slots={"authority_claim": "boss"},
            ),
        ]
        labels = label_records(records)
        dist = label_distribution(labels)
        # Both should have AUTHORITY_FRAME; SYSTEM_PROMPT_LEAK only in R2.
        assert dist[GrammarNode.AUTHORITY_FRAME] == 2
        assert dist[GrammarNode.SYSTEM_PROMPT_LEAK] == 1


# ---------------------------------------------------------------------------
# DB-gated persist test (state-neutral)
# ---------------------------------------------------------------------------

_DEFAULT_DB_URL = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"
)


def _db_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", _DEFAULT_DB_URL)


def _db_reachable() -> bool:
    import urllib.parse

    url = _db_url()
    # Parse host/port from the URL
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        sock = socket.create_connection((host, port), timeout=2)
        sock.close()
        return True
    except (OSError, socket.error):
        return False


@pytest.fixture
def db_session_for_labeler():
    """Yield a live SQLAlchemy Session if Postgres is reachable and the
    primitive_grammar_labels table exists.  Skip otherwise."""
    if not _db_reachable():
        pytest.skip("Postgres not reachable — skipping DB persist test")

    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session

    engine = create_engine(_db_url(), connect_args={"connect_timeout": 2})

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"DB connection failed: {exc}")

    # `primitive_grammar_labels` is created by migration 0027. If the table is
    # absent the DB simply isn't migrated to head — `uv run alembic upgrade head`.
    insp = inspect(engine)
    if "primitive_grammar_labels" not in insp.get_table_names():
        pytest.skip(
            "primitive_grammar_labels table absent — DB not migrated to head "
            "(run `uv run alembic upgrade head`)"
        )

    with Session(engine) as session:
        yield session

    engine.dispose()


def test_persist_labels_writes_rows(db_session_for_labeler):
    """Upsert heuristic labels for a seeded primitive and verify rows land + are idempotent.

    Migration 0027 added a FK from ``primitive_grammar_labels.primitive_id`` to
    ``attack_primitives``, so the label's parent primitive must exist first — we
    seed a minimal one, then clean both up.
    """
    from datetime import datetime, timezone

    from sqlalchemy import text

    from rogue.db.models import AttackPrimitive as AttackPrimitiveORM
    from rogue.grammar.labeler import persist_labels

    fake_id = "TESTLABELROW0000001"
    labels = {
        fake_id: {GrammarNode.AUTHORITY_FRAME, GrammarNode.ENCODING_OBFUSCATION},
    }

    # Parent primitive (FK target). Minimal valid row.
    db_session_for_labeler.add(
        AttackPrimitiveORM(
            primitive_id=fake_id,
            cluster_id=fake_id,
            canonical=True,
            family="direct_instruction_override",
            secondary_families=[],
            vector="user_turn",
            title="grammar-labeler FK parent",
            short_description="seeded so the label FK resolves",
            payload_template="ignore previous instructions",
            payload_slots={},
            target_models_claimed=[],
            reproducibility_score=5,
            requires_multi_turn=False,
            requires_system_prompt_access=False,
            requires_tools=[],
            requires_multimodal=False,
            discovered_at=datetime.now(timezone.utc),
            base_severity="medium",
            severity_rationale="r",
        )
    )
    db_session_for_labeler.commit()

    try:
        # First upsert
        rows_written = persist_labels(db_session_for_labeler, labels, source="heuristic")
        db_session_for_labeler.commit()
        assert rows_written == 2

        # Second upsert must be idempotent (ON CONFLICT DO UPDATE)
        rows_written_2 = persist_labels(db_session_for_labeler, labels, source="heuristic")
        db_session_for_labeler.commit()
        assert rows_written_2 == 2
    finally:
        # Cleanup — only rows we inserted (labels first: FK child).
        db_session_for_labeler.execute(
            text(
                "DELETE FROM primitive_grammar_labels "
                "WHERE primitive_id = :pid AND source = 'heuristic'"
            ),
            {"pid": fake_id},
        )
        db_session_for_labeler.execute(
            text("DELETE FROM attack_primitives WHERE primitive_id = :pid"),
            {"pid": fake_id},
        )
        db_session_for_labeler.commit()
