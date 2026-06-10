"""Combination-risk graph (Surface 3, Section F) — ADR-0009: Postgres adjacency +
recursive CTE, NOT a graph DB.

**Why a graph.** Risk in a shared skill pool is *combinatorial*: two individually
benign skills can compose into malicious behavior, and inference injects the top-k
skills *together*. You cannot brute-force every pair at pool scale — so the pool is
modelled as a graph over ``skill_edges`` (build 08 §7), high-risk neighborhoods /
connected components are surfaced, and co-invocation is simulated *within* them.
"Risk percolates once the pool is connected; high-risk skills form one giant
component" (SkillProbe) — :meth:`CombinationGraph.giant_component` /
:meth:`CombinationGraph.high_risk_neighborhood` surface exactly that.

**Two backends behind one interface.** The graph queries (neighborhood / k-hop
blast-radius / connected components) are implemented twice, deliberately, so the
production path and the offline/test path produce *identical* results:

- :class:`PostgresGraph` — the production path (ADR-0009): a ``WITH RECURSIVE`` CTE
  over ``skill_edges``, traversing both endpoints (the table indexes ``skill_a`` and
  ``skill_b`` for exactly this). No graph DB, no new datastore.
- :class:`UnionFindGraph` — the offline-testable fallback + the documented escape
  for environments without Postgres: an app-side BFS (k-hop) over an in-memory edge
  set and a union-find for connected components. Same results as the CTE on the same
  edges (the EXIT-GATE-F check asserts this agreement).

Both implement the :class:`GraphBackend` protocol; :class:`CombinationGraph` is the
single facade callers use, plus the co-invocation simulation
(:meth:`CombinationGraph.simulate_co_invocation`).

**Co-invocation simulation = consummation, not theory** (build 08 §7, spec §4). Two
skills that *could* theoretically combine are NOT a breach. Only a *produced* harmful
composition is: the candidate top-k skill SET is co-injected and run via the
injectable :class:`CoInvocationRunner` (the real scan-engine seam, wired later — here
an offline fake), the output is scored by the harmful-composition judge, and ONLY if
the judge says the set produced harmful behavior do we (a) write a
``skill_edges(edge_type=composition, risk_score, evidence_breach_id)`` edge and
(b) **quarantine the neighborhood** (the connected set flips ``status → quarantined``).
A benign set writes nothing and quarantines nothing.

**ADR-0009 perf guard.** Recursive-CTE traversals are CTE-bound; :func:`graph_query_stats`
exposes the measured p95 so the escape hatch can be triggered on data, not preempted.
The concrete reversal trigger (build 08 §7 / the risk register): **p95 graph-query
latency > ~500 ms, or a connected-component recompute > a few seconds, at > ~100k
edges, after indexing/materialization** — only then revisit a graph store. At
single-org / one-team v2 scale (hundreds–low-thousands of skills) this is well inside
Postgres; do NOT pre-empt it.

Import-safe: no DB and no credentials at import; SQLAlchemy is imported lazily inside
:class:`PostgresGraph` methods (mirrors ``pool.PostgresSkillStore``). The judge and
the runner are injected, so the whole module is exercisable offline with a union-find
backend, a stub judge, and a fake runner (no LLM, no creds).
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from rogue.db.models import SkillEdge, SkillEdgeType, SkillStatus

__all__ = [
    "Edge",
    "GraphBackend",
    "UnionFindGraph",
    "PostgresGraph",
    "CombinationGraph",
    "CoInvocationRunner",
    "FakeCoInvocationRunner",
    "RolloutOutput",
    "CompositionResult",
    "GraphQueryStat",
    "graph_query_stats",
    "reset_graph_query_stats",
    "ADR_0009_PERF_TRIGGER",
]


# --------------------------------------------------------------------------------------------------
# ADR-0009 perf guard — the measured escape-hatch trigger + a timing hook
# --------------------------------------------------------------------------------------------------

# The concrete, MEASURED reversal trigger for ADR-0009 (build 08 §7 + risk register):
# only revisit a graph store once recursive-CTE / component recompute latency crosses
# this AT the stated edge scale, after indexing. Do not pre-empt — single-team v2 scale
# (hundreds–low-thousands of skills) is well inside Postgres.
ADR_0009_PERF_TRIGGER = {
    "p95_query_ms": 500.0,  # p95 neighborhood/blast-radius query latency
    "component_recompute_s": 3.0,  # full connected_components recompute
    "edge_count": 100_000,  # ... only meaningful at > ~100k edges, post-index
    "note": (
        "Revisit a graph store ONLY when p95 graph-query latency > ~500 ms (or a "
        "connected-component recompute > a few seconds) at > ~100k edges, after "
        "indexing/materialization. At single-org/one-team v2 scale this is well "
        "inside Postgres; do not pre-empt (ADR-0009)."
    ),
}


@dataclass(frozen=True)
class GraphQueryStat:
    """One timed graph query — the data the ADR-0009 trigger is judged on."""

    op: str  # "neighborhood" | "blast_radius" | "connected_components"
    backend: str  # "union_find" | "postgres"
    duration_ms: float
    edge_count: int


# Process-local ring of recent query timings. Small + bounded — this is a perf hook,
# not durable telemetry; the durable audit spine is `skill_verifications` (ADR-0009).
_QUERY_STATS: list[GraphQueryStat] = []
_QUERY_STATS_MAX = 2_000


def _record_stat(op: str, backend: str, duration_ms: float, edge_count: int) -> None:
    _QUERY_STATS.append(
        GraphQueryStat(
            op=op, backend=backend, duration_ms=duration_ms, edge_count=edge_count
        )
    )
    if len(_QUERY_STATS) > _QUERY_STATS_MAX:
        del _QUERY_STATS[: len(_QUERY_STATS) - _QUERY_STATS_MAX]


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    # Nearest-rank percentile (no interpolation — small samples, plain + defensible).
    k = max(0, min(len(ordered) - 1, int(round(pct / 100.0 * (len(ordered) - 1)))))
    return ordered[k]


def graph_query_stats() -> dict[str, Any]:
    """Summarize recent graph-query timings against the ADR-0009 trigger.

    Returns per-op p50/p95/max latency (ms), the sample count, the max edge count
    observed, and ``trigger_tripped`` — True iff a query op's p95 exceeded
    ``ADR_0009_PERF_TRIGGER['p95_query_ms']`` (or component recompute exceeded its
    threshold) *while* observed edges exceeded the trigger's ``edge_count``. This is
    the data-driven signal to revisit a graph store; it does not act on its own.
    """
    by_op: dict[str, list[GraphQueryStat]] = defaultdict(list)
    for s in _QUERY_STATS:
        by_op[s.op].append(s)

    ops: dict[str, Any] = {}
    tripped = False
    for op, stats in by_op.items():
        durations = [s.duration_ms for s in stats]
        max_edges = max((s.edge_count for s in stats), default=0)
        p95 = _percentile(durations, 95.0)
        threshold = (
            ADR_0009_PERF_TRIGGER["component_recompute_s"] * 1000.0
            if op == "connected_components"
            else ADR_0009_PERF_TRIGGER["p95_query_ms"]
        )
        op_tripped = (
            p95 > threshold and max_edges > ADR_0009_PERF_TRIGGER["edge_count"]
        )
        tripped = tripped or op_tripped
        ops[op] = {
            "n": len(stats),
            "p50_ms": _percentile(durations, 50.0),
            "p95_ms": p95,
            "max_ms": max(durations) if durations else 0.0,
            "max_edge_count": max_edges,
            "threshold_ms": threshold,
            "tripped": op_tripped,
        }
    return {
        "ops": ops,
        "trigger_tripped": tripped,
        "trigger": ADR_0009_PERF_TRIGGER,
    }


def reset_graph_query_stats() -> None:
    """Clear the in-process timing ring (test isolation / a fresh measurement window)."""
    _QUERY_STATS.clear()


# --------------------------------------------------------------------------------------------------
# Graph backend seam — identical results from the recursive CTE and the union-find
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Edge:
    """An undirected combination-risk edge between two skills.

    Mirrors a ``skill_edges`` row's identity (``skill_a``, ``skill_b``, ``edge_type``)
    plus ``risk_score``. The graph is treated as UNDIRECTED for neighborhood /
    component traversal (the CTE walks both endpoints; ``skill_edges`` indexes both),
    so ``(a, b)`` and ``(b, a)`` are the same adjacency.
    """

    skill_a: str
    skill_b: str
    edge_type: SkillEdgeType = SkillEdgeType.CO_INVOCATION
    risk_score: Optional[float] = None


class GraphBackend(Protocol):
    """The two-impl seam: same neighborhood / component / blast-radius results.

    Both :class:`UnionFindGraph` (app-side BFS/union-find, offline) and
    :class:`PostgresGraph` (``WITH RECURSIVE`` CTE, production per ADR-0009) implement
    this; :class:`CombinationGraph` is backend-agnostic over it. ``backend_name`` tags
    the timing stats so the two paths are distinguishable in :func:`graph_query_stats`.
    """

    backend_name: str

    def neighborhood(self, skill_id: str, k_hops: int) -> set[str]: ...

    def blast_radius(self, skill_id: str) -> set[str]: ...

    def connected_components(self) -> list[set[str]]: ...

    def edge_count(self) -> int: ...


class UnionFindGraph:
    """App-side graph over an in-memory edge set — the offline/test backend + the
    documented ADR-0009 fallback for no-Postgres environments.

    - ``neighborhood(skill, k)`` / ``blast_radius`` — breadth-first traversal of the
      undirected adjacency (blast-radius = unbounded BFS = the whole reachable set).
    - ``connected_components`` — union-find (disjoint-set) over the edge list.

    Produces the SAME sets as :class:`PostgresGraph`'s recursive CTE on the same edges
    (asserted by EXIT-GATE F). Nodes are inferred from the edges; an isolated skill
    with no edges is not part of any edge-derived component (callers that need
    singleton components seed them explicitly).
    """

    backend_name = "union_find"

    def __init__(self, edges: Iterable[Edge] = ()) -> None:
        self._adj: dict[str, set[str]] = defaultdict(set)
        self._nodes: set[str] = set()
        self._edge_count = 0
        for e in edges:
            self.add_edge(e)

    def add_edge(self, edge: Edge) -> None:
        self._adj[edge.skill_a].add(edge.skill_b)
        self._adj[edge.skill_b].add(edge.skill_a)
        self._nodes.add(edge.skill_a)
        self._nodes.add(edge.skill_b)
        self._edge_count += 1

    def edge_count(self) -> int:
        return self._edge_count

    def neighborhood(self, skill_id: str, k_hops: int) -> set[str]:
        """Skills within ``k_hops`` of ``skill_id`` (the seed itself EXCLUDED).

        ``k_hops <= 0`` is the empty set. BFS layer-by-layer; matches the CTE's
        depth-bounded recursion (the CTE seeds at depth 0 and stops at ``k_hops``).
        """
        start = time.perf_counter()
        try:
            if k_hops <= 0 or skill_id not in self._nodes:
                return set()
            visited = {skill_id}
            frontier = {skill_id}
            for _ in range(k_hops):
                nxt: set[str] = set()
                for node in frontier:
                    for nb in self._adj.get(node, ()):
                        if nb not in visited:
                            visited.add(nb)
                            nxt.add(nb)
                frontier = nxt
                if not frontier:
                    break
            visited.discard(skill_id)
            return visited
        finally:
            _record_stat(
                "neighborhood",
                self.backend_name,
                (time.perf_counter() - start) * 1000.0,
                self._edge_count,
            )

    def blast_radius(self, skill_id: str) -> set[str]:
        """Every skill reachable from ``skill_id`` (unbounded hops), seed EXCLUDED.

        The connected component containing ``skill_id``, minus the seed — "if this
        skill is compromised, what is the reachable blast radius?".
        """
        start = time.perf_counter()
        try:
            if skill_id not in self._nodes:
                return set()
            visited = {skill_id}
            queue = deque([skill_id])
            while queue:
                node = queue.popleft()
                for nb in self._adj.get(node, ()):
                    if nb not in visited:
                        visited.add(nb)
                        queue.append(nb)
            visited.discard(skill_id)
            return visited
        finally:
            _record_stat(
                "blast_radius",
                self.backend_name,
                (time.perf_counter() - start) * 1000.0,
                self._edge_count,
            )

    def connected_components(self) -> list[set[str]]:
        """Connected components via union-find. Each is a ``set[skill_id]``.

        Sorted largest-first so ``[0]`` is the giant component (the
        risk-percolation signal). Only edge-touching nodes appear (an isolated
        skill forms no edge-derived component).
        """
        start = time.perf_counter()
        try:
            parent: dict[str, str] = {n: n for n in self._nodes}

            def find(x: str) -> str:
                root = x
                while parent[root] != root:
                    root = parent[root]
                while parent[x] != root:  # path compression
                    parent[x], x = root, parent[x]
                return root

            for a, neighbors in self._adj.items():
                for b in neighbors:
                    ra, rb = find(a), find(b)
                    if ra != rb:
                        parent[rb] = ra

            groups: dict[str, set[str]] = defaultdict(set)
            for node in self._nodes:
                groups[find(node)].add(node)
            return sorted(groups.values(), key=len, reverse=True)
        finally:
            _record_stat(
                "connected_components",
                self.backend_name,
                (time.perf_counter() - start) * 1000.0,
                self._edge_count,
            )


class PostgresGraph:
    """Production graph backend — ``WITH RECURSIVE`` CTE over ``skill_edges`` (ADR-0009).

    The neighborhood / blast-radius queries are a single recursive CTE that walks the
    UNDIRECTED adjacency by UNION-ing both directions (``skill_a→skill_b`` and
    ``skill_b→skill_a``) — which is why ``skill_edges`` indexes both endpoints. No
    graph DB, no new datastore.

    Scoping: the graph lives inside one ``(org_id, cohort_id, trust_domain)`` — edges
    only connect skills in the same scope (the simulation writes them that way). The
    CTE joins ``skills`` on both endpoints and constrains the scope so a traversal can
    never walk across a trust boundary (Section G isolation holds on the graph too).

    SQLAlchemy is imported lazily so the module imports with no DB/driver (mirrors
    ``pool.PostgresSkillStore``). ``session_factory`` is a ``sessionmaker`` (or any
    zero-arg callable returning a context-manageable ``Session``).
    """

    backend_name = "postgres"

    def __init__(
        self,
        session_factory: Callable[[], Any],
        *,
        org_id: str,
        cohort_id: str,
        trust_domain: str,
    ) -> None:
        self._session_factory = session_factory
        self._org_id = org_id
        self._cohort_id = cohort_id
        self._trust_domain = trust_domain

    # ---- scope predicate shared by every query (Section G isolation on the graph) ----

    _SCOPE_JOIN = (
        "JOIN skills sa ON sa.skill_id = e.skill_a "
        "JOIN skills sb ON sb.skill_id = e.skill_b "
        "WHERE sa.org_id = :org AND sa.cohort_id = :cohort "
        "AND sa.trust_domain = :td "
        "AND sb.org_id = :org AND sb.cohort_id = :cohort "
        "AND sb.trust_domain = :td"
    )

    def _params(self, **extra: Any) -> dict[str, Any]:
        return {
            "org": self._org_id,
            "cohort": self._cohort_id,
            "td": self._trust_domain,
            **extra,
        }

    def edge_count(self) -> int:
        from sqlalchemy import text

        sql = text(f"SELECT count(*) FROM skill_edges e {self._SCOPE_JOIN}")
        with self._session_factory() as session:
            return int(session.execute(sql, self._params()).scalar() or 0)

    def _traverse(self, skill_id: str, *, max_depth: Optional[int]) -> set[str]:
        """Recursive-CTE traversal of the undirected, scoped adjacency.

        ``max_depth=None`` = unbounded (blast radius / component). Returns the
        reachable set EXCLUDING the seed (the caller's neighborhood / blast-radius
        contract). The CTE seeds at depth 0 with ``skill_id``, then at each step
        UNIONs the neighbors found in EITHER endpoint column, bounded by ``max_depth``.
        """
        from sqlalchemy import text

        # Postgres forbids the recursive working-table reference (`reach`) inside a
        # subquery / LATERAL, so the recursive term joins `skill_edges` DIRECTLY to
        # `reach` and picks the OTHER endpoint via a CASE (the edge matches on either
        # column — the undirected walk).
        #
        # Cycle guard (CRITICAL): an undirected graph is inherently cyclic
        # (a→b at depth 1, b→a at depth 2, …). Because `depth` differs each pass,
        # `UNION` alone would NEVER converge → unbounded recursion → OOM. We carry a
        # ``path`` array of visited nodes and refuse to re-expand a node already on it
        # (``NOT node = ANY(r.path)``), so each node is expanded at most once
        # (shortest-path / BFS semantics — matches the union-find layer-by-layer BFS).
        #
        # The scope predicate constrains BOTH endpoints to the (org, cohort,
        # trust_domain) so a traversal can't cross a trust boundary (Section G holds
        # on the graph too).
        depth_guard = "" if max_depth is None else "AND r.depth < :max_depth"
        sql = text(
            f"""
            WITH RECURSIVE reach(node, depth, path) AS (
                SELECT CAST(:seed AS varchar) AS node, 0 AS depth,
                       ARRAY[CAST(:seed AS varchar)] AS path
                UNION ALL
                SELECT nxt.node, r.depth + 1, r.path || nxt.node
                FROM reach r
                JOIN skill_edges e
                    ON (e.skill_a = r.node OR e.skill_b = r.node)
                JOIN skills sa ON sa.skill_id = e.skill_a
                JOIN skills sb ON sb.skill_id = e.skill_b
                CROSS JOIN LATERAL (
                    SELECT CASE WHEN e.skill_a = r.node THEN e.skill_b
                                ELSE e.skill_a END AS node
                ) AS nxt
                WHERE sa.org_id = :org AND sa.cohort_id = :cohort
                    AND sa.trust_domain = :td
                    AND sb.org_id = :org AND sb.cohort_id = :cohort
                    AND sb.trust_domain = :td
                    AND NOT (nxt.node = ANY(r.path))
                    {depth_guard}
            )
            SELECT DISTINCT node FROM reach WHERE node <> :seed
            """
        )
        params = self._params(seed=skill_id)
        if max_depth is not None:
            params["max_depth"] = max_depth
        with self._session_factory() as session:
            rows = session.execute(sql, params).scalars().all()
        return set(rows)

    def neighborhood(self, skill_id: str, k_hops: int) -> set[str]:
        start = time.perf_counter()
        ec = 0
        try:
            if k_hops <= 0:
                return set()
            result = self._traverse(skill_id, max_depth=k_hops)
            return result
        finally:
            try:
                ec = self.edge_count()
            except Exception:  # noqa: BLE001 — timing hook must never mask the query
                ec = 0
            _record_stat(
                "neighborhood",
                self.backend_name,
                (time.perf_counter() - start) * 1000.0,
                ec,
            )

    def blast_radius(self, skill_id: str) -> set[str]:
        start = time.perf_counter()
        ec = 0
        try:
            return self._traverse(skill_id, max_depth=None)
        finally:
            try:
                ec = self.edge_count()
            except Exception:  # noqa: BLE001
                ec = 0
            _record_stat(
                "blast_radius",
                self.backend_name,
                (time.perf_counter() - start) * 1000.0,
                ec,
            )

    def connected_components(self) -> list[set[str]]:
        """Connected components over the scoped graph.

        Pulls the scoped edge list (cheap at v2 scale) and runs the same union-find as
        :class:`UnionFindGraph` — the components are a property of the adjacency, so
        computing them app-side over Postgres-sourced edges yields identical results to
        any in-DB scheme while staying ADR-0009-simple. (The ADR-0009 trigger watches
        this op's recompute time; see :func:`graph_query_stats`.)
        """
        from sqlalchemy import text

        start = time.perf_counter()
        ec = 0
        try:
            sql = text(
                f"SELECT e.skill_a, e.skill_b FROM skill_edges e {self._SCOPE_JOIN}"
            )
            with self._session_factory() as session:
                rows = session.execute(sql, self._params()).all()
            ec = len(rows)
            uf = UnionFindGraph(
                Edge(skill_a=a, skill_b=b) for a, b in rows
            )
            # Pop the union-find's own component timing so only the postgres op is
            # recorded for this call (avoid double-counting the same work).
            components = uf.connected_components()
            if _QUERY_STATS and _QUERY_STATS[-1].backend == "union_find":
                _QUERY_STATS.pop()
            return components
        finally:
            _record_stat(
                "connected_components",
                self.backend_name,
                (time.perf_counter() - start) * 1000.0,
                ec,
            )


# --------------------------------------------------------------------------------------------------
# Co-invocation runner seam — abstracts the real scan engine (wired later)
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RolloutOutput:
    """The output of running the agent with a co-injected skill SET.

    The thin contract :class:`CoInvocationRunner` returns and the judge scores.
    ``scan_run_id`` ties the rollout back to a scan run when the real engine is wired
    (``skill_edges.evidence_breach_id`` is set from ``breach_id`` on a composition
    breach; ``skill_verifications.scan_run_id`` records the rollout).
    """

    output: str
    scan_run_id: Optional[str] = None
    breach_id: Optional[str] = None


class CoInvocationRunner(Protocol):
    """The injectable rollout seam — abstracts ``platform.scan_service`` (ADR-0009).

    The real implementation runs the agent over the scan engine with the candidate
    top-k skill SET co-injected (a scan job; ``DefaultScanService`` + ``worker``/
    ``queue``). Here it is a Protocol so :meth:`CombinationGraph.simulate_co_invocation`
    is exercisable offline with :class:`FakeCoInvocationRunner` — no real engine, no
    creds, no LLM. The real runner is wired later behind this same seam.
    """

    def run(self, skill_set: list[str], *, task: str) -> RolloutOutput: ...


class FakeCoInvocationRunner:
    """Offline rollout runner — returns canned outputs keyed by the (sorted) skill set.

    For tests/demo: pass ``outputs`` mapping a frozenset of skill_ids → the
    :class:`RolloutOutput` the "agent" produced when that set was co-injected. An
    unmapped set yields a benign empty rollout (no composition). This is the fake the
    EXIT-GATE-F check drives — the real scan-engine runner replaces it behind
    :class:`CoInvocationRunner`.
    """

    def __init__(
        self,
        outputs: Optional[dict[frozenset[str], RolloutOutput]] = None,
        *,
        default: Optional[RolloutOutput] = None,
    ) -> None:
        self._outputs = outputs or {}
        self._default = default or RolloutOutput(output="")
        self.calls: list[list[str]] = []

    def run(self, skill_set: list[str], *, task: str) -> RolloutOutput:
        self.calls.append(list(skill_set))
        return self._outputs.get(frozenset(skill_set), self._default)


# --------------------------------------------------------------------------------------------------
# CompositionResult — the outcome of one co-invocation simulation
# --------------------------------------------------------------------------------------------------


@dataclass
class CompositionResult:
    """Outcome of one :meth:`CombinationGraph.simulate_co_invocation`.

    ``is_breach`` is the consummation verdict: the co-injected SET *produced* harmful
    behavior (build 08 §7 / spec §4), not "could theoretically combine". On a breach,
    ``edge`` is the written ``composition`` edge and ``quarantined`` is the connected
    set flipped to ``status=quarantined``; on a benign set both are empty/None.
    """

    skill_set: list[str]
    is_breach: bool
    risk_score: Optional[float] = None
    rationale: str = ""
    evidence_breach_id: Optional[str] = None
    scan_run_id: Optional[str] = None
    edge: Optional[Edge] = None
    quarantined: set[str] = field(default_factory=set)


# --------------------------------------------------------------------------------------------------
# The facade — graph queries + co-invocation simulation + neighborhood quarantine
# --------------------------------------------------------------------------------------------------


def _new_verification_id() -> str:
    return f"skv_{uuid.uuid4().hex[:20]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CombinationGraph:
    """Section-F facade: graph queries (over either backend) + co-invocation simulation.

    Args:
        backend: a :class:`GraphBackend` — :class:`UnionFindGraph` (offline/fallback)
            or :class:`PostgresGraph` (production CTE). The query methods delegate to
            it unchanged, so the same call site works on both paths.
        edge_writer: callable persisting a :class:`Edge` as a ``skill_edges`` row on a
            composition breach (Postgres path: an ``add``-style writer over a session;
            offline: appends to a list / a :class:`UnionFindGraph`). Optional — query-
            only use needs no writer.
        quarantine_fn: callable ``set[skill_id] -> None`` flipping a connected set to
            ``status=quarantined`` (Postgres: an UPDATE; offline: mutate in-memory
            ``Skill`` rows). Optional — required only for :meth:`simulate_co_invocation`.

    The judge and runner are passed per-simulation (not held), mirroring how the
    promotion/leakage gates inject their judge per call.
    """

    def __init__(
        self,
        backend: GraphBackend,
        *,
        edge_writer: Optional[Callable[[Edge], Any]] = None,
        quarantine_fn: Optional[Callable[[set[str]], Any]] = None,
    ) -> None:
        self.backend = backend
        self._edge_writer = edge_writer
        self._quarantine_fn = quarantine_fn

    # ---- graph queries (delegate to the backend; identical results both ways) ----

    def neighborhood(self, skill_id: str, k_hops: int) -> set[str]:
        """Skills within ``k_hops`` of ``skill_id`` (seed excluded)."""
        return self.backend.neighborhood(skill_id, k_hops)

    def blast_radius(self, skill_id: str) -> set[str]:
        """Every skill reachable from ``skill_id`` (seed excluded) — its blast radius."""
        return self.backend.blast_radius(skill_id)

    def connected_components(self) -> list[set[str]]:
        """Connected components, largest-first (``[0]`` is the giant component)."""
        return self.backend.connected_components()

    # ---- risk-percolation signals (build 08 §7 / SkillProbe giant-component) ----

    def giant_component(self) -> set[str]:
        """The largest connected component — empty if the graph has no edges.

        "Risk percolates once the pool is connected; high-risk skills form one giant
        component" (SkillProbe): a giant component that swallows most of the pool is
        the signal that combination risk has percolated.
        """
        comps = self.connected_components()
        return comps[0] if comps else set()

    def high_risk_neighborhood(
        self, skill_id: str, *, k_hops: int = 2
    ) -> set[str]:
        """The k-hop neighborhood of a high-risk skill — its containment radius.

        The set a quarantine would span if ``skill_id`` is implicated: who composes
        (transitively, within ``k_hops``) with a skill flagged high-risk. Defaults to
        2 hops (direct co-invocation partners + their partners).
        """
        return self.neighborhood(skill_id, k_hops)

    # ---- co-invocation simulation = consummation, then quarantine the neighborhood ----

    def simulate_co_invocation(
        self,
        skill_set: list[str],
        *,
        runner: CoInvocationRunner,
        judge: Any,
        task: str = "",
        risk_score: float = 1.0,
        scope_skill_ids: Optional[set[str]] = None,
    ) -> CompositionResult:
        """Run the candidate top-k SET co-injected, score it, act ONLY on consummation.

        Steps (build 08 §7):

        1. Run the agent with the whole ``skill_set`` co-injected, via the injected
           :class:`CoInvocationRunner` (the real scan-engine seam; an offline fake in
           tests). One rollout for the SET, not per-pair.
        2. Score the rollout with ``judge`` — the harmful-composition judge (reuse the
           harm / net-effect judge from ``rogue.memory.judges`` / ``reproduce.judge``).
           The judge must expose ``grade_sync(**inputs) -> result`` and the result an
           ``is_breach: bool`` (the :class:`~rogue.memory.judges.MemoryJudge` shape).
        3. **Two benign skills that *could* combine ≠ breach.** Only if the judge says
           the SET *produced* harmful behavior (``is_breach``) do we:
           a. write a ``skill_edges(edge_type=composition, risk_score,
              evidence_breach_id)`` edge across the set (via ``edge_writer``), and
           b. **quarantine the neighborhood** — the connected set spanning ``skill_set``
              flips ``status=quarantined`` (via ``quarantine_fn``).
           A benign set writes no edge and quarantines nothing.

        Returns a :class:`CompositionResult` carrying the verdict, the written edge,
        and the quarantined set.

        ``scope_skill_ids`` optionally bounds the quarantine to a known in-scope set
        (the offline path passes the cohort's skill_ids); when omitted the quarantine
        spans the graph blast-radius of the set plus the set itself.
        """
        if len(skill_set) < 2:
            raise ValueError(
                "co-invocation simulation needs a SET of >= 2 skills "
                f"(got {skill_set!r})"
            )

        rollout = runner.run(skill_set, task=task)

        # Score the SET's output. The judge owns the consummation gate (engagement /
        # "looks risky" is NOT a breach — only produced harmful behavior is).
        result = judge.grade_sync(
            skill_set="\n---\n".join(skill_set),
            task=task,
            model_response=rollout.output,
        )
        is_breach = bool(getattr(result, "is_breach"))
        rationale = str(getattr(result, "rationale", ""))

        if not is_breach:
            # Benign composition — record nothing, quarantine nothing.
            return CompositionResult(
                skill_set=list(skill_set),
                is_breach=False,
                rationale=rationale,
                scan_run_id=rollout.scan_run_id,
            )

        # --- consummation: a produced harmful composition ---
        # One composition edge anchoring the SET. We anchor at the first two members
        # (the PK is the (a, b, edge_type) triple); the risk_score + evidence are the
        # audit payload the attestation reads.
        a, b = skill_set[0], skill_set[1]
        edge = Edge(
            skill_a=a,
            skill_b=b,
            edge_type=SkillEdgeType.COMPOSITION,
            risk_score=risk_score,
        )
        if self._edge_writer is not None:
            self._edge_writer(
                SkillEdge(
                    skill_a=a,
                    skill_b=b,
                    edge_type=SkillEdgeType.COMPOSITION,
                    risk_score=risk_score,
                    evidence_breach_id=rollout.breach_id,
                    created_at=_now(),
                )
            )

        # Quarantine the neighborhood: the connected set spanning the breaching set.
        to_quarantine: set[str] = set(skill_set)
        for sid in skill_set:
            to_quarantine |= self.blast_radius(sid)
        if scope_skill_ids is not None:
            to_quarantine &= scope_skill_ids | set(skill_set)
        if self._quarantine_fn is not None:
            self._quarantine_fn(to_quarantine)

        return CompositionResult(
            skill_set=list(skill_set),
            is_breach=True,
            risk_score=risk_score,
            rationale=rationale,
            evidence_breach_id=rollout.breach_id,
            scan_run_id=rollout.scan_run_id,
            edge=edge,
            quarantined=to_quarantine,
        )


# --------------------------------------------------------------------------------------------------
# Offline helpers for the in-memory path (edge writer + quarantine over Skill rows)
# --------------------------------------------------------------------------------------------------


def in_memory_quarantine_fn(
    skills: list[Any],
) -> Callable[[set[str]], None]:
    """Build a ``quarantine_fn`` that flips matching in-memory ``Skill`` rows to
    ``status=quarantined`` (the offline mirror of the Postgres UPDATE).

    ``skills`` is a mutable list of ``Skill`` rows (e.g. ``InMemorySkillStore.skills``);
    the returned callable sets ``status=QUARANTINED`` on every row whose ``skill_id``
    is in the quarantine set.
    """

    def _quarantine(ids: set[str]) -> None:
        for s in skills:
            if s.skill_id in ids:
                s.status = SkillStatus.QUARANTINED

    return _quarantine
