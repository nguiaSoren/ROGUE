"""Unit tests for retrieval Recall@K evaluation — synthetic, NO DB, NO network.

These exercise the *pure* core (``compute_recall`` + ``TechniqueIndex``) with
hand-built vectors so the winner's rank is exactly controllable, and assert:

  * the recall math (winner at rank 3 -> Recall@2 == 0, Recall@5 == 1);
  * per-target (vendor/family) aggregation sums correctly;
  * uncovered winners (no profile in the universe) are COUNTED, not dropped;
  * the MIN_K floor lifts low-K recall the way the retriever would.

No Postgres, no OpenAI: vectors are built by hand (and via the offline
``deterministic_embed_fn`` for one end-to-end-ish index check).
"""

from __future__ import annotations

import math

from rogue.retrieval.evaluation import (
    TechniqueIndex,
    WinnerEvent,
    compute_recall,
    render_report,
)


# ---------------------------------------------------------------------------
# Helpers — build an index whose ranking is fully under our control.
# ---------------------------------------------------------------------------


def _axis(i: int, dim: int) -> list[float]:
    """Unit vector along axis i (one-hot). Orthogonal axes -> cosine 0 between
    distinct axes, cosine 1 with itself."""
    v = [0.0] * dim
    v[i] = 1.0
    return v


def _graded_index(labels: list[str], dim: int = 8, min_k: int = 25) -> TechniqueIndex:
    """Index where label[j] points 'mostly' along axis 0 with decreasing strength,
    so a query along axis 0 ranks them in list order: labels[0] is rank 1, etc."""
    pairs = []
    for j, label in enumerate(labels):
        # Strong axis-0 component that decreases with j, tiny orthogonal jitter
        # on a distinct axis to keep vectors distinct.
        v = [0.0] * dim
        v[0] = 1.0 - 0.01 * j
        v[1 + (j % (dim - 1))] = 0.001
        pairs.append((label, v))
    return TechniqueIndex.from_pairs(pairs, min_k=min_k)


# ---------------------------------------------------------------------------
# Core recall math.
# ---------------------------------------------------------------------------


def test_winner_at_rank_three():
    """Winner at rank 3 => Recall@2 == 0, Recall@5 == 1 (with MIN_K low enough)."""
    labels = ["t0", "t1", "t2", "t3", "t4"]  # query along axis0 ranks in this order
    index = _graded_index(labels, min_k=1)  # MIN_K must not lift @2 to include rank3
    query = _axis(0, 8)

    ev = WinnerEvent(
        parent_id="p1",
        target_key="anthropic/claude-haiku-4-5",
        winner_label="t2",  # rank 3
        vendor="anthropic",
        family="claude",
        query_embedding=query,
    )

    # Sanity: the index really ranks the winner at 3.
    assert index.rank_of(query, "t2") == 3

    res = compute_recall([ev], index, ks=(2, 5))
    assert res["overall_recall_at_k"][2]["recall"] == 0.0
    assert res["overall_recall_at_k"][2]["hits"] == 0
    assert res["overall_recall_at_k"][5]["recall"] == 1.0
    assert res["overall_recall_at_k"][5]["hits"] == 1
    assert res["n_events"] == 1
    assert res["uncovered"]["count"] == 0


def test_min_k_floor_lifts_low_k():
    """A K below MIN_K is treated as MIN_K — winner at rank 3 hits @1 when MIN_K>=3."""
    labels = ["t0", "t1", "t2", "t3"]
    index = _graded_index(labels, min_k=3)  # floor pulls @1 up to @3
    query = _axis(0, 8)
    ev = WinnerEvent(
        parent_id="p",
        target_key="x",
        winner_label="t2",  # rank 3
        vendor="v",
        family="f",
        query_embedding=query,
    )
    res = compute_recall([ev], index, ks=(1, 2, 3))
    # All collapse to effective-K = max(K, 3) = 3, so all hit.
    assert res["overall_recall_at_k"][1]["recall"] == 1.0
    assert res["overall_recall_at_k"][2]["recall"] == 1.0
    assert res["overall_recall_at_k"][3]["recall"] == 1.0


def test_uncovered_winner_counted_not_dropped():
    """A winner with no profile in the universe is counted in the denominator and
    surfaced as uncovered — never silently dropped."""
    labels = ["a", "b", "c"]
    index = _graded_index(labels, min_k=1)
    query = _axis(0, 8)

    covered = WinnerEvent("p1", "tgt", "a", "openai", "gpt", query)  # rank 1, hits
    uncovered = WinnerEvent("p2", "tgt", "ghost", "openai", "gpt", query)  # no profile

    res = compute_recall([covered, uncovered], index, ks=(50,))

    assert res["n_events"] == 2
    assert res["uncovered"]["count"] == 1
    assert "ghost" in res["uncovered"]["labels"]
    # Denominator is 2 (uncovered NOT dropped): 1 hit / 2 events = 0.5.
    assert res["overall_recall_at_k"][50]["n"] == 2
    assert res["overall_recall_at_k"][50]["hits"] == 1
    assert res["overall_recall_at_k"][50]["recall"] == 0.5


def test_uncovered_caps_achievable_recall():
    """If every winner is uncovered, recall is 0 at every K but events are kept."""
    index = _graded_index(["a", "b"], min_k=1)
    q = _axis(0, 4)
    evs = [
        WinnerEvent("p1", "t", "ghost1", "v", "f", q),
        WinnerEvent("p2", "t", "ghost2", "v", "f", q),
    ]
    res = compute_recall(evs, index, ks=(10, 50, 100))
    assert res["uncovered"]["count"] == 2
    for k in (10, 50, 100):
        assert res["overall_recall_at_k"][k]["recall"] == 0.0
        assert res["overall_recall_at_k"][k]["n"] == 2


# ---------------------------------------------------------------------------
# Per-target aggregation.
# ---------------------------------------------------------------------------


def test_per_target_aggregation_sums():
    """Per-target hits/n sum back to the overall hits/n for each K."""
    labels = ["t0", "t1", "t2", "t3", "t4"]
    index = _graded_index(labels, min_k=1)
    q = _axis(0, 8)

    events = [
        # anthropic/claude: winners at rank 1 (hit@2) and rank 5 (miss@2)
        WinnerEvent("p1", "tA", "t0", "anthropic", "claude", q),
        WinnerEvent("p2", "tA", "t4", "anthropic", "claude", q),
        # openai/gpt: winner at rank 1 (hit@2)
        WinnerEvent("p3", "tB", "t0", "openai", "gpt", q),
    ]
    res = compute_recall(events, index, ks=(2, 50))

    # Overall @2: t0(rank1) hit, t4(rank5) miss, t0(rank1) hit => 2/3.
    assert res["overall_recall_at_k"][2]["hits"] == 2
    assert res["overall_recall_at_k"][2]["n"] == 3

    # Per-target rows present for both groups.
    by_key = {(r["vendor"], r["family"]): r for r in res["per_target"]}
    assert set(by_key) == {("anthropic", "claude"), ("openai", "gpt")}

    anth = by_key[("anthropic", "claude")]
    oa = by_key[("openai", "gpt")]
    assert anth["n_events"] == 2
    assert oa["n_events"] == 1
    assert anth["recall_at_k"][2]["hits"] == 1  # only t0 hit @2
    assert oa["recall_at_k"][2]["hits"] == 1

    # Aggregation invariant: per-target hits sum to overall hits at every K.
    for k in (2, 50):
        summed = sum(r["recall_at_k"][k]["hits"] for r in res["per_target"])
        assert summed == res["overall_recall_at_k"][k]["hits"]
        summed_n = sum(r["n_events"] for r in res["per_target"])
        assert summed_n == res["overall_recall_at_k"][k]["n"]


def test_empty_events_safe():
    """No events => recall 0, n 0, no crash, no uncovered."""
    index = _graded_index(["a"], min_k=1)
    res = compute_recall([], index, ks=(10, 50))
    assert res["n_events"] == 0
    assert res["uncovered"]["count"] == 0
    assert res["overall_recall_at_k"][50]["recall"] == 0.0
    assert res["per_target"] == []


# ---------------------------------------------------------------------------
# Index semantics + deterministic embedder smoke (still no DB / network).
# ---------------------------------------------------------------------------


def test_rank_of_returns_none_for_missing_label():
    index = _graded_index(["a", "b"], min_k=1)
    assert index.rank_of(_axis(0, 8), "nope") is None
    assert index.rank_of(_axis(0, 8), "a") == 1


def test_deterministic_embed_self_similarity_ranks_first():
    """Using the real offline embedder: a target whose query text equals a
    technique's text retrieves that technique at rank 1 (self-cosine ~1)."""
    from rogue.retrieval.embed import deterministic_embed_fn

    embed = deterministic_embed_fn(dim=64)
    labels = ["alpha", "beta", "gamma"]
    pairs = [(lbl, embed(f"technique:{lbl}")) for lbl in labels]
    index = TechniqueIndex.from_pairs(pairs, min_k=1)

    # Query identical to beta's text -> beta should be rank 1.
    q = embed("technique:beta")
    assert index.rank_of(q, "beta") == 1
    # Self-cosine is ~1.
    qnorm = math.sqrt(sum(x * x for x in q))
    assert qnorm > 0


def test_render_report_runs_and_flags_gate():
    """render_report produces markdown and surfaces the Recall@50 gate verdict."""
    labels = ["t0", "t1"]
    index = _graded_index(labels, min_k=1)
    q = _axis(0, 8)
    ev = WinnerEvent("p", "t", "t0", "anthropic", "claude", q)
    res = compute_recall([ev], index, ks=(10, 50))
    res["meta"] = {
        "n_profiles": 2,
        "suppress_known_successes": True,
        "embedder": "deterministic",
    }
    report = render_report(res)
    assert "Recall@K" in report
    assert "Recall@50 >= 80%" in report
    assert "uncovered winners" in report
    # rank-1 winner => 100% recall => gate PASS
    assert "PASS" in report
