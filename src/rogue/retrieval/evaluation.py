"""Offline retrieval evaluation — Recall@K by replaying historical ladder runs.

This is the deployment gate (and a publishable result) for the Technique
Retrieval System: *does the retriever's top-K contain the technique that
eventually won?* We answer it by replaying real escalation-ladder telemetry
(``ladder_attempts``), with no spend, using the deterministic offline embedder.

Method (the honest denominator matters)
---------------------------------------
1. Technique universe — ``build_technique_profiles(session)`` enumerates every
   ladder strategy as a :class:`~rogue.schemas.TechniqueProfile`. Each profile is
   embedded (``build_technique_embedding_text`` -> ``embed_fn``) into an in-memory
   index. The index ranks by cosine similarity exactly as
   :class:`~rogue.retrieval.retriever.TechniqueRetriever` does
   (``similarity = 1 - cosine_distance``, ``MIN_K`` floor), so eval does not
   depend on DB write state and is cheap/repeatable.
2. Winner events — every ``ladder_attempts`` row with ``is_winner`` gives one
   replay event: ``(parent_id, target_key, winner_label)``. ``winner_label`` is
   the row's ``entity_id``; ``target_key`` is the row's ``config_id`` (the
   ``target_model`` string — a documented schema misnomer).
3. Replay — for each event, build a :class:`TargetFingerprint`, retrieve a
   ranking over the technique universe, find the rank of ``winner_label``, and
   record ``winner_label in top-K`` for each K.
4. Aggregate — overall Recall@K, per-target (vendor/family) breakdown, ``n_events``,
   and a *separate* ``uncovered`` count: events whose ``winner_label`` has **no
   profile in the universe** and so can never be retrieved. Uncovered winners are
   NOT silently dropped — they are counted against the denominator (they cap the
   achievable recall), and surfaced explicitly so the headline number is honest.

Leakage note (reported, not hidden)
-----------------------------------
``build_target_fingerprint(target_model, session=...)`` populates
``known_successes`` from the *same* ``ladder_attempts`` winner rows, so a target's
fingerprint text can already mention the winning label. That mildly optimistically
biases recall. ``evaluate_recall(..., suppress_known_successes=True)`` (the eval
default) strips ``known_successes`` from each fingerprint before retrieval so the
measured recall reflects a cold target, not a target the system has already broken.

Public API
----------
evaluate_recall(session, *, embed_fn, ks=(10, 25, 50, 100)) -> dict
compute_recall(events, index, ks=(...)) -> dict   # pure, DB-free, unit-testable
render_report(result: dict) -> str
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Iterable, Optional, Sequence

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

    from rogue.schemas import TechniqueProfile

EmbedFn = Callable[[str], list[float]]

# Mirror of TechniqueRetriever.MIN_K. Imported lazily at call time when the
# sibling module is available; this constant is the offline fallback so the
# in-memory ranking matches retriever semantics even before E5 lands.
_DEFAULT_MIN_K = 25


# ---------------------------------------------------------------------------
# Replay event + in-memory technique index (both DB-free, unit-testable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WinnerEvent:
    """One replayed ladder win.

    ``query_embedding`` is the embedded target fingerprint for this event (the
    retrieval query). Carrying the embedding (rather than a fingerprint object)
    keeps :func:`compute_recall` pure and DB/embedder-free.
    """

    parent_id: str
    target_key: str
    winner_label: str
    vendor: str
    family: str
    query_embedding: Sequence[float]


@dataclass
class TechniqueIndex:
    """In-memory cosine index over the technique universe.

    Mirrors :class:`~rogue.retrieval.retriever.TechniqueRetriever`:
    ``similarity = 1 - cosine_distance`` and a ``MIN_K`` floor on the number of
    candidates returned. No DB. Vectors need not be pre-normalised — cosine is
    computed with explicit norms.
    """

    labels: list[str] = field(default_factory=list)
    vectors: list[Sequence[float]] = field(default_factory=list)
    min_k: int = _DEFAULT_MIN_K
    _norms: list[float] = field(default_factory=list, repr=False)

    @classmethod
    def from_pairs(
        cls,
        pairs: Iterable[tuple[str, Sequence[float]]],
        *,
        min_k: int = _DEFAULT_MIN_K,
    ) -> "TechniqueIndex":
        labels: list[str] = []
        vectors: list[Sequence[float]] = []
        for label, vec in pairs:
            labels.append(label)
            vectors.append(vec)
        idx = cls(labels=labels, vectors=vectors, min_k=min_k)
        idx._norms = [math.sqrt(sum(x * x for x in v)) for v in vectors]
        return idx

    def __post_init__(self) -> None:
        if self.vectors and not self._norms:
            self._norms = [math.sqrt(sum(x * x for x in v)) for v in self.vectors]

    @property
    def labels_set(self) -> frozenset[str]:
        return frozenset(self.labels)

    def rank_of(self, query: Sequence[float], winner_label: str) -> Optional[int]:
        """Return the 1-based rank of ``winner_label`` in the full similarity
        ordering, or ``None`` if the label is not in the index (uncovered).

        The ranking is the complete ordering of the universe by descending cosine
        similarity (ties broken by label for determinism). The ``MIN_K`` floor is
        applied by callers at Recall@K time, not here — ``rank_of`` reports the
        true position so K below MIN_K can still be reasoned about.
        """
        if winner_label not in self.labels_set:
            return None

        qnorm = math.sqrt(sum(x * x for x in query))
        scored: list[tuple[float, str]] = []
        for label, vec, vnorm in zip(self.labels, self.vectors, self._norms):
            if qnorm == 0.0 or vnorm == 0.0:
                sim = 0.0
            else:
                dot = sum(a * b for a, b in zip(query, vec))
                sim = dot / (qnorm * vnorm)
            scored.append((sim, label))

        # Descending similarity; deterministic tie-break by label ascending.
        scored.sort(key=lambda t: (-t[0], t[1]))
        for rank, (_sim, label) in enumerate(scored, start=1):
            if label == winner_label:
                return rank
        return None  # pragma: no cover - unreachable given membership check


# ---------------------------------------------------------------------------
# Pure recall computation (no DB session, no embedder)
# ---------------------------------------------------------------------------


def compute_recall(
    events: Sequence[WinnerEvent],
    index: TechniqueIndex,
    ks: Sequence[int] = (10, 25, 50, 100),
) -> dict:
    """Compute Recall@K over replay ``events`` against an in-memory ``index``.

    Pure function: no DB, no network, no embedder. This is the unit-testable core.

    Recall@K semantics
    ------------------
    An event "hits" at K iff its winner_label is in the top-K of the similarity
    ranking. The effective K is ``max(K, index.min_k)`` — the retriever's MIN_K
    floor (a caller asking for K<MIN_K still receives MIN_K candidates, so the
    winner is retrieved iff its rank <= MIN_K). Uncovered winners (no profile in
    the index) can never hit at any K, but stay in the denominator: they cap
    achievable recall and are reported separately so the number stays honest.

    Returns a dict — see module docstring / render_report for the shape.
    """
    ks = tuple(int(k) for k in ks)
    n_events = len(events)

    # rank_of -> None means uncovered (winner has no profile in the universe).
    ranks: list[Optional[int]] = [
        index.rank_of(ev.query_embedding, ev.winner_label) for ev in events
    ]
    uncovered_idx = [i for i, r in enumerate(ranks) if r is None]
    n_uncovered = len(uncovered_idx)

    def _hit(rank: Optional[int], k: int) -> bool:
        if rank is None:
            return False
        return rank <= max(k, index.min_k)

    overall: dict[int, dict] = {}
    for k in ks:
        hits = sum(1 for r in ranks if _hit(r, k))
        overall[k] = {
            "hits": hits,
            "n": n_events,
            "recall": (hits / n_events) if n_events else 0.0,
        }

    # Per-target (vendor/family) breakdown.
    by_target: dict[tuple[str, str], list[Optional[int]]] = defaultdict(list)
    for ev, r in zip(events, ranks):
        by_target[(ev.vendor, ev.family)].append(r)

    per_target: list[dict] = []
    for (vendor, fam), grp_ranks in sorted(by_target.items()):
        grp_n = len(grp_ranks)
        grp_uncovered = sum(1 for r in grp_ranks if r is None)
        recalls = {
            k: {
                "hits": sum(1 for r in grp_ranks if _hit(r, k)),
                "n": grp_n,
                "recall": (
                    sum(1 for r in grp_ranks if _hit(r, k)) / grp_n if grp_n else 0.0
                ),
            }
            for k in ks
        }
        per_target.append(
            {
                "vendor": vendor,
                "family": family_label(fam),
                "n_events": grp_n,
                "uncovered": grp_uncovered,
                "recall_at_k": recalls,
            }
        )

    return {
        "ks": list(ks),
        "min_k": index.min_k,
        "n_events": n_events,
        "n_techniques": len(index.labels),
        "uncovered": {
            "count": n_uncovered,
            "labels": sorted(
                {events[i].winner_label for i in uncovered_idx}
            ),
            "note": (
                "winner_label has no TechniqueProfile in the universe; cannot be "
                "retrieved at any K. Counted in the denominator (caps achievable "
                "recall), not dropped."
            ),
        },
        "overall_recall_at_k": overall,
        "per_target": per_target,
    }


def family_label(fam: str) -> str:
    """Identity helper kept tiny so per-target rows stay greppable/stable."""
    return fam


# ---------------------------------------------------------------------------
# DB-backed driver: build universe + events, then call the pure core
# ---------------------------------------------------------------------------


def _build_index(
    session: "Session",
    embed_fn: EmbedFn,
    *,
    min_k: int,
) -> tuple[TechniqueIndex, int]:
    """Embed every technique profile into an in-memory index.

    Returns ``(index, n_profiles)``. Lazily imports the sibling-owned profile
    builder and embedding-text builder so this module imports cleanly while
    parallel siblings are still landing their files.
    """
    from rogue.retrieval.embedding_text import build_technique_embedding_text
    from rogue.retrieval.technique_profile_builder import build_technique_profiles

    profiles: Sequence["TechniqueProfile"] = build_technique_profiles(session)
    pairs: list[tuple[str, list[float]]] = []
    for profile in profiles:
        text = build_technique_embedding_text(profile)
        pairs.append((profile.label, embed_fn(text)))
    return TechniqueIndex.from_pairs(pairs, min_k=min_k), len(profiles)


def _load_winner_events(
    session: "Session",
    embed_fn: EmbedFn,
    *,
    suppress_known_successes: bool,
) -> list[WinnerEvent]:
    """Pull winner rows from ``ladder_attempts`` and embed each target fingerprint.

    One event per winner row: ``target_key`` = ``config_id`` (the target_model
    misnomer), ``winner_label`` = ``entity_id``. vendor/family come from the
    denormalised columns when present, else are derived from the model string.
    """
    from sqlalchemy import select, true

    from rogue.db.models import LadderAttempt
    from rogue.retrieval.embedding_text import build_target_embedding_text
    from rogue.retrieval.target_fingerprint import build_target_fingerprint

    stmt = (
        select(
            LadderAttempt.parent_id,
            LadderAttempt.config_id,
            LadderAttempt.entity_id,
            LadderAttempt.target_vendor,
            LadderAttempt.target_family,
        )
        .where(LadderAttempt.is_winner == true())
        .where(LadderAttempt.config_id.is_not(None))
    )
    rows = session.execute(stmt).all()

    # Cache one fingerprint embedding per distinct target_key (many wins share a
    # target — re-embedding identical text is wasteful and changes nothing).
    fp_cache: dict[str, tuple[list[float], str, str]] = {}
    events: list[WinnerEvent] = []
    for parent_id, config_id, entity_id, vendor_col, family_col in rows:
        target_key = config_id
        if target_key not in fp_cache:
            fp = build_target_fingerprint(target_key, session=session)
            if suppress_known_successes:
                # Strip telemetry leakage: the winner can appear here.
                fp = fp.model_copy(update={"known_successes": []})
            text = build_target_embedding_text(fp)
            fp_cache[target_key] = (embed_fn(text), fp.vendor, fp.model_family)
        emb, fp_vendor, fp_family = fp_cache[target_key]
        vendor = vendor_col or fp_vendor
        family = family_col or fp_family
        events.append(
            WinnerEvent(
                parent_id=parent_id,
                target_key=target_key,
                winner_label=entity_id,
                vendor=vendor,
                family=family,
                query_embedding=emb,
            )
        )
    return events


def evaluate_recall(
    session: "Session",
    *,
    embed_fn: EmbedFn,
    ks: Sequence[int] = (10, 25, 50, 100),
    suppress_known_successes: bool = True,
) -> dict:
    """Replay historical ladder wins and measure Recall@K of the retriever.

    Parameters
    ----------
    session:
        SQLAlchemy session over the telemetry DB (``ladder_attempts`` + the
        technique universe source).
    embed_fn:
        Embedding callable. Pass ``deterministic_embed_fn()`` for the offline,
        no-spend default; ``default_embed_fn()`` for live OpenAI embeddings.
    ks:
        K values to report Recall@K for.
    suppress_known_successes:
        When True (default), strip ``known_successes`` from each target
        fingerprint before embedding so the winner cannot leak into the query
        text. Set False to measure the deployed-as-is (mildly optimistic) number.

    Returns
    -------
    dict
        Adds ``meta`` (embedder mode + leakage-suppression flag) to the
        :func:`compute_recall` result. See :func:`render_report` for the shape.
    """
    min_k = _resolve_min_k()
    index, n_profiles = _build_index(session, embed_fn, min_k=min_k)
    events = _load_winner_events(
        session, embed_fn, suppress_known_successes=suppress_known_successes
    )
    result = compute_recall(events, index, ks=ks)
    result["meta"] = {
        "n_profiles": n_profiles,
        "suppress_known_successes": suppress_known_successes,
        "embedder": getattr(embed_fn, "__qualname__", repr(embed_fn)),
    }
    return result


def _resolve_min_k() -> int:
    """Use the retriever's MIN_K when its module is importable; else the fallback."""
    try:
        from rogue.retrieval.retriever import TechniqueRetriever

        return int(TechniqueRetriever.MIN_K)
    except Exception:
        return _DEFAULT_MIN_K


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render_report(result: dict) -> str:
    """Render an :func:`evaluate_recall` / :func:`compute_recall` dict as markdown."""
    ks = result.get("ks", [])
    lines: list[str] = []
    lines.append("# Retrieval Recall@K — historical ladder replay")
    lines.append("")

    meta = result.get("meta")
    n_events = result.get("n_events", 0)
    n_tech = result.get("n_techniques", 0)
    lines.append(f"- events (winner rows replayed): **{n_events}**")
    lines.append(f"- technique universe size: **{n_tech}**")
    lines.append(f"- MIN_K floor: **{result.get('min_k')}**")
    if meta:
        lines.append(f"- embedder: `{meta.get('embedder')}`")
        lines.append(
            f"- known_successes suppressed (anti-leakage): "
            f"**{meta.get('suppress_known_successes')}**"
        )

    unc = result.get("uncovered", {})
    unc_count = unc.get("count", 0)
    unc_pct = (unc_count / n_events * 100.0) if n_events else 0.0
    lines.append("")
    lines.append(
        f"- **uncovered winners** (no profile in universe — caps recall): "
        f"**{unc_count}** ({unc_pct:.1f}% of events)"
    )
    if unc.get("labels"):
        shown = unc["labels"][:10]
        more = "" if len(unc["labels"]) <= 10 else f" … (+{len(unc['labels']) - 10} more)"
        lines.append(f"  - labels: {', '.join(shown)}{more}")

    # Overall table.
    lines.append("")
    lines.append("## Overall Recall@K")
    lines.append("")
    header = "| metric | " + " | ".join(f"@{k}" for k in ks) + " |"
    sep = "|---|" + "|".join("---" for _ in ks) + "|"
    lines.append(header)
    lines.append(sep)
    overall = result.get("overall_recall_at_k", {})
    rec_cells = []
    hit_cells = []
    for k in ks:
        entry = overall.get(k) or overall.get(str(k)) or {}
        rec_cells.append(f"{entry.get('recall', 0.0) * 100:.1f}%")
        hit_cells.append(f"{entry.get('hits', 0)}/{entry.get('n', n_events)}")
    lines.append("| recall | " + " | ".join(rec_cells) + " |")
    lines.append("| hits   | " + " | ".join(hit_cells) + " |")

    # Gate line: Recall@50 >= 80%.
    gate_entry = overall.get(50) or overall.get("50")
    if gate_entry is not None:
        r50 = gate_entry.get("recall", 0.0)
        verdict = "PASS" if r50 >= 0.80 else "FAIL"
        lines.append("")
        lines.append(
            f"**Deployment gate — Recall@50 >= 80%: {verdict}** "
            f"(measured {r50 * 100:.1f}%)"
        )

    # Per-target breakdown.
    per_target = result.get("per_target", [])
    if per_target:
        lines.append("")
        lines.append("## Per-target (vendor / family)")
        lines.append("")
        thead = "| vendor | family | n | uncovered | " + " | ".join(
            f"R@{k}" for k in ks
        ) + " |"
        tsep = "|---|---|---|---|" + "|".join("---" for _ in ks) + "|"
        lines.append(thead)
        lines.append(tsep)
        for row in per_target:
            rk = row.get("recall_at_k", {})
            cells = []
            for k in ks:
                entry = rk.get(k) or rk.get(str(k)) or {}
                cells.append(f"{entry.get('recall', 0.0) * 100:.0f}%")
            lines.append(
                f"| {row.get('vendor')} | {row.get('family')} | "
                f"{row.get('n_events')} | {row.get('uncovered')} | "
                + " | ".join(cells)
                + " |"
            )

    return "\n".join(lines)
