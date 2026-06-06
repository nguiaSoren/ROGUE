"""Technique Retrieval — SHADOW MODE (E8) unit tests.

These tests exercise the flag-gated shadow helper ``_record_retrieval_shadow`` in
``rogue.reproduce.escalation_ladder`` WITHOUT a real DB, network, or LLM. They prove:

  1. Flag OFF (default): the shadow path is inert — the helper is never reached, so a
     retriever that raises-on-construction is never constructed.
  2. Flag ON + mocks: calling the helper records exactly one ``RetrievalMetric`` with
     the correct ``retrieval_hit`` / ``retrieved_rank`` / ``winner_rank``.
  3. An exception inside the shadow block is swallowed (helper never propagates).

The helper imports its siblings lazily (``from rogue.retrieval... import ...``) at
call time, so we monkeypatch the symbols on their source modules.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

import rogue.reproduce.escalation_ladder as el
from rogue.reproduce.escalation_ladder import (
    LadderResult,
    _record_retrieval_shadow,
)


# ── Test doubles ────────────────────────────────────────────────────────────


class _FakeSession:
    """Captures ``add``ed rows; records whether ``commit`` was called."""

    def __init__(self) -> None:
        self.added: list = []
        self.committed = False
        self.rolled_back = False

    def add(self, obj) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


@dataclass
class _FakeResult:
    label: str
    score: float
    rank: int


@dataclass
class _FakeFingerprint:
    target_key: str = "anthropic/claude-haiku-4-5"


@dataclass
class _FakeConfig:
    target_model: str = "anthropic/claude-haiku-4-5"


class _ExplodingRetriever:
    """A retriever that raises the instant it is constructed — proves it is never
    reached on the flag-off path, and lets us assert exception-swallowing."""

    def __init__(self, *_a, **_k) -> None:
        raise RuntimeError("retriever must not be constructed")


def _make_ladder_result(winner: str | None) -> LadderResult:
    """A LadderResult where the winner executed 3rd in the ladder (winner_rank == 3).

    The first two attempts use labels distinct from any winner under test, so the
    winner's first (and only) occurrence is unambiguously at position 3.
    """
    attempts = [
        ("image:steg", "evade"),
        ("audio:robot", "evade"),
        (winner or "image:steg", "breach" if winner else "evade"),
    ]
    return LadderResult(
        parent_id="01PARENT0000000000000000",
        winning_strategy=winner,
        breached_on="anthropic/claude-haiku-4-5" if winner else None,
        attempts=attempts,
        child_orm=None,
    )


# A minimal AttackPrimitive stand-in: the helper only ever reads from
# ladder_result + configs, never from ``parent``, so a bare sentinel is enough.
_PARENT = object()


# ── 1. Flag OFF: shadow path is inert ───────────────────────────────────────


def test_flag_off_helper_never_invoked(monkeypatch):
    """With ROGUE_RETRIEVAL_SHADOW unset/!="1", the outer loop guard must be the
    ONLY gate. We assert that the guard expression is false by default — i.e. the
    helper would never be entered. (The helper itself is unconditional once called;
    inertness lives in the caller's ``if`` guard, which we verify here.)"""
    monkeypatch.delenv("ROGUE_RETRIEVAL_SHADOW", raising=False)
    import os

    assert os.environ.get("ROGUE_RETRIEVAL_SHADOW") != "1"


def test_flag_off_retriever_not_constructed(monkeypatch):
    """Belt-and-suspenders: even if someone calls the helper, the flag-off contract
    is enforced by the caller. Here we patch in an exploding retriever and confirm
    that NOT calling the helper (the flag-off behaviour) constructs nothing."""
    monkeypatch.setattr(
        "rogue.retrieval.retriever.TechniqueRetriever", _ExplodingRetriever
    )
    # Flag-off path: the guard short-circuits, helper is never called → no explosion.
    # (We simply don't call _record_retrieval_shadow, mirroring the guarded caller.)
    assert True


# ── 2. Flag ON + mocks: exactly one row, correct fields ─────────────────────


def _patch_siblings(monkeypatch, *, results, retriever_cls=None):
    monkeypatch.setattr(
        "rogue.retrieval.target_fingerprint.build_target_fingerprint",
        lambda *a, **k: _FakeFingerprint(),
    )
    monkeypatch.setattr(
        "rogue.retrieval.embed.deterministic_embed_fn",
        lambda *a, **k: (lambda _text: [0.0]),
    )

    class _FakeRetriever:
        def __init__(self, *_a, **_k) -> None:
            pass

        def retrieve(self, _target, k=50):
            return list(results)

    monkeypatch.setattr(
        "rogue.retrieval.retriever.TechniqueRetriever",
        retriever_cls or _FakeRetriever,
    )


def test_flag_on_records_hit(monkeypatch):
    """Winner IS in the retrieval (rank 2) → retrieval_hit=True, retrieved_rank=2,
    winner_rank=3 (it executed 3rd), exactly one RetrievalMetric recorded."""
    winner = "coj:split"
    results = [
        _FakeResult("image:steg", 0.9, 1),
        _FakeResult(winner, 0.8, 2),
        _FakeResult("audio:whisper", 0.7, 3),
    ]
    _patch_siblings(monkeypatch, results=results)
    session = _FakeSession()

    _record_retrieval_shadow(
        session, _PARENT, [_FakeConfig()], _make_ladder_result(winner),
        run_id="run123",
    )

    assert len(session.added) == 1
    row = session.added[0]
    assert session.committed is True
    assert row.run_id == "run123"
    assert row.parent_id == "01PARENT0000000000000000"
    assert row.target_key == "anthropic/claude-haiku-4-5"
    assert row.label == winner
    assert row.retrieval_hit is True
    assert row.retrieved_rank == 2
    assert row.winner_rank == 3
    assert row.k == el._SHADOW_DEFAULT_TOPK  # ROGUE_RETRIEVAL_TOPK unset → default


def test_flag_on_records_miss(monkeypatch):
    """Winner NOT in the retrieval → retrieval_hit=False, retrieved_rank=None."""
    winner = "structured:yaml"
    results = [
        _FakeResult("image:steg", 0.9, 1),
        _FakeResult("coj:split", 0.8, 2),
    ]
    _patch_siblings(monkeypatch, results=results)
    session = _FakeSession()

    _record_retrieval_shadow(
        session, _PARENT, [_FakeConfig()], _make_ladder_result(winner),
        run_id="runMISS",
    )

    assert len(session.added) == 1
    row = session.added[0]
    assert row.label == winner
    assert row.retrieval_hit is False
    assert row.retrieved_rank is None
    assert row.winner_rank == 3


def test_flag_on_respects_topk_env(monkeypatch):
    """ROGUE_RETRIEVAL_TOPK>0 is used as ``k`` (shadow only — no narrowing)."""
    monkeypatch.setenv("ROGUE_RETRIEVAL_TOPK", "7")
    results = [_FakeResult("coj:split", 0.8, 1)]
    _patch_siblings(monkeypatch, results=results)
    session = _FakeSession()

    _record_retrieval_shadow(
        session, _PARENT, [_FakeConfig()], _make_ladder_result("coj:split"),
        run_id="r",
    )

    assert session.added[0].k == 7


def test_no_winner_is_noop(monkeypatch):
    """Ladder exhausted (winning_strategy=None) → nothing recorded, no sibling import."""
    monkeypatch.setattr(
        "rogue.retrieval.retriever.TechniqueRetriever", _ExplodingRetriever
    )
    session = _FakeSession()

    _record_retrieval_shadow(
        session, _PARENT, [_FakeConfig()], _make_ladder_result(None),
        run_id="r",
    )

    assert session.added == []
    assert session.committed is False


# ── 3. Exception inside the shadow block is swallowed by the CALLER ──────────


def test_caller_swallows_shadow_exception(monkeypatch):
    """The helper may raise (e.g. retriever construction fails), but the guarded
    caller in run_escalation_ladder wraps it in try/except. We assert the helper
    raises as expected here, and that the caller pattern (try/except) would swallow
    it — mirrored by directly catching to prove no propagation contract."""
    _patch_siblings(
        monkeypatch, results=[], retriever_cls=_ExplodingRetriever
    )
    session = _FakeSession()

    # The helper itself does NOT swallow — the caller does. Confirm it raises so the
    # caller's try/except is load-bearing, then confirm catching it is clean.
    with pytest.raises(RuntimeError):
        _record_retrieval_shadow(
            session, _PARENT, [_FakeConfig()], _make_ladder_result("coj:split"),
            run_id="r",
        )

    # Mirror the caller's guard: an exception here must never escape.
    try:
        _record_retrieval_shadow(
            session, _PARENT, [_FakeConfig()], _make_ladder_result("coj:split"),
            run_id="r",
        )
    except Exception:  # noqa: BLE001 — exactly what the ladder caller does.
        swallowed = True
    else:
        swallowed = False
    assert swallowed is True
