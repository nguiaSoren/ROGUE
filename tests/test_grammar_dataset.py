"""Tests for the grammar analysis dataset (Engineer 7 slice).

Two layers:

* PURE unit tests over :func:`aggregate_primitive` / :func:`dataset_summary` — DB-free,
  hand-built rows, asserting the breached / breach_rate / n_trials aggregation contract
  (including run_date collapse and trial-weighting).
* DB-gated integration tests — connect to whatever ``DATABASE_URL`` / ``TEST_DATABASE_URL``
  points at (the real data lives in Neon), skip cleanly if unreachable. READ-ONLY.
"""

from __future__ import annotations

import os
import socket

import pytest

from rogue.grammar.dataset import (
    PrimitiveRecord,
    TargetOutcome,
    aggregate_primitive,
    build_grammar_analysis_dataset,
    dataset_summary,
)


# --------------------------------------------------------------------------- #
# PURE unit tests — no DB.
# --------------------------------------------------------------------------- #
_META = {
    "dc-openai": ("openai", "gpt"),
    "dc-anthropic": ("anthropic", "claude"),
}


def _row(dc, n, any_r, full_r):
    return {
        "deployment_config_id": dc,
        "n_trials": n,
        "any_breach_rate": any_r,
        "full_breach_rate": full_r,
    }


def test_aggregate_single_target_breached():
    rec = aggregate_primitive(
        "p1", "instruction_override", [], {"role": "x"}, False, "direct_chat",
        breach_rows=[_row("dc-openai", 10, 0.4, 0.1)],
        target_meta=_META,
    )
    assert isinstance(rec, PrimitiveRecord)
    assert rec.has_breach_data is True
    assert rec.breached is True
    assert rec.breach_rate == pytest.approx(0.4)
    assert rec.n_trials == 10
    assert len(rec.targets) == 1
    t = rec.targets[0]
    assert isinstance(t, TargetOutcome)
    assert (t.vendor, t.model_family) == ("openai", "gpt")
    assert t.breached is True


def test_aggregate_no_breach_data():
    rec = aggregate_primitive(
        "p2", "obfuscation", [], {}, True, "encoded",
        breach_rows=[],
        target_meta=_META,
    )
    assert rec.has_breach_data is False
    assert rec.breached is False
    assert rec.breach_rate == 0.0
    assert rec.n_trials == 0
    assert rec.targets == []


def test_aggregate_threshold_gates_breached():
    # any_breach_rate 0.2 with threshold 0.0 → breached; with 0.5 → not.
    rows = [_row("dc-openai", 5, 0.2, 0.0)]
    hot = aggregate_primitive("p", "f", [], {}, False, "v", breach_rows=rows,
                              target_meta=_META, breach_threshold=0.0)
    cold = aggregate_primitive("p", "f", [], {}, False, "v", breach_rows=rows,
                               target_meta=_META, breach_threshold=0.5)
    assert hot.breached is True
    assert cold.breached is False
    assert cold.breach_rate == pytest.approx(0.2)  # rate still reported


def test_aggregate_runs_collapse_trial_weighted():
    # Same (primitive, dc) across two run_dates → ONE target, trials summed,
    # rate trial-weighted: (90*0.0 + 10*1.0)/100 = 0.1.
    rows = [
        _row("dc-openai", 90, 0.0, 0.0),
        _row("dc-openai", 10, 1.0, 0.5),
    ]
    rec = aggregate_primitive("p", "f", [], {}, False, "v", breach_rows=rows,
                              target_meta=_META)
    assert len(rec.targets) == 1
    t = rec.targets[0]
    assert t.n_trials == 100
    assert t.any_breach_rate == pytest.approx(0.1)
    assert t.full_breach_rate == pytest.approx(0.05)
    assert rec.n_trials == 100
    assert rec.breach_rate == pytest.approx(0.1)


def test_aggregate_max_across_targets_and_any_breached():
    rows = [
        _row("dc-openai", 10, 0.0, 0.0),    # not breached
        _row("dc-anthropic", 10, 0.3, 0.1),  # breached
    ]
    rec = aggregate_primitive("p", "f", [], {}, False, "v", breach_rows=rows,
                              target_meta=_META)
    assert len(rec.targets) == 2
    assert rec.breached is True              # ANY target breached
    assert rec.breach_rate == pytest.approx(0.3)  # MAX any_breach_rate
    assert rec.n_trials == 20


def test_aggregate_none_rate_does_not_poison():
    # An all-errored run_date contributes a None rate; it must not crash or skew.
    rows = [
        _row("dc-openai", 8, 0.5, 0.25),
        _row("dc-openai", 4, None, None),
    ]
    rec = aggregate_primitive("p", "f", [], {}, False, "v", breach_rows=rows,
                              target_meta=_META)
    t = rec.targets[0]
    assert t.any_breach_rate == pytest.approx(0.5)  # None row dropped from weighting
    assert t.n_trials == 12                          # but trials still counted


def test_aggregate_unknown_target_meta_falls_back():
    rec = aggregate_primitive("p", "f", [], {}, False, "v",
                              breach_rows=[_row("dc-mystery", 3, 0.1, 0.0)],
                              target_meta=_META)
    t = rec.targets[0]
    assert (t.vendor, t.model_family) == ("unknown", "unknown")


def test_dataset_summary_pure():
    recs = [
        aggregate_primitive("a", "fam1", [], {}, False, "v",
                            breach_rows=[_row("dc-openai", 10, 0.5, 0.0)],
                            target_meta=_META),
        aggregate_primitive("b", "fam1", [], {}, False, "v",
                            breach_rows=[_row("dc-openai", 10, 0.0, 0.0)],
                            target_meta=_META),
        aggregate_primitive("c", "fam2", [], {}, False, "v",
                            breach_rows=[], target_meta=_META),  # no breach data
    ]
    s = dataset_summary(recs)
    assert s["n_total"] == 3
    assert s["n_with_breach_data"] == 2
    assert s["n_breached"] == 1
    assert s["breach_base_rate"] == pytest.approx(0.5)  # 1 of 2 analyzable
    assert s["family_counts"]["fam1"] == 2
    assert s["family_counts"]["fam2"] == 1
    assert set(s.keys()) >= {
        "n_total", "n_with_breach_data", "n_breached",
        "breach_base_rate", "family_counts", "family_breached",
    }


def test_dataset_summary_empty():
    s = dataset_summary([])
    assert s["n_total"] == 0
    assert s["n_with_breach_data"] == 0
    assert s["breach_base_rate"] == 0.0


# --------------------------------------------------------------------------- #
# DB-gated integration — READ-ONLY, skip cleanly when unreachable.
# --------------------------------------------------------------------------- #
def _database_url() -> str:
    from dotenv import load_dotenv

    load_dotenv()
    return os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL") or (
        "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"
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
            "— run `docker compose up -d` (or set DATABASE_URL)"
        )
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def test_build_returns_records(live_session):
    records = build_grammar_analysis_dataset(live_session)
    assert isinstance(records, list)
    assert len(records) > 0
    assert all(isinstance(r, PrimitiveRecord) for r in records)


def test_records_with_breach_data_have_targets(live_session):
    records = build_grammar_analysis_dataset(live_session)
    with_data = [r for r in records if r.has_breach_data]
    assert with_data, "expected at least one primitive with breach data"
    for r in with_data:
        assert len(r.targets) >= 1
        assert 0.0 <= r.breach_rate <= 1.0
        assert r.n_trials >= 0


def test_target_outcomes_well_formed(live_session):
    records = build_grammar_analysis_dataset(live_session)
    seen = 0
    for r in records:
        for t in r.targets:
            assert 0.0 <= t.any_breach_rate <= 1.0
            assert 0.0 <= t.full_breach_rate <= 1.0
            assert isinstance(t.vendor, str) and t.vendor
            assert isinstance(t.model_family, str) and t.model_family
            assert t.n_trials >= 1
            seen += 1
    assert seen > 0, "expected at least one TargetOutcome across the corpus"


def test_summary_keys_present(live_session):
    records = build_grammar_analysis_dataset(live_session)
    s = dataset_summary(records)
    for key in ("n_total", "n_with_breach_data", "n_breached",
                "breach_base_rate", "family_counts", "family_breached"):
        assert key in s
    assert s["n_total"] == len(records)
    assert 0.0 <= s["breach_base_rate"] <= 1.0
