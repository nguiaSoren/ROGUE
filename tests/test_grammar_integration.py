"""Integration tests for the grammar study pipeline (Engineer 8).

Two layers:

SYNTHETIC end-to-end (NO DB):
  Hand-builds a small list[PrimitiveRecord] with .targets, then runs the full
  label_records -> node_lift_table -> pairwise_interactions -> controlled_analysis
  chain, asserting the whole pipeline composes and controlled_analysis returns a
  dict with a VERDICT field.

  Sibling modules (combinations, validation) are imported lazily — if they have
  not yet landed this test SKIPs with a clear message rather than erroring, so the
  orchestrator can run the suite incrementally as modules land.

DB-gated (skip-when-DB-down, STATE-NEUTRAL, read-only):
  Builds the real dataset from the live DB, labels it, runs node_lift_table
  (per_target) and asserts it returns NodeLift objects with sane fields.
  Never writes anything.
"""

from __future__ import annotations

import os
import socket

import pytest

# ---------------------------------------------------------------------------
# Test data factories
# ---------------------------------------------------------------------------


def _make_target(dc_id: str, any_rate: float, n: int = 10) -> object:
    """Return a TargetOutcome (imported lazily to skip if dataset not available)."""
    from rogue.grammar.dataset import TargetOutcome

    return TargetOutcome(
        deployment_config_id=dc_id,
        vendor="test_vendor",
        model_family="test_family",
        any_breach_rate=any_rate,
        full_breach_rate=any_rate * 0.5,
        n_trials=n,
        breached=any_rate > 0.0,
    )


def _make_record(
    pid: str,
    family: str,
    slots: dict,
    requires_multi_turn: bool = False,
    targets: list | None = None,
) -> object:
    """Return a PrimitiveRecord with the given targets."""
    from rogue.grammar.dataset import PrimitiveRecord

    tgts = targets or []
    breached = any(t.breached for t in tgts)
    breach_rate = max((t.any_breach_rate for t in tgts), default=0.0)
    n_trials = sum(t.n_trials for t in tgts)
    return PrimitiveRecord(
        primitive_id=pid,
        family=family,
        secondary_families=[],
        payload_slots=slots,
        requires_multi_turn=requires_multi_turn,
        vector="direct_chat",
        breached=breached,
        breach_rate=breach_rate,
        n_trials=n_trials,
        has_breach_data=bool(tgts),
        targets=tgts,
    )


def _small_corpus() -> list:
    """Build a 6-primitive synthetic corpus with varied node coverage."""
    return [
        # p1: authority_frame + target_behavior → 2 targets, both breach
        _make_record(
            "p1",
            "role_hijack",
            {"authority_claim": "I am a researcher", "target_behavior": "synthesise X"},
            targets=[
                _make_target("dc-a", 0.8),
                _make_target("dc-b", 0.6),
            ],
        ),
        # p2: encoding_obfuscation, no breach
        _make_record(
            "p2",
            "obfuscation_encoding",
            {"encoding_scheme": "base64"},
            targets=[
                _make_target("dc-a", 0.0),
                _make_target("dc-b", 0.0),
            ],
        ),
        # p3: multi-turn escalation, 1 breach
        _make_record(
            "p3",
            "role_hijack",
            {"target_behavior": "escalate gradually"},
            requires_multi_turn=True,
            targets=[
                _make_target("dc-a", 0.5),
                _make_target("dc-b", 0.0),
            ],
        ),
        # p4: structured_output, 1 breach
        _make_record(
            "p4",
            "refusal_suppression",
            {"target_output_format": "JSON", "target_behavior": "output secrets"},
            targets=[
                _make_target("dc-a", 0.7),
            ],
        ),
        # p5: exfiltration, both breach
        _make_record(
            "p5",
            "indirect_prompt_injection",
            {"exfil_destination": "http://evil.example", "poison_payload": "inject"},
            targets=[
                _make_target("dc-a", 0.9),
                _make_target("dc-b", 0.8),
            ],
        ),
        # p6: no breach data (no targets) — kept to verify dataset_summary handles it
        _make_record(
            "p6",
            "dan_persona",
            {"role_name": "DAN"},
            targets=[],
        ),
    ]


# ---------------------------------------------------------------------------
# Synthetic end-to-end tests (no DB)
# ---------------------------------------------------------------------------


class TestSyntheticEndToEnd:
    """Whole-chain integration over a hand-built corpus — no DB required."""

    @pytest.fixture(scope="class")
    def corpus(self):
        return _small_corpus()

    @pytest.fixture(scope="class")
    def labels(self, corpus):
        from rogue.grammar.labeler import label_records

        return label_records(corpus)

    @pytest.fixture(scope="class")
    def lifts(self, corpus, labels):
        from rogue.grammar.stats import node_lift_table

        return node_lift_table(corpus, labels, unit="per_target", min_n=1)

    # ------------------------------------------------------------------ #
    # Step 2: labeler                                                       #
    # ------------------------------------------------------------------ #

    def test_labels_returns_dict_keyed_by_primitive_id(self, corpus, labels):
        pids = {r.primitive_id for r in corpus}
        assert set(labels.keys()) == pids

    def test_labels_values_are_sets_of_grammar_nodes(self, labels):
        from rogue.schemas import GrammarNode

        for v in labels.values():
            assert isinstance(v, set)
            for node in v:
                assert isinstance(node, GrammarNode)

    def test_authority_frame_labeled_on_p1(self, labels):
        from rogue.schemas import GrammarNode

        assert GrammarNode.AUTHORITY_FRAME in labels["p1"]

    def test_encoding_obfuscation_labeled_on_p2(self, labels):
        from rogue.schemas import GrammarNode

        assert GrammarNode.ENCODING_OBFUSCATION in labels["p2"]

    def test_multi_turn_escalation_labeled_on_p3(self, labels):
        from rogue.schemas import GrammarNode

        assert GrammarNode.MULTI_TURN_ESCALATION in labels["p3"]

    def test_dan_persona_labeled_on_p6(self, labels):
        from rogue.schemas import GrammarNode

        assert GrammarNode.DAN_PERSONA in labels["p6"]

    def test_label_distribution_returns_complete_dict(self, labels):
        from rogue.grammar.labeler import label_distribution
        from rogue.schemas import GrammarNode

        dist = label_distribution(labels)
        # All GrammarNode values present (including zero-count ones)
        assert set(dist.keys()) == set(GrammarNode)
        assert all(isinstance(v, int) and v >= 0 for v in dist.values())

    # ------------------------------------------------------------------ #
    # Step 3: node_lift_table                                               #
    # ------------------------------------------------------------------ #

    def test_lifts_is_list_of_node_lifts(self, lifts):
        from rogue.grammar.stats import NodeLift

        assert isinstance(lifts, list)
        for nl in lifts:
            assert isinstance(nl, NodeLift)

    def test_lifts_sorted_by_lift_rel_desc(self, lifts):
        for i in range(len(lifts) - 1):
            assert lifts[i].lift_rel >= lifts[i + 1].lift_rel

    def test_lifts_fields_in_range(self, lifts):
        for nl in lifts:
            assert nl.n_with >= 0
            assert nl.n_without >= 0
            assert 0.0 <= nl.p_with <= 1.0
            assert 0.0 <= nl.p_without <= 1.0
            assert 0.0 <= nl.baseline <= 1.0
            assert nl.odds_ratio >= 0.0
            assert 0.0 <= nl.p_value <= 1.0
            lo, hi = nl.with_ci
            assert 0.0 <= lo <= hi <= 1.0

    def test_lifts_baseline_consistent(self, lifts):
        # All rows should share the same baseline (corpus-wide rate)
        baselines = {nl.baseline for nl in lifts}
        assert len(baselines) <= 1, f"Multiple baselines found: {baselines}"

    # ------------------------------------------------------------------ #
    # Step 4: pairwise_interactions (lazy — skip if not yet landed)        #
    # ------------------------------------------------------------------ #

    def test_pairwise_interactions_composes(self, corpus, labels):
        try:
            from rogue.grammar.combinations import pairwise_interactions, suppressed_pair_count
        except ImportError:
            pytest.skip(
                "rogue.grammar.combinations not yet available "
                "(Engineer 5's module has not landed — skip is expected)"
            )

        pairs = pairwise_interactions(corpus, labels, min_cell_n=1)
        assert isinstance(pairs, list), "pairwise_interactions must return a list"

        suppressed = suppressed_pair_count(corpus, labels, min_cell_n=1)
        assert isinstance(suppressed, int) and suppressed >= 0

    # ------------------------------------------------------------------ #
    # Step 5: controlled_analysis (lazy — skip if not yet landed)          #
    # ------------------------------------------------------------------ #

    def test_controlled_analysis_returns_verdict_dict(self, corpus, labels, lifts):
        try:
            from rogue.grammar.validation import controlled_analysis
        except ImportError:
            pytest.skip(
                "rogue.grammar.validation not yet available "
                "(Engineer 6's module has not landed — skip is expected)"
            )

        result = controlled_analysis(corpus, labels)
        assert isinstance(result, dict), "controlled_analysis must return a dict"
        # The contract specifies "VERDICT" but the module may use "verdict" (lowercase).
        # Accept either — the integration guarantee is that the key exists.
        verdict_key = "VERDICT" if "VERDICT" in result else "verdict" if "verdict" in result else None
        assert verdict_key is not None, (
            f"controlled_analysis return dict must contain a 'VERDICT' or 'verdict' key; "
            f"got keys: {list(result.keys())}"
        )
        verdict = result[verdict_key]
        assert isinstance(verdict, str) and verdict, (
            f"'{verdict_key}' must be a non-empty string; got {verdict!r}"
        )

    # ------------------------------------------------------------------ #
    # Full chain: label -> lift -> (pairs) -> (validation)                 #
    # ------------------------------------------------------------------ #

    def test_full_chain_composes(self, corpus, labels, lifts):
        """The core guarantee: the chain runs without error end-to-end."""
        # If we reached here, steps 2 and 3 already ran (fixtures succeeded).
        # Steps 4 and 5 are covered by the individual lazy tests above.
        assert len(corpus) == 6
        assert len(labels) == 6
        # At minimum, nodes that fire on the synthetic corpus are represented
        assert len(lifts) > 0


# ---------------------------------------------------------------------------
# DB-gated integration tests — read-only, skip when DB is down
# ---------------------------------------------------------------------------


def _database_url() -> str:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    return (
        os.environ.get("TEST_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"
    )


@pytest.fixture(scope="module")
def live_session():
    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import sessionmaker

    url = _database_url()
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 5})
        with engine.connect():
            pass
    except (OperationalError, ConnectionRefusedError, socket.gaierror, OSError) as exc:
        pytest.skip(
            f"DB not reachable at {url.split('@')[-1]}: {exc.__class__.__name__} "
            "— run `docker compose up -d` (or set DATABASE_URL/TEST_DATABASE_URL)"
        )
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def test_db_dataset_builds(live_session):
    """Live DB: build_grammar_analysis_dataset returns a non-empty list."""
    from rogue.grammar.dataset import build_grammar_analysis_dataset

    records = build_grammar_analysis_dataset(live_session)
    assert isinstance(records, list)
    assert len(records) > 0


def test_db_node_lift_table_sane(live_session):
    """Live DB: node_lift_table returns NodeLift objects with sane field values."""
    from rogue.grammar.dataset import build_grammar_analysis_dataset
    from rogue.grammar.labeler import label_records
    from rogue.grammar.stats import NodeLift, node_lift_table

    records = build_grammar_analysis_dataset(live_session)
    labels = label_records(records)
    lifts = node_lift_table(records, labels, unit="per_target", min_n=5)

    assert isinstance(lifts, list), "node_lift_table must return a list"
    assert len(lifts) > 0, "expected at least one node present in the live corpus"

    for nl in lifts:
        assert isinstance(nl, NodeLift)
        assert nl.n_with >= 0
        assert nl.n_without >= 0
        assert 0.0 <= nl.p_with <= 1.0
        assert 0.0 <= nl.p_value <= 1.0
        assert nl.odds_ratio >= 0.0
        lo, hi = nl.with_ci
        assert 0.0 <= lo <= hi <= 1.0, f"with_ci out of range for {nl.node}"


def test_db_lift_table_sorted(live_session):
    """Live DB: node_lift_table is sorted by lift_rel descending."""
    from rogue.grammar.dataset import build_grammar_analysis_dataset
    from rogue.grammar.labeler import label_records
    from rogue.grammar.stats import node_lift_table

    records = build_grammar_analysis_dataset(live_session)
    labels = label_records(records)
    lifts = node_lift_table(records, labels, unit="per_target", min_n=5)

    for i in range(len(lifts) - 1):
        assert lifts[i].lift_rel >= lifts[i + 1].lift_rel, (
            f"Lift table not sorted at index {i}: "
            f"{lifts[i].node.value}={lifts[i].lift_rel} > "
            f"{lifts[i+1].node.value}={lifts[i+1].lift_rel}"
        )


def test_db_labels_no_writes(live_session):
    """Live DB: label_records does NOT write to the DB (no PrimitiveGrammarLabel rows added)."""
    from sqlalchemy import text

    from rogue.grammar.dataset import build_grammar_analysis_dataset
    from rogue.grammar.labeler import label_records

    # Count rows before — the table may not exist yet (Engineer 2's migration).
    # Roll back after any failure so the session stays usable for the rest of the test.
    before: int | None = None
    try:
        before = live_session.execute(
            text("SELECT COUNT(*) FROM primitive_grammar_labels")
        ).scalar()
    except Exception:
        live_session.rollback()  # reset aborted transaction before re-using session

    records = build_grammar_analysis_dataset(live_session)
    _labels = label_records(records)

    if before is not None:
        after = live_session.execute(
            text("SELECT COUNT(*) FROM primitive_grammar_labels")
        ).scalar()
        assert after == before, (
            f"label_records wrote to the DB! before={before}, after={after}"
        )
