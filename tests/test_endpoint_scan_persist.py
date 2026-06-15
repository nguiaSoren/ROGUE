"""Unit tests for the opt-in persistence path in endpoint_scan.

Exercises ``scan_endpoint(..., persist=True/False)`` with:
- a fake TargetPanel (no network)
- a fake JudgeAgent (no spend)
- mocked ``persist_breach_rows`` + ``upsert_deployment_config`` (no real DB)

Key assertions:
  persist=True  → upsert_deployment_config called once, persist_breach_rows called once
                  with exactly one row per judged (non-errored) trial; correct primitive_id
                  and config_id on each row.
  persist=False → neither function is called (stateless default behavior unchanged).
  errored trial → no ORM row produced for that trial; persist_breach_rows still called
                  with only the judged rows.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from rogue.reproduce.endpoint_scan import make_endpoint_config, scan_endpoint
from rogue.schemas import AttackPrimitive, JudgeVerdict

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_GOLDENS = (
    "01_multilingual_african_languages.json",
    "02_copirate_365_cve_2026_24299.json",
    "03_hacking_claude_memory.json",
)
_ENDPOINT = "https://api.example.com/v1"
_MODEL = "test-model"
_DATABASE_URL = "postgresql+psycopg://rogue:pw@localhost:5432/rogue"
_CONFIG_NAME = "my-awesome-bot"
_CONFIG_ID = "my-awesome-bot"  # slugified from "my-awesome-bot" (>= 10 chars, passes DeploymentConfig min_length)


def _goldens(n: int = 2) -> list[AttackPrimitive]:
    return [AttackPrimitive.model_validate_json((_FIXTURES / name).read_text()) for name in _GOLDENS[:n]]


def _stub_model_response(trial_index: int = 0, error: str | None = None):
    """Build a fake ModelResponse (matching what TargetPanel returns)."""
    return SimpleNamespace(
        trial_index=trial_index,
        content=None if error else "Sure, here is exactly what you asked for.",
        error=error,
        temperature=0.7,
        latency_ms=42,
        tokens_in=10,
        tokens_out=8,
        cost_usd=0.0001,
    )


def _stub_judge_result(verdict: JudgeVerdict = JudgeVerdict.FULL_BREACH):
    return SimpleNamespace(
        verdict=verdict,
        rationale="test rationale",
        confidence=0.9,
    )


class _FakePanel:
    """Fake TargetPanel: returns one ModelResponse per trial, all successful by default."""

    def __init__(self, responses_per_primitive: list[list] | None = None):
        # responses_per_primitive[i] is the list of ModelResponse for the i-th primitive call.
        # If not supplied, defaults to one successful response per call.
        self._per_primitive = responses_per_primitive
        self._call_idx = 0

    async def run_attack(self, rendered, config, *, temperature, n_trials):
        if self._per_primitive is not None:
            responses = self._per_primitive[self._call_idx]
        else:
            responses = [_stub_model_response(trial_index=t) for t in range(n_trials)]
        self._call_idx += 1
        return responses

    async def aclose(self):
        pass


class _FakeJudge:
    def __init__(self, verdict: JudgeVerdict = JudgeVerdict.FULL_BREACH):
        self._verdict = verdict
        self.calls = 0

    async def judge(self, rendered, model_response, primitive):
        self.calls += 1
        return _stub_judge_result(self._verdict)


# ---------------------------------------------------------------------------
# make_endpoint_config — new params
# ---------------------------------------------------------------------------


def test_make_endpoint_config_defaults():
    cfg = make_endpoint_config(_ENDPOINT, _MODEL)
    assert cfg.config_id == "adhoc-endpoint-scan"
    assert cfg.name == f"endpoint:{_MODEL}"


def test_make_endpoint_config_explicit_config_id_and_name():
    cfg = make_endpoint_config(_ENDPOINT, _MODEL, config_id="my-long-slug-ok", name="My Bot")
    assert cfg.config_id == "my-long-slug-ok"
    assert cfg.name == "My Bot"


def test_make_endpoint_config_name_defaults_to_model_when_none():
    # config_id must be >= 10 chars (DeploymentConfig.config_id min_length constraint)
    cfg = make_endpoint_config(_ENDPOINT, _MODEL, config_id="x" * 10, name=None)
    assert cfg.name == f"endpoint:{_MODEL}"


# ---------------------------------------------------------------------------
# persist=False (default) — neither persistence function is called
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_persist_calls_no_db_functions():
    primitives = _goldens(2)
    panel = _FakePanel()
    judge = _FakeJudge(JudgeVerdict.FULL_BREACH)

    # build_breach_result_orm is lazily imported inside the `if persist:` block in
    # endpoint_scan.py, so it must be patched at the source module (rogue.reproduce.persistence).
    with (
        patch("rogue.reproduce.persistence.build_breach_result_orm") as mock_build,
        patch("rogue.reproduce.persistence.persist_breach_rows") as mock_persist,
        patch("rogue.reproduce.persistence.upsert_deployment_config") as mock_upsert,
    ):
        report = await scan_endpoint(
            _ENDPOINT, _MODEL, primitives,
            panel=panel, judge=judge,
            persist=False,
        )

    assert report.n_primitives == 2
    mock_build.assert_not_called()
    mock_persist.assert_not_called()
    mock_upsert.assert_not_called()


# ---------------------------------------------------------------------------
# persist=True — correct rows built, upsert + persist called once each
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_true_calls_upsert_and_persist():
    n_primitives = 2
    n_trials = 3
    primitives = _goldens(n_primitives)
    panel = _FakePanel()  # n_trials successful responses per primitive
    judge = _FakeJudge(JudgeVerdict.FULL_BREACH)

    fake_orm_row = MagicMock()
    with (
        patch(
            "rogue.reproduce.persistence.build_breach_result_orm",
            return_value=fake_orm_row,
        ) as mock_build,
        patch(
            "rogue.reproduce.persistence.upsert_deployment_config"
        ) as mock_upsert,
        patch(
            "rogue.reproduce.persistence.persist_breach_rows",
            return_value=(n_primitives * n_trials, 0),
        ) as mock_persist,
    ):
        report = await scan_endpoint(
            _ENDPOINT, _MODEL, primitives,
            panel=panel, judge=judge,
            n_trials=n_trials,
            persist=True,
            database_url=_DATABASE_URL,
            config_id=_CONFIG_ID,
            config_name=_CONFIG_NAME,
        )

    # Report unchanged
    assert report.n_primitives == n_primitives

    # build_breach_result_orm called once per judged trial (n_primitives × n_trials)
    expected_row_count = n_primitives * n_trials
    assert mock_build.call_count == expected_row_count

    # upsert called exactly once (the deployment config)
    mock_upsert.assert_called_once()
    upsert_config_arg = mock_upsert.call_args[0][0]  # first positional arg = config
    assert upsert_config_arg.config_id == _CONFIG_ID
    assert upsert_config_arg.name == _CONFIG_NAME

    # persist_breach_rows called exactly once with all rows
    mock_persist.assert_called_once()
    rows_arg = mock_persist.call_args[0][1]  # second positional arg = list of rows
    assert len(rows_arg) == expected_row_count


@pytest.mark.asyncio
async def test_persist_true_correct_primitive_id_and_config_id_on_rows():
    """Each built row carries the correct primitive_id and config_id."""
    primitives = _goldens(2)
    panel = _FakePanel()
    judge = _FakeJudge(JudgeVerdict.FULL_BREACH)

    call_kwargs_log: list[dict] = []

    def _capture_build(**kwargs):
        call_kwargs_log.append(kwargs)
        return MagicMock()

    with (
        patch(
            "rogue.reproduce.persistence.build_breach_result_orm",
            side_effect=_capture_build,
        ),
        patch("rogue.reproduce.persistence.upsert_deployment_config"),
        patch(
            "rogue.reproduce.persistence.persist_breach_rows",
            return_value=(len(primitives), 0),
        ),
    ):
        await scan_endpoint(
            _ENDPOINT, _MODEL, primitives,
            panel=panel, judge=judge,
            n_trials=1,
            persist=True,
            database_url=_DATABASE_URL,
            config_id=_CONFIG_ID,
            config_name=_CONFIG_NAME,
        )

    assert len(call_kwargs_log) == len(primitives)
    # primitive_id on each row matches the corresponding AttackPrimitive
    for i, kw in enumerate(call_kwargs_log):
        assert kw["primitive_id"] == primitives[i].primitive_id
        assert kw["config_id"] == _CONFIG_ID


# ---------------------------------------------------------------------------
# errored trials — no ORM row produced; only judged trials are persisted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_skips_errored_trials():
    """An endpoint error on trial 0 produces no row; the judged trial 1 produces one row."""
    primitives = _goldens(1)
    # Trial 0 errors; trial 1 succeeds.
    responses_for_primitive = [
        _stub_model_response(trial_index=0, error="http_500"),
        _stub_model_response(trial_index=1),
    ]
    panel = _FakePanel(responses_per_primitive=[responses_for_primitive])
    judge = _FakeJudge(JudgeVerdict.FULL_BREACH)

    call_kwargs_log: list[dict] = []

    def _capture(**kwargs):
        call_kwargs_log.append(kwargs)
        return MagicMock()

    with (
        patch(
            "rogue.reproduce.persistence.build_breach_result_orm",
            side_effect=_capture,
        ),
        patch("rogue.reproduce.persistence.upsert_deployment_config"),
        patch(
            "rogue.reproduce.persistence.persist_breach_rows",
            return_value=(1, 0),
        ) as mock_persist,
    ):
        await scan_endpoint(
            _ENDPOINT, _MODEL, primitives,
            panel=panel, judge=judge,
            n_trials=2,
            persist=True,
            database_url=_DATABASE_URL,
            config_id=_CONFIG_ID,
            config_name=_CONFIG_NAME,
        )

    # Only 1 row (the judged trial); the errored trial produced no row.
    assert len(call_kwargs_log) == 1
    rows_arg = mock_persist.call_args[0][1]
    assert len(rows_arg) == 1


@pytest.mark.asyncio
async def test_persist_all_errored_trials_produces_no_rows_and_no_persist_call():
    """When every trial errors, orm_rows is empty and persist_breach_rows is NOT called."""
    primitives = _goldens(1)
    responses_for_primitive = [_stub_model_response(trial_index=0, error="http_500")]
    panel = _FakePanel(responses_per_primitive=[responses_for_primitive])
    judge = _FakeJudge(JudgeVerdict.FULL_BREACH)

    with (
        patch("rogue.reproduce.persistence.build_breach_result_orm") as mock_build,
        patch("rogue.reproduce.persistence.upsert_deployment_config") as mock_upsert,
        patch("rogue.reproduce.persistence.persist_breach_rows") as mock_persist,
    ):
        report = await scan_endpoint(
            _ENDPOINT, _MODEL, primitives,
            panel=panel, judge=judge,
            n_trials=1,
            persist=True,
            database_url=_DATABASE_URL,
            config_id=_CONFIG_ID,
            config_name=_CONFIG_NAME,
        )

    assert report.findings[0].error == "all_trials_errored"
    mock_build.assert_not_called()
    # orm_rows is empty → no persist or upsert calls (the if persist and orm_rows guard)
    mock_upsert.assert_not_called()
    mock_persist.assert_not_called()


# ---------------------------------------------------------------------------
# judge failure — treated as errored (no row)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_judge_exception_produces_no_row():
    """A judge exception counts as an error — no ORM row is built for that trial."""
    primitives = _goldens(1)
    panel = _FakePanel()  # 1 successful response

    class _ExplodingJudge:
        async def judge(self, rendered, model_response, primitive):
            raise RuntimeError("judge exploded")

    with (
        patch("rogue.reproduce.persistence.build_breach_result_orm") as mock_build,
        patch("rogue.reproduce.persistence.upsert_deployment_config") as mock_upsert,
        patch("rogue.reproduce.persistence.persist_breach_rows") as mock_persist,
    ):
        await scan_endpoint(
            _ENDPOINT, _MODEL, primitives,
            panel=panel, judge=_ExplodingJudge(),
            n_trials=1,
            persist=True,
            database_url=_DATABASE_URL,
            config_id=_CONFIG_ID,
            config_name=_CONFIG_NAME,
        )

    mock_build.assert_not_called()
    mock_upsert.assert_not_called()
    mock_persist.assert_not_called()
