"""Serve-time hybrid-acquisition gate — Q18.

ROGUE has a fixed paid budget: given hundreds of harvested attacks and money to fire only a fraction,
which fire *first*? Today the answer is the static, config-blind ``reproducibility_score`` order (a
harvest-time self-rating). This gate replaces that with an **active-learning acquisition function** that
spends the budget on the most *informative* attacks, not just the most likely to breach.

    score(p) = w_value·value(p,c) + α·uncertainty(p,c) + β·diversity(p | already-chosen) + γ·info_gain(p,c)

Each term is a different *reason* to spend budget, and each has a home in the literature (verified from
the full papers, not the Elicit brief):

* **value** — exploitation. ``P(breach)`` from the Q7 pre-fire scorer (calibrated, config-aware). This is
  the active-*testing* term: Kossen (2103.05331) shows the optimal proposal samples ∝ the expected loss,
  and a breach *is* the loss of the target's safety. Falls back to ``reproducibility_score/10`` when no
  pre-fire artifact is present (so the gate never *requires* a trained model to be useful).

* **uncertainty** — learning. ``1 − 2·|P(breach) − 0.5|`` (peaks at P=0.5, zero at a confident 0/1). This
  is active-*learning* uncertainty sampling: Ma (1904.13195) finds the prediction-probability distance to
  the decision boundary is among the most effective test-selection signals, and it is exactly the
  acquisition the **robustness-threshold leaderboard** needs — the "breaks at N tokens" boundary sits
  where breach_prob≈0.5.

* **diversity** — coverage. ``min`` cosine distance from p's payload embedding to the attacks already
  chosen *this run* (a greedy maximal-marginal-relevance step). Kossen's tactic (b): decorrelate the
  chosen set so the budget isn't burned on thirty near-identical "ignore previous instructions" clones;
  Chung (2405.07440) names the same failure as *redundancy* in uncertainty sampling.

* **info_gain** — experimental design. ``1/(n_cell + 1)`` where ``n_cell`` is the number of prior trials
  in this attack's (family × target_model) cell — the expected reduction in that cell's breach-rate
  posterior variance from one more observation. Under-evidenced cells score higher (a first Bengali
  many-shot jailbreak teaches more than the tenth DAN variant). This is Chung's expected-information-gain
  reading (model uncertainty about the *cell*, not the single primitive) and reuses the module's own
  Beta(1,1) smoothing convention (see ``ladder_priors``).

**Honesty note (from the papers).** Kossen's LURE importance-weighting is needed only to keep an *unbiased
statistic estimate* under active selection. ROGUE's objective is discovery + learning, not an unbiased
breach-rate estimate, so we deliberately do **not** apply LURE and do **not** sample stochastically — we
sort deterministically (highest acquisition first) so the canonical/discovery reproducibility contract
(§10.3) holds: the same corpus + telemetry snapshot always yields the same fire order.

**Modality gate.** All four terms score *whether* an attack is worth firing; none of them notices that an
image/audio attack against a text-only target fires **zero trials** (it modality-skips at dispatch). Under a
budget cap that is a silent waste — the acquisition order can spend the whole budget on multimodal primitives
a text target can't read. So the gate sinks any modality-incompatible primitive below every compatible one
(``ROGUE_ACQ_MODALITY_GATE`` on by default). It is **per-config** — the same image primitive is untouched
against a vision target — and **ordering-only**: nothing is dropped (the sunk primitives simply fall past the
cap), so the "never drops a cell" contract holds and a text-only corpus is byte-for-byte unchanged.

**Composition.** ``value`` is Q7's calibrated probability; ``uncertainty`` is a transform of the same
probability (exploit vs explore — the same number, opposite goals); Q11's survival predictor is a *sibling*
acquisition signal (near-death configs) that a caller can run first. The gate is off by default
(``ROGUE_ACQUISITION_ORDER`` unset) → today's ``reproducibility_score`` order is byte-for-byte unchanged.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rogue.reproduce.config_features import derive_config_features
from rogue.reproduce.prefire.features import build_prefire_features
from rogue.reproduce.prefire.model import PrefirePredictor
from rogue.reproduce.survival.features import is_novel_family
from rogue.reproduce.survival.train import DEFAULT_MIN_SUPPORT
from rogue.retrieval.embed import EmbedFn
from rogue.schemas import AttackPrimitive, AttackVector, DeploymentConfig

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_log = logging.getLogger(__name__)

ENV_ORDER = "ROGUE_ACQUISITION_ORDER"        # off (default) | on
ENV_MODEL = "ROGUE_ACQUISITION_MODEL"        # path to a PrefirePredictor json (defaults to the Q7 model)
ENV_W_VALUE = "ROGUE_ACQ_W_VALUE"            # exploitation weight
ENV_ALPHA = "ROGUE_ACQ_ALPHA"                # uncertainty weight
ENV_BETA = "ROGUE_ACQ_BETA"                  # diversity weight
ENV_GAMMA = "ROGUE_ACQ_GAMMA"                # info-gain weight
ENV_MIN_SUPPORT = "ROGUE_ACQ_MIN_SUPPORT"    # drift-guard: below this family support, force-keep
ENV_EMBED = "ROGUE_ACQ_EMBED"               # on (default) | off — compute serve-time embeddings for diversity
ENV_MODALITY_GATE = "ROGUE_ACQ_MODALITY_GATE"  # on (default) | off — sink modality-incompatible primitives

# Default weights are on comparable [0,1] scales and sum to 1.0 — mirroring the report's worked example
# (0.6 value / 0.25 uncertainty / 0.10 diversity / 0.05 info-gain). Not asserted convex: additive weights
# are legitimate here and a caller may push exploration up (raise α) for a robustness-leaderboard run.
DEFAULT_W_VALUE = 0.60
DEFAULT_ALPHA = 0.25
DEFAULT_BETA = 0.10
DEFAULT_GAMMA = 0.05

# The Q7 pre-fire model doubles as the acquisition value/uncertainty source — no separate artifact to train.
DEFAULT_MODEL_PATH = "data/models/prefire_scorer.json"

# A modality-incompatible primitive (an image/audio attack against a target that can't read that modality)
# fires ZERO trials — it modality-skips at dispatch (``TargetPanel.modality_skip_reason``), so spending paid
# budget on it is pure waste. When the modality gate is on the gate sinks such a primitive below every
# compatible one. This constant dominates every [0,1]-scaled term AND the ≤β diversity add, so incompatible
# items sort strictly last while preserving their relative order among themselves.
_MODALITY_PENALTY = 1.0e6


def _modality_compatible(p: AttackPrimitive, config: DeploymentConfig) -> bool:
    """False iff ``p`` requires an input modality the target can't consume (would modality-skip at fire).

    The raw-primitive (pre-render) analogue of ``TargetPanel.modality_skip_reason``: a MULTIMODAL_IMAGE /
    MULTIMODAL_AUDIO vector — or a ``requires_multimodal`` primitive whose specific modality the vector
    doesn't pin — against a target whose ``model_specs`` say it can't read that modality dispatches no
    trials, so it can neither breach nor teach. Text / multi-turn primitives are always compatible."""
    from rogue.adapters import model_specs  # noqa: PLC0415 — local import keeps gate module import cheap

    tm = config.target_model
    if p.vector == AttackVector.MULTIMODAL_IMAGE:
        return model_specs.supports_image(tm)
    if p.vector == AttackVector.MULTIMODAL_AUDIO:
        return model_specs.supports_audio(tm)
    if p.requires_multimodal:  # modality not pinned by the vector — compatible if the target reads either
        return model_specs.supports_image(tm) or model_specs.supports_audio(tm)
    return True


@dataclass
class AcquisitionScore:
    """The per-primitive acquisition breakdown — inspectable telemetry, never a silent black box."""

    primitive: AttackPrimitive
    p_breach: float          # the Q7 calibrated probability (or reproducibility_score/10 fallback)
    value: float             # w-scaled exploitation contribution's raw term (== p_breach)
    uncertainty: float       # 1 - 2*|p_breach - 0.5|
    info_gain: float         # 1/(n_cell + 1)
    diversity: float         # min cosine distance to the already-chosen set (filled at selection time)
    total: float             # the full weighted acquisition score at the moment it was chosen
    forced: bool             # drift-guard force-keep (novel/low-support family) — never deferred by a cap
    forced_reason: str       # "" | "novel_family" | "low_support"
    orig_index: int
    compatible: bool = True  # modality-compatible with the target (else sunk below the budget by the gate)


@dataclass
class AcquisitionPlan:
    """The gate's decision for one scan: a full acquisition-ranked order + an optional budget selection."""

    ordered: list[AttackPrimitive]                  # every input, acquisition-ranked (greedy order)
    selected: list[AttackPrimitive]                 # the subset to fire (== ordered when no cap)
    scores: list[AcquisitionScore] = field(default_factory=list)
    deferred: list[AttackPrimitive] = field(default_factory=list)  # dropped by the budget cap
    enabled: bool = True

    def summary(self) -> str:
        forced = sum(1 for s in self.scores if s.forced)
        incompatible = sum(1 for s in self.scores if not s.compatible)
        return (
            f"acquisition gate: ranked {len(self.ordered)} attacks, firing {len(self.selected)} "
            f"({forced} force-kept by drift-guard, {incompatible} modality-sunk, "
            f"{len(self.deferred)} deferred)"
        )


def _unit_matrix(embeddings: list[list[float] | None], dim_hint: int | None = None):
    """Stack embeddings into an L2-normalised numpy matrix; a missing/degenerate row becomes all-zeros so
    its cosine similarity to anything is 0 (i.e. treated as maximally diverse / never a near-duplicate)."""
    import numpy as np  # noqa: PLC0415 — local import keeps module import cheap + dependency explicit

    dim = dim_hint
    for e in embeddings:
        if e:
            dim = len(e)
            break
    if dim is None:  # no embeddings at all
        return np.zeros((len(embeddings), 1), dtype=np.float64)
    m = np.zeros((len(embeddings), dim), dtype=np.float64)
    for i, e in enumerate(embeddings):
        if e and len(e) == dim:
            v = np.asarray(e, dtype=np.float64)
            n = float(np.linalg.norm(v))
            if n > 0.0:
                m[i] = v / n
    return m


def _greedy_order(static: "list[float]", unit: "object", beta: float) -> tuple[list[int], list[float]]:
    """Greedy maximal-marginal-relevance ordering (Kossen tactic b / Chung redundancy fix).

    ``static[j]`` is the selection-independent part of the acquisition score (w·value + α·unc + γ·infogain);
    ``unit`` is the L2-normalised embedding matrix (rows may be all-zero when an embedding is missing).
    Repeatedly picks argmax(static + β·diversity) where diversity = 1 − max cosine similarity to the
    already-chosen set, updated **incrementally** (one matrix-vector product per pick) so the whole loop is
    O(n²·d) with numpy, not O(n³·d). Returns ``(order, diversity_at_pick)`` — the diversity each item had
    at the moment it was chosen (for telemetry). numpy's argmax breaks ties by lowest index, so equal
    scores preserve the caller's order (the reproducibility contract)."""
    import numpy as np  # noqa: PLC0415

    n = len(static)
    s = np.asarray(static, dtype=np.float64)
    best_sim = np.zeros(n, dtype=np.float64)   # max cosine sim of each item to any chosen item
    chosen = np.zeros(n, dtype=bool)
    order: list[int] = []
    div_at_pick: list[float] = []
    for _ in range(n):
        div = 1.0 - best_sim
        total = s + beta * div
        total[chosen] = -np.inf
        j = int(np.argmax(total))            # first max ⇒ lowest-index tiebreak ⇒ stable/reproducible
        order.append(j)
        div_at_pick.append(float(div[j]))
        chosen[j] = True
        row = unit[j]
        if row.any():                        # a chosen item with an embedding tightens neighbours' diversity
            sims = unit @ row                # cosine (rows are unit-norm); zero rows contribute 0
            best_sim = np.maximum(best_sim, sims)
    return order, div_at_pick


@dataclass
class AcquisitionGate:
    """Holds the acquisition signals + weights and turns (primitives, config) into a firing plan.

    ``predictor`` supplies value + uncertainty; when ``None`` the gate degrades to
    ``reproducibility_score/10`` for value and a zero uncertainty term (still a working diversity +
    info-gain ordering). ``embed_fn`` supplies diversity; ``None`` disables the diversity term.
    ``cell_evidence`` maps ``(target_model, family) → (breaches, trials)`` for info-gain (the key order
    ``contextual_breach_rates`` emits); an empty map makes info-gain a constant (neutral — every cell
    equally under-evidenced), which is the honest behaviour when no telemetry is passed (e.g. a stateless
    SDK scan). ``modality_gate`` (on by default) sinks a primitive whose required modality the target
    can't read below every compatible one, so a budget cap isn't spent on cells that would only
    modality-skip; it is per-config (the same image primitive vs a vision target is untouched).
    """

    predictor: PrefirePredictor | None = None
    embed_fn: EmbedFn | None = None
    cell_evidence: dict[tuple[str, str], tuple[int, int]] = field(default_factory=dict)
    w_value: float = DEFAULT_W_VALUE
    alpha: float = DEFAULT_ALPHA
    beta: float = DEFAULT_BETA
    gamma: float = DEFAULT_GAMMA
    min_support: int = DEFAULT_MIN_SUPPORT
    modality_gate: bool = True
    enabled: bool = True
    _embed_warned: bool = False

    # --- per-primitive term computation -------------------------------------------------------------
    def _embed(self, p: AttackPrimitive) -> list[float] | None:
        if self.embed_fn is None:
            return None
        try:
            return self.embed_fn(p.payload_template or " ")
        except Exception as e:  # noqa: BLE001 — embeddings unreachable must degrade, never abort a scan
            if not self._embed_warned:
                _log.warning("acquisition: embedding unavailable (%s) — diversity term off", e)
                self._embed_warned = True
            return None

    def _p_breach(
        self, p: AttackPrimitive, config: DeploymentConfig, emb: list[float] | None, cf: object,
    ) -> float:
        """Calibrated P(breach) from the Q7 predictor, or a reproducibility_score fallback (no artifact)."""
        if self.predictor is None:
            return max(0.0, min(1.0, (p.reproducibility_score or 0) / 10.0))
        feats = build_prefire_features(p, config, emb, self.predictor.affinity, config_features=cf)
        return float(self.predictor.score_one(feats))

    def _info_gain(self, p: AttackPrimitive, config: DeploymentConfig) -> float:
        """Inverse-support (low-support / exploration) bonus for this cell = 1/(n_cell + 1).

        NOT expected information gain — it is an inverse *sampling frequency*, a cheap monotone proxy for
        EIG (true EIG would be the Beta-posterior entropy reduction, a strictly larger computation). Method
        name kept ``_info_gain`` for the intent; the doc/glossary call it the support/exploration term.

        The cell key is ``(target_model, family)`` — the exact order ``ladder_priors.contextual_breach_rates``
        (and therefore ``build_cell_evidence``) produces, so the lookup actually hits. A fresh cell (no prior
        trials) → 1.0; a cell with 9 prior trials → 0.1. When ``cell_evidence`` is empty every cell reads n=0
        → a constant 1.0, so the term drops out of the ranking (neutral)."""
        cell = (config.target_model, p.family.value)
        _breaches, trials = self.cell_evidence.get(cell, (0, 0))
        return 1.0 / (trials + 1.0)

    def _forced(self, p: AttackPrimitive) -> tuple[bool, str]:
        """Drift-guard: a novel or low-support family is force-kept (never deferred by a budget cap).

        Kirch (2411.03343): probes transfer *below random* to held-out families, so we never drop an
        under-evidenced family on a model's say-so. Only meaningful when a predictor supplies
        ``family_support``; with no predictor nothing is forced (the whole set is fired in rank order)."""
        if self.predictor is None:
            return False, ""
        if is_novel_family(p):
            return True, "novel_family"
        support = self.predictor.family_support.get(p.family.value, 0)
        if support < self.min_support:
            return True, "low_support"
        return False, ""

    # --- the ranking itself -------------------------------------------------------------------------
    def _static_terms(
        self, primitives: list[AttackPrimitive], config: DeploymentConfig, cf: object,
    ) -> tuple[list[list[float] | None], list[float], list[dict]]:
        """Compute the selection-independent part of the acquisition score for each primitive against one
        config: the embedding (for diversity), the static score (w·value + α·unc + γ·infogain), and the
        term breakdown. Diversity is added later by the greedy loop (it depends on prior picks)."""
        embs: list[list[float] | None] = []
        static: list[float] = []
        meta: list[dict] = []
        for i, p in enumerate(primitives):
            emb = self._embed(p)
            pb = self._p_breach(p, config, emb, cf)
            unc = 1.0 - 2.0 * abs(pb - 0.5)
            ig = self._info_gain(p, config)
            forced, reason = self._forced(p)
            compat = (not self.modality_gate) or _modality_compatible(p, config)
            base = self.w_value * pb + self.alpha * unc + self.gamma * ig
            embs.append(emb)
            # A modality-incompatible primitive would only skip against this target, so sink it below every
            # compatible one (the penalty dominates all terms + the later diversity add). Terms are still
            # recorded raw in ``meta`` for telemetry — the sinking is a scoring choice, not a silent drop.
            static.append(base if compat else base - _MODALITY_PENALTY)
            meta.append({
                "p": p, "pb": pb, "unc": unc, "ig": ig,
                "forced": forced, "reason": reason, "compat": compat, "i": i,
            })
        return embs, static, meta

    def rank(
        self,
        primitives: list[AttackPrimitive],
        config: DeploymentConfig,
        *,
        max_primitives: int | None = None,
    ) -> AcquisitionPlan:
        """Greedy maximal-marginal-relevance selection: repeatedly pick the highest-acquisition attack,
        the diversity term measured against the already-chosen set. Value/uncertainty/info-gain are static
        per primitive; diversity is updated incrementally (``_greedy_order``), so the loop is O(n²·d) with
        numpy — fine for a fired corpus of a few hundred.

        The greedy *pick order* is the fire order. A ``max_primitives`` cap defers the tail, but a
        drift-guard force-kept primitive (novel/low-support family) is never deferred."""
        cf = derive_config_features(config.target_model, base_url=getattr(config, "base_url", None))
        embs, static, meta = self._static_terms(primitives, config, cf)
        unit = _unit_matrix(embs)
        order, div_at = _greedy_order(static, unit, self.beta)

        scores: list[AcquisitionScore] = []
        for pos, j in enumerate(order):
            m = meta[j]
            div = div_at[pos]
            total = static[j] + self.beta * div
            scores.append(
                AcquisitionScore(
                    primitive=m["p"], p_breach=m["pb"], value=m["pb"], uncertainty=m["unc"],
                    info_gain=m["ig"], diversity=div, total=total,
                    forced=m["forced"], forced_reason=m["reason"], orig_index=m["i"],
                    compatible=m["compat"],
                )
            )
        ordered = [s.primitive for s in scores]

        # Budget cap: keep the top-``max_primitives`` in acquisition order, but a drift-guard force-kept
        # primitive is always selected even past the cap.
        cap = max_primitives if max_primitives is not None else len(ordered)
        selected: list[AttackPrimitive] = []
        deferred: list[AttackPrimitive] = []
        for pos, s in enumerate(scores):
            if s.forced or pos < cap:
                selected.append(s.primitive)
            else:
                deferred.append(s.primitive)

        return AcquisitionPlan(
            ordered=ordered, selected=selected, scores=scores, deferred=deferred, enabled=True,
        )

    def rank_pairs(
        self,
        pairs: list[tuple[AttackPrimitive, DeploymentConfig]],
    ) -> list[tuple[AttackPrimitive, DeploymentConfig]]:
        """Rank a flat (primitive × config) list by acquisition score — the research reproduce sweep's
        cartesian fan-out. Ordering-only (no cell is dropped): an early budget/``primitive_limit`` cutoff
        has already fired the highest-acquisition pairs.

        Diversity is measured **within each config group**, not across the whole cartesian set — firing the
        same payload against config A and config B is the *matrix we want*, not a redundancy, so
        cross-config near-duplicates are not penalised. Each config's primitives get the same 4-term greedy
        as a per-config scan; the groups are then merged by descending pick score so the globally
        best-acquisition pairs fire first."""
        # group pairs by config, preserving first-seen config order and within-config primitive order
        groups: dict[str, dict] = {}
        for p, c in pairs:
            key = getattr(c, "config_id", None) or c.target_model
            g = groups.get(key)
            if g is None:
                g = {"config": c, "prims": [], "order": len(groups)}
                groups[key] = g
            g["prims"].append(p)

        merged: list[tuple[float, int, int, tuple[AttackPrimitive, DeploymentConfig]]] = []
        sunk = 0
        for g in groups.values():
            c = g["config"]
            cf = derive_config_features(c.target_model, base_url=getattr(c, "base_url", None))
            embs, static, meta = self._static_terms(g["prims"], c, cf)
            sunk += sum(1 for m in meta if not m["compat"])
            unit = _unit_matrix(embs)
            order, div_at = _greedy_order(static, unit, self.beta)
            for pos, j in enumerate(order):
                total = static[j] + self.beta * div_at[pos]
                # sort key: acquisition score desc, then config order, then within-config pick position —
                # a deterministic global order that keeps each config's own acquisition ranking intact.
                merged.append((-total, g["order"], pos, (g["prims"][j], c)))
        merged.sort(key=lambda t: (t[0], t[1], t[2]))
        if sunk:
            _log.info(
                "acquisition sweep-order: %d/%d pairs modality-sunk below the budget (target can't read "
                "their modality)", sunk, len(pairs),
            )
        return [pair for _, _, _, pair in merged]


def _disabled_plan(primitives: list[AttackPrimitive]) -> AcquisitionPlan:
    return AcquisitionPlan(ordered=list(primitives), selected=list(primitives), enabled=False)


def build_cell_evidence(session: "Session", *, target_model: str | None = None) -> dict[tuple[str, str], tuple[int, int]]:
    """Materialise the info-gain ``(target_model, family) → (breaches, trials)`` map from ``breach_results``.

    Reuses ``ladder_priors.contextual_breach_rates`` (which already aggregates the breach matrix at exactly
    this ``(target_model, family)`` granularity) so there is one source of truth for the contextual counts —
    and the key order matches ``AcquisitionGate._info_gain``'s lookup exactly. An empty map (fresh DB / no
    session) makes info-gain neutral — the gate still orders on value + uncertainty + diversity."""
    from rogue.reproduce.ladder_priors import contextual_breach_rates  # noqa: PLC0415

    stats = contextual_breach_rates(session, target_model=target_model)
    return {key: (cs.breaches, cs.trials) for key, cs in stats.items()}


def resolve_acquisition_gate(
    *,
    predictor: PrefirePredictor | None = None,
    embed_fn: EmbedFn | None = None,
    session: "Session | None" = None,
) -> AcquisitionGate | None:
    """Build a gate from the environment, or ``None`` when acquisition ordering is off.

    Off unless ``ROGUE_ACQUISITION_ORDER`` ∈ {on,1,true}. When on it loads the Q7 pre-fire model at
    ``ROGUE_ACQUISITION_MODEL`` (default the shared ``data/models/prefire_scorer.json``) for value +
    uncertainty; a missing model is **not** fatal — the gate degrades to a ``reproducibility_score`` value
    term (still a working diversity + info-gain ordering), because acquisition composes existing artifacts
    rather than owning one. A ``session`` (when the caller has one) populates the info-gain cell counts;
    without it info-gain is neutral. Weights come from ``ROGUE_ACQ_{W_VALUE,ALPHA,BETA,GAMMA}``."""
    mode = os.environ.get(ENV_ORDER, "off").strip().lower()
    if mode not in ("on", "1", "true", "yes"):
        return None

    if predictor is None:
        path = os.environ.get(ENV_MODEL, DEFAULT_MODEL_PATH)
        if os.path.exists(path):
            try:
                predictor = PrefirePredictor.load(path)
            except Exception as e:  # noqa: BLE001 — a bad artifact must not break the scan
                _log.warning("acquisition: failed to load %r (%s) — value falls back to repro-score", path, e)
                predictor = None
        else:
            _log.info("acquisition on but no pre-fire model at %r — value uses reproducibility_score", path)

    if embed_fn is None and os.environ.get(ENV_EMBED, "on").strip().lower() in ("on", "1", "true", "yes"):
        from rogue.retrieval.embed import default_embed_fn  # noqa: PLC0415

        embed_fn = default_embed_fn()

    cell_evidence: dict[tuple[str, str], tuple[int, int]] = {}
    if session is not None:
        try:
            cell_evidence = build_cell_evidence(session)
        except Exception as e:  # noqa: BLE001 — telemetry is optional; a query failure just neutralises info-gain
            _log.warning("acquisition: could not load cell evidence (%s) — info-gain neutral", e)

    def _w(env: str, default: float) -> float:
        raw = os.environ.get(env)
        try:
            return float(raw) if raw not in (None, "") else default
        except ValueError:
            return default

    modality_gate = os.environ.get(ENV_MODALITY_GATE, "on").strip().lower() in ("on", "1", "true", "yes")

    return AcquisitionGate(
        predictor=predictor,
        embed_fn=embed_fn,
        cell_evidence=cell_evidence,
        w_value=_w(ENV_W_VALUE, DEFAULT_W_VALUE),
        alpha=_w(ENV_ALPHA, DEFAULT_ALPHA),
        beta=_w(ENV_BETA, DEFAULT_BETA),
        gamma=_w(ENV_GAMMA, DEFAULT_GAMMA),
        min_support=int(os.environ.get(ENV_MIN_SUPPORT, DEFAULT_MIN_SUPPORT)),
        modality_gate=modality_gate,
        enabled=True,
    )


def apply_acquisition_order(
    primitives: list[AttackPrimitive],
    config: DeploymentConfig,
    *,
    gate: AcquisitionGate | None = None,
    max_primitives: int | None = None,
) -> AcquisitionPlan:
    """The one call a per-config scan makes. Resolves the gate from env when not injected; returns a
    disabled plan (identity order) when acquisition ordering is off — so the caller has a single, uniform
    surface and today's ``reproducibility_score`` order is byte-identical when the flag is unset."""
    gate = gate if gate is not None else resolve_acquisition_gate()
    if gate is None or not primitives:
        return _disabled_plan(primitives)
    plan = gate.rank(primitives, config, max_primitives=max_primitives)
    _log.info("%s", plan.summary())
    return plan


def apply_acquisition_order_pairs(
    pairs: list[tuple[AttackPrimitive, DeploymentConfig]],
    *,
    gate: AcquisitionGate | None = None,
) -> tuple[list[tuple[AttackPrimitive, DeploymentConfig]], bool]:
    """Sweep-side entry: order a flat (primitive × config) list by acquisition score.

    Returns ``(ordered, enabled)``. When the gate is off (env unset) returns the input unchanged with
    ``enabled=False`` — the research sweep is byte-identical by default. Ordering-only: it never drops a
    cell (dropping would corrupt the breach matrix and the predictor's own future labels)."""
    gate = gate if gate is not None else resolve_acquisition_gate()
    if gate is None or not pairs:
        return pairs, False
    ordered = gate.rank_pairs(pairs)
    _log.info("acquisition sweep-order: %d pairs ranked by hybrid acquisition score", len(pairs))
    return ordered, True


__all__ = [
    "AcquisitionGate",
    "AcquisitionPlan",
    "AcquisitionScore",
    "resolve_acquisition_gate",
    "apply_acquisition_order",
    "apply_acquisition_order_pairs",
    "build_cell_evidence",
    "DEFAULT_MODEL_PATH",
    "ENV_ORDER",
    "ENV_MODEL",
]
