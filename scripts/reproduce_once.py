"""One-shot reproduction sweep: render attacks, fire at panel, judge, persist.

Wires Layer 4 end-to-end. Run from the repo root::

    # Subset (~$10 with Sonnet judge, 20 primitives × 5 configs × 5 trials = 500 calls):
    uv run python scripts/reproduce_once.py --primitive-limit 20

    # Full sweep (~$35 with Sonnet judge, all canonical primitives × 5 configs × 5 trials):
    uv run python scripts/reproduce_once.py

Pipeline (ROGUE_PLAN.md §3.1 LAYER 4 + §10.1-§10.4)::

    canonical AttackPrimitive ──► Instantiator.render(primitive, config)
                                           │
                                           ▼
                                  RenderedAttack
                                           │
                                           ▼
                          TargetPanel.run_attack(rendered, config, N_TRIALS)
                                           │
                                           ▼
                              list[ModelResponse]
                                           │
                                           ▼
                          JudgeAgent.judge(rendered, response, primitive)
                                           │
                                           ▼
                                 JudgeResult
                                           │
                                           ▼
                          BreachResult row × N_TRIALS
                                           │
                                           ▼
                              session.add + commit

Selection: by default reproduces every ``canonical=True`` primitive from the
DB. ``--primitive-limit N`` picks the top N by ``reproducibility_score``
(biases toward attacks the LLM thought were most concretely reproducible —
the right bias for a budget-bounded first sweep).

Failure handling: per-trial errors on EITHER the target call OR the judge
call surface as a synthesized ``JudgeVerdict.ERROR`` row so the breach
matrix still has a cell for every (primitive × config × trial) — cleaner
than dropping trials silently. Target-model errors are already converted
to ``ModelResponse(error=...)`` upstream by ``TargetPanel``.

Concurrency: ``asyncio.Semaphore(N)`` caps the outer (primitive × config)
fan-out so we don't cascade-429 the target providers. Default cap is 5
concurrent pairs — each pair internally fans out ``n_trials`` calls via
``asyncio.gather`` per ``target_panel.py::run_attack``.

Env vars required: ``DATABASE_URL`` (defaults to docker-compose dev URL),
``ANTHROPIC_API_KEY`` (judge + Anthropic panel slot), ``OPENAI_API_KEY``
(OpenAI panel slot), ``OPENROUTER_API_KEY`` (Mistral + Google + Llama).
Loaded automatically via ``python-dotenv`` from ``.env`` at the repo root.

**Order-matters DB warning**: same as ``harvest_once.py`` — if you ran
``uv run pytest`` recently, run ``uv run alembic upgrade head`` BEFORE
this script. The preflight check catches it fast either way.

Spec: ROGUE_PLAN.md §A.13, §10.1-§10.4.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import ulid
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import create_engine, inspect, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from rogue.db.models import (  # noqa: E402
    AttackPrimitive as AttackPrimitiveORM,
    BreachResult as BreachResultORM,
    DeploymentConfig as DeploymentConfigORM,
    PairRefinementStep as PairRefinementStepORM,
)
from rogue.reproduce.coj import COJ_OPERATIONS  # noqa: E402
from rogue.reproduce.escalation_planner import EscalationPlanner  # noqa: E402
from rogue.reproduce.instantiator import RenderedAttack, render  # noqa: E402
from rogue.reproduce.iterative_attacker import (  # noqa: E402
    BudgetExceededError,
    DailyBudgetExceededError,
    IterativeAttacker,
)
from rogue.reproduce.judge import JudgeAgent, JudgeResult  # noqa: E402
from rogue.reproduce.pair_orchestrator import (  # noqa: E402
    PairCellResult,
    PairOrchestrator,
    build_step_orm_rows,
    new_breach_id,
)
from rogue.reproduce.persona_wrap import PersonaWrapper  # noqa: E402
from rogue.reproduce.target_panel import ModelResponse, TargetPanel  # noqa: E402
from rogue.schemas import (  # noqa: E402
    AttackFamily,
    AttackPrimitive,
    AttackVector,
    DeploymentConfig,
    JudgeVerdict,
    Severity,
)

logger = logging.getLogger("rogue.scripts.reproduce_once")

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"
)
DEFAULT_N_TRIALS = 5
DEFAULT_TEMPERATURE = 0.7
DEFAULT_CONCURRENCY = 5

# Judge-input rough estimate per call: rubric (~3K) + rendered attack
# (~1.5K) + response (~1.5K) ≈ 6K input tokens + ~300 tokens output. With
# Sonnet ($3/M in + $15/M out), per-call ≈ $0.0225.
_JUDGE_COST_ESTIMATE_PER_CALL_USD = 0.0225


@dataclass
class ReproductionRunStats:
    """Per-run telemetry — printed at end + every 10 pairs during the sweep."""

    primitives_processed: int = 0
    configs_per_primitive: int = 0
    trials_per_pair: int = 0
    breach_results_persisted: int = 0
    target_call_errors: int = 0
    judge_call_errors: int = 0
    persist_errors: int = 0
    estimated_cost_usd: float = 0.0
    verdict_counts: dict[str, int] = field(default_factory=dict)
    # §10.8 inline escalation (only when --escalate): primitives fully refused by
    # the panel that were then laddered, and how many the ladder broke.
    escalations_run: int = 0
    escalation_breaches: int = 0
    escalation_spend_usd: float = 0.0
    escalation_winners: dict[str, int] = field(default_factory=dict)

    def add_verdict(self, verdict: JudgeVerdict) -> None:
        self.verdict_counts[verdict.value] = (
            self.verdict_counts.get(verdict.value, 0) + 1
        )

    def summary_line(self) -> str:
        verdict_str = ", ".join(
            f"{k}={v}" for k, v in sorted(self.verdict_counts.items())
        )
        base = (
            f"primitives={self.primitives_processed} "
            f"configs={self.configs_per_primitive} "
            f"trials={self.trials_per_pair} "
            f"breach_results={self.breach_results_persisted} "
            f"target_errors={self.target_call_errors} "
            f"judge_errors={self.judge_call_errors} "
            f"persist_errors={self.persist_errors} "
            f"est_cost=${self.estimated_cost_usd:.2f} "
            f"verdicts=[{verdict_str}]"
        )
        if self.escalations_run:
            winners = ", ".join(
                f"{k}={v}" for k, v in sorted(self.escalation_winners.items())
            )
            base += (
                f" | escalations_run={self.escalations_run} "
                f"escalation_breaches={self.escalation_breaches} "
                f"escalation_spend=${self.escalation_spend_usd:.2f} "
                f"escalation_winners=[{winners}]"
            )
        return base


def _orm_to_pydantic_primitive(orm: AttackPrimitiveORM) -> AttackPrimitive:
    """Project an ORM AttackPrimitive into the Pydantic wire type used by
    the instantiator + judge. Field names match by design; this function
    exists mostly to centralize enum coercion + handle JSON-column defaults."""
    return AttackPrimitive.model_validate(
        {
            "primitive_id": orm.primitive_id,
            "cluster_id": orm.cluster_id,
            "canonical": orm.canonical,
            "family": (
                AttackFamily(orm.family) if isinstance(orm.family, str) else orm.family
            ),
            "secondary_families": [
                AttackFamily(f) if isinstance(f, str) else f
                for f in (orm.secondary_families or [])
            ],
            "vector": (
                AttackVector(orm.vector) if isinstance(orm.vector, str) else orm.vector
            ),
            "title": orm.title,
            "short_description": orm.short_description,
            "payload_template": orm.payload_template,
            "payload_slots": orm.payload_slots or {},
            "multi_turn_sequence": orm.multi_turn_sequence,
            "target_models_claimed": orm.target_models_claimed or [],
            "claimed_success_rate": orm.claimed_success_rate,
            "claimed_first_seen": orm.claimed_first_seen,
            "reproducibility_score": orm.reproducibility_score,
            "requires_multi_turn": orm.requires_multi_turn,
            "requires_system_prompt_access": orm.requires_system_prompt_access,
            "requires_tools": orm.requires_tools or [],
            "requires_multimodal": orm.requires_multimodal,
            "discovered_at": orm.discovered_at,
            "base_severity": (
                Severity(orm.base_severity)
                if isinstance(orm.base_severity, str)
                else orm.base_severity
            ),
            "severity_rationale": orm.severity_rationale,
            "notes": orm.notes,
            # `sources` is required to have ≥1 entry, but the reproduction
            # layer doesn't read source provenance — it only needs the
            # primitive itself to render + judge. Synth a single placeholder
            # entry referencing the primitive's own ID so the wire type
            # validates. The dashboard re-joins source_provenances directly
            # when rendering a breach card; it doesn't go through this
            # projection.
            "sources": [
                {
                    "url": f"https://rogue.internal/replay/{orm.primitive_id}",
                    "source_type": "other",
                    "author": None,
                    "published_at": None,
                    "fetched_at": orm.discovered_at,
                    "archive_hash": "replay-placeholder",
                    "bright_data_product": "fixture",
                },
            ],
        },
    )


def _orm_to_pydantic_config(orm: DeploymentConfigORM) -> DeploymentConfig:
    """Project a DeploymentConfig ORM row into the Pydantic wire type."""
    return DeploymentConfig.model_validate(
        {
            "config_id": orm.config_id,
            "customer_id": orm.customer_id,
            "name": orm.name,
            "target_model": orm.target_model,
            "system_prompt": orm.system_prompt,
            "declared_tools": orm.declared_tools or [],
            "forbidden_topics": orm.forbidden_topics or [],
        },
    )


def _build_breach_result_orm(
    *,
    primitive_id: str,
    config_id: str,
    rendered: RenderedAttack,
    response: ModelResponse,
    judge_result: JudgeResult,
) -> BreachResultORM:
    """Compose one BreachResult ORM row from (rendered, response, verdict).

    `rendered_payload` is the concatenated user-turn content of
    `rendered.messages` (system prompt excluded; it's already on
    `deployment_configs.system_prompt`). Truncated at 50K chars to keep
    row size sane.

    `persona_used` mirrors `rendered.persona_used` (set when --persona is
    passed; NULL otherwise) so the §10.7 A/B query GROUP BY persona_used
    can compare wrapped-vs-unwrapped breach rates per (primitive, config).
    """
    user_turns = [
        m["content"] for m in rendered.messages if m.get("role") == "user"
    ]
    rendered_payload = "\n\n---NEXT TURN---\n\n".join(user_turns)[:50_000]

    return BreachResultORM(
        breach_id=ulid.new().str,
        primitive_id=primitive_id,
        deployment_config_id=config_id,
        trial_index=response.trial_index,
        temperature=response.temperature,
        rendered_payload=rendered_payload,
        model_response=(response.content or "")[:50_000],
        verdict=judge_result.verdict.value,
        judge_rationale=judge_result.rationale[:2_000],
        judge_confidence=judge_result.confidence,
        latency_ms=response.latency_ms,
        tokens_in=response.tokens_in,
        tokens_out=response.tokens_out,
        cost_usd=response.cost_usd,
        ran_at=datetime.now(timezone.utc),
        persona_used=rendered.persona_used,
    )


def _assert_schema_present(database_url: str) -> None:
    """Fail-fast preflight — same pattern as ``scripts/harvest_once.py``."""
    from sqlalchemy import create_engine as _ce
    from sqlalchemy.exc import OperationalError

    try:
        engine = _ce(database_url, connect_args={"connect_timeout": 5})
        with engine.connect():
            pass
        tables = set(inspect(engine).get_table_names())
    except OperationalError as exc:
        raise RuntimeError(
            f"Postgres at {database_url!r} unreachable: {exc}. "
            "Start it with: docker compose up -d --wait"
        ) from exc
    finally:
        try:
            engine.dispose()
        except Exception:  # pragma: no cover
            pass

    required = {"attack_primitives", "deployment_configs", "breach_results"}
    missing = required - tables
    if missing:
        raise RuntimeError(
            f"Postgres at {database_url!r} missing tables {sorted(missing)}. "
            "Run: uv run alembic upgrade head"
        )


async def _run_one_pair(
    *,
    primitive: AttackPrimitive,
    config: DeploymentConfig,
    panel: TargetPanel,
    judge: JudgeAgent,
    n_trials: int,
    temperature: float,
    persona_wrapper: PersonaWrapper | None = None,
    persona_technique: str | None = None,
) -> tuple[RenderedAttack, list[tuple[ModelResponse, JudgeResult]]]:
    """Render + (optionally wrap with persona) + fire + judge for one
    (primitive, config) pair × N trials.

    When ``persona_wrapper`` and ``persona_technique`` are both set, the
    baseline render is wrapped in a PAP persuasion frame (§10.7) before
    dispatch. The returned RenderedAttack carries ``persona_used`` so
    BreachResult rows get the technique name persisted for the A/B
    comparison.

    Returns ``(rendered, [(response, verdict) × n_trials])``. Per-trial
    errors on EITHER side synthesize a ``JudgeVerdict.ERROR`` so the
    breach matrix always has a cell.
    """
    rendered = render(primitive, config)
    if persona_wrapper is not None and persona_technique is not None:
        rendered = await persona_wrapper.wrap_rendered(rendered, persona_technique)
    responses = await panel.run_attack(
        rendered=rendered,
        config=config,
        temperature=temperature,
        n_trials=n_trials,
    )

    out: list[tuple[ModelResponse, JudgeResult]] = []
    for response in responses:
        if response.error:
            verdict_result = JudgeResult(
                verdict=JudgeVerdict.ERROR,
                rationale=f"target-model error: {response.error[:1900]}",
                confidence=0.0,
            )
        else:
            try:
                verdict_result = await judge.judge(
                    rendered=rendered,
                    model_response=response.content or "",
                    primitive=primitive,
                )
            except Exception as exc:
                verdict_result = JudgeResult(
                    verdict=JudgeVerdict.ERROR,
                    rationale=(
                        f"judge-call error: {type(exc).__name__}: "
                        f"{str(exc)[:1900]}"
                    ),
                    confidence=0.0,
                )
        out.append((response, verdict_result))
    return rendered, out


def _build_pair_breach_result_orm(
    *,
    primitive_id: str,
    config_id: str,
    pair_result: PairCellResult,
    judge_confidence: float = 0.9,
) -> BreachResultORM:
    """Compose a BreachResult ORM row from a §10.7 PAIR cell outcome.

    Differs from `_build_breach_result_orm` in that:
      - rendered_payload = final iteration's payload (the refined prompt)
      - model_response = final iteration's target response
      - verdict = final iteration's verdict
      - pair_iters_to_breach + pair_attacker_total_cost_usd set from the chain
      - persona_used stays NULL — PAIR rows are identified canonically by
        pair_attacker_total_cost_usd / pair_iters_to_breach. Overloading
        persona_used made the persona A/B (`/api/persona/stats`) count PAIR
        iterations as a "persona," inflating it to a false 100% (fixed 2026-05-28).
    """
    return BreachResultORM(
        breach_id=new_breach_id(),
        primitive_id=primitive_id,
        deployment_config_id=config_id,
        trial_index=0,  # one PAIR row per cell — trial index is informational
        temperature=0.7,
        rendered_payload=pair_result.final_rendered_payload[:50_000],
        model_response=pair_result.final_model_response[:50_000],
        verdict=pair_result.final_verdict.value,
        judge_rationale=(
            f"§10.7 PAIR final iter (iters_to_breach="
            f"{pair_result.pair_iters_to_breach}, "
            f"steps={len(pair_result.steps)}, "
            f"aborted={pair_result.aborted_reason or 'no'})"
        )[:2_000],
        judge_confidence=judge_confidence,
        latency_ms=0,
        tokens_in=0,
        tokens_out=0,
        cost_usd=pair_result.pair_attacker_total_cost_usd,
        ran_at=datetime.now(timezone.utc),
        persona_used=None,
        pair_iters_to_breach=pair_result.pair_iters_to_breach,
        pair_attacker_total_cost_usd=pair_result.pair_attacker_total_cost_usd,
    )


async def run_reproduction(
    *,
    database_url: str,
    primitive_limit: int | None,
    n_trials: int,
    temperature: float,
    concurrency: int,
    panel: TargetPanel | None = None,
    judge: JudgeAgent | None = None,
    persona_technique: str | None = None,
    persona_wrapper: PersonaWrapper | None = None,
    pair_max_iters: int = 0,
    pair_attacker: IterativeAttacker | None = None,
    synthesized_only: bool = False,
    escalate: bool = False,
    escalate_max_spend: float | None = None,
    escalate_n_trials: int = 1,
    escalate_planner_model: str | None = None,
    planner: EscalationPlanner | None = None,
) -> ReproductionRunStats:
    """End-to-end Day-2 reproduction sweep. Returns per-run counters.

    ``panel`` and ``judge`` are injection seams — production calls leave
    them None and constructs both from env; tests pass mocks. Mirrors
    the same pattern as ``harvest_once.run_harvest``.

    ``persona_technique`` (§10.7): when set (a PAP technique name like
    ``"Logical Appeal"`` or the directive ``"random"``), every rendered
    attack is wrapped in that persuasion frame before dispatch and the
    BreachResult rows are tagged with ``persona_used`` for the dashboard
    A/B query. ``persona_wrapper`` is the matching injection seam — tests
    pass a stub; production constructs PersonaWrapper.from_env() lazily
    iff ``persona_technique`` is set.
    """
    _assert_schema_present(database_url)

    if panel is None:
        panel = TargetPanel()
    if judge is None:
        judge = JudgeAgent()
    if persona_technique is not None and persona_wrapper is None:
        persona_wrapper = PersonaWrapper.from_env()
    if pair_max_iters > 0 and pair_attacker is None:
        # Default attacker_strategy=mixed locked by the 2026-05-27 n=20 A/B.
        # allow_strategy_pick=True activates the refinement_type field so
        # the dashboard's stubbornness tile can show which strategies broke
        # which configs.
        # per_run_budget_usd=$10: the scaffold default ($0.50) was sized for
        # the 40-cell A/B test; a 250-cell × max_iters reproduce sweep with
        # mixed attacker can easily exceed that. $10 covers a 250-cell ×
        # 3-iter sweep at avg $0.013/refinement; per-primitive ($1.50) and
        # per-day ($20) caps still bound runaway behavior. Discovered 2026-
        # 05-27 PM after Phase 4 of the disciplined sweep crashed at $0.5070.
        pair_attacker = IterativeAttacker(
            attacker_strategy="mixed",
            allow_strategy_pick=True,
            per_run_budget_usd=10.00,
        )
    pair_orchestrator: PairOrchestrator | None = None
    if pair_max_iters > 0 and pair_attacker is not None:
        pair_orchestrator = PairOrchestrator(
            attacker=pair_attacker,
            panel=panel,
            judge=judge,
            max_iters=pair_max_iters,
            target_temperature=temperature,
        )

    # §10.8 inline escalation: when --escalate, a primitive the WHOLE panel
    # refused is laddered (image → CoJ → structured → audio → escalation, stop
    # at first breach) right after its cells finish. Planner is constructed lazily
    # iff escalate (Claude backbone w/ auto-fallback to Llama on refusal).
    if escalate and planner is None:
        planner = EscalationPlanner.from_env(
            **({"model": escalate_planner_model} if escalate_planner_model else {})
        )

    engine = create_engine(database_url)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    stats = ReproductionRunStats(trials_per_pair=n_trials)

    try:
        with SessionLocal() as session:
            primitives_q = (
                select(AttackPrimitiveORM)
                .where(AttackPrimitiveORM.canonical.is_(True))
                .order_by(AttackPrimitiveORM.reproducibility_score.desc())
            )
            if synthesized_only:
                # §10.7 disciplined sweep: fire ONLY synthesized children
                # (escalation + mutation rows) so we don't pay to re-fire
                # baseline primitives that already have breach_results.
                primitives_q = primitives_q.where(
                    AttackPrimitiveORM.synthesized.is_(True),
                )
            if primitive_limit is not None:
                primitives_q = primitives_q.limit(primitive_limit)
            primitive_orms = list(session.execute(primitives_q).scalars())

            config_orms = list(
                session.execute(select(DeploymentConfigORM)).scalars()
            )
            if not config_orms:
                raise RuntimeError(
                    "no DeploymentConfigs in DB — run: "
                    "uv run python scripts/seed_demo_data.py"
                )
            stats.configs_per_primitive = len(config_orms)

            primitives = [_orm_to_pydantic_primitive(o) for o in primitive_orms]
            configs = [_orm_to_pydantic_config(o) for o in config_orms]

            n_pairs = len(primitives) * len(configs)
            n_calls = n_pairs * n_trials
            logger.info(
                "starting sweep: %d primitives × %d configs × %d trials = %d total calls",
                len(primitives),
                len(configs),
                n_trials,
                n_calls,
            )

            semaphore = asyncio.Semaphore(concurrency)
            pairs_done = 0

            async def _bounded(p: AttackPrimitive, c: DeploymentConfig):
                async with semaphore:
                    rendered, trials = await _run_one_pair(
                        primitive=p,
                        config=c,
                        panel=panel,
                        judge=judge,
                        n_trials=n_trials,
                        temperature=temperature,
                        persona_wrapper=persona_wrapper,
                        persona_technique=persona_technique,
                    )
                    return p.primitive_id, c.config_id, rendered, trials

            coros = [
                _bounded(p, c)
                for p in primitives
                for c in configs
            ]

            primitive_by_id = {p.primitive_id: p for p in primitives}
            config_by_id = {c.config_id: c for c in configs}
            pair_aborted_daily = False

            # §10.8 inline escalation bookkeeping: a primitive is escalated only
            # once ALL its cells finish AND none breached. as_completed yields
            # cells interleaved across primitives, so track per-primitive.
            if escalate:
                from scripts.synthesize_escalations import (  # noqa: PLC0415
                    DEFAULT_AUDIO_STYLES,
                    DEFAULT_IMAGE_RENDERERS,
                    DEFAULT_STRUCTURED_FORMATS,
                    run_escalation_ladder_one,
                )
            cells_left = {p.primitive_id: len(configs) for p in primitives}
            prim_breached = {p.primitive_id: False for p in primitives}
            escalation_budget_hit = False

            for fut in asyncio.as_completed(coros):
                pid, cid, rendered, trials = await fut
                pairs_done += 1
                cell_breached = False
                for response, verdict_result in trials:
                    try:
                        row = _build_breach_result_orm(
                            primitive_id=pid,
                            config_id=cid,
                            rendered=rendered,
                            response=response,
                            judge_result=verdict_result,
                        )
                        session.add(row)
                        stats.breach_results_persisted += 1
                        stats.add_verdict(verdict_result.verdict)
                        stats.estimated_cost_usd += response.cost_usd
                        if response.error:
                            stats.target_call_errors += 1
                        elif verdict_result.verdict is JudgeVerdict.ERROR:
                            stats.judge_call_errors += 1
                        else:
                            # Only count judge cost when the judge actually ran.
                            stats.estimated_cost_usd += (
                                _JUDGE_COST_ESTIMATE_PER_CALL_USD
                            )
                        if verdict_result.verdict in (
                            JudgeVerdict.PARTIAL_BREACH, JudgeVerdict.FULL_BREACH,
                        ):
                            cell_breached = True
                    except Exception as exc:
                        stats.persist_errors += 1
                        session.rollback()
                        logger.exception(
                            "persist failed: primitive=%s config=%s err=%s",
                            pid, cid, exc,
                        )
                        continue
                session.commit()

                # §10.7 full PAIR build — fire iterative refinement on cells
                # where no baseline trial breached. One additional BreachResult
                # row per cell (marked via `persona_used` = `pair_iter=N` and
                # `pair_iters_to_breach` set) plus N RefinementStep rows.
                if (
                    pair_orchestrator is not None
                    and not cell_breached
                    and not pair_aborted_daily
                ):
                    try:
                        pair_result = await pair_orchestrator.run_pair_cell(
                            primitive=primitive_by_id[pid],
                            config=config_by_id[cid],
                        )
                    except DailyBudgetExceededError as exc:
                        # Cap hit — log + flip the flag so the remaining
                        # pairs skip PAIR but the baseline reproduction
                        # continues to completion. The baseline data is
                        # the load-bearing artifact; PAIR is the bonus.
                        logger.warning(
                            "PAIR daily budget exceeded — disabling PAIR "
                            "for remainder of sweep: %s", exc,
                        )
                        pair_aborted_daily = True
                    except BudgetExceededError as exc:
                        # Per-run cap hit (base class catch — fires after
                        # the more specific Daily/Primitive subclasses).
                        # Same disable-PAIR-but-continue-baseline strategy:
                        # the sweep keeps walking the remaining pairs,
                        # they just skip the PAIR augmentation. Fixed
                        # 2026-05-27 PM after a Phase 4 run crashed here.
                        logger.warning(
                            "PAIR per-run budget exceeded — disabling PAIR "
                            "for remainder of sweep: %s", exc,
                        )
                        pair_aborted_daily = True
                    else:
                        try:
                            pair_row = _build_pair_breach_result_orm(
                                primitive_id=pid,
                                config_id=cid,
                                pair_result=pair_result,
                            )
                            session.add(pair_row)
                            session.flush()  # surface PK conflicts now
                            for step_row in build_step_orm_rows(
                                breach_id=pair_row.breach_id,
                                steps=pair_result.steps,
                            ):
                                session.add(PairRefinementStepORM(**step_row))
                            stats.breach_results_persisted += 1
                            stats.add_verdict(pair_result.final_verdict)
                            stats.estimated_cost_usd += (
                                pair_result.pair_attacker_total_cost_usd
                            )
                        except Exception as exc:
                            stats.persist_errors += 1
                            session.rollback()
                            logger.exception(
                                "PAIR persist failed: primitive=%s config=%s err=%s",
                                pid, cid, exc,
                            )
                        else:
                            session.commit()

                # §10.8 inline escalation — run the auto-ladder on a primitive the
                # moment its LAST cell finishes, iff the WHOLE panel refused it.
                # The session is committed (above) so no transaction is held open
                # during the ladder's minutes of LLM calls (avoids Neon's
                # idle-in-transaction timeout). A winning CoJ/escalation child is
                # persisted in its own short txn; image/structured/audio winners
                # are slot variants of the parent (recorded, not persisted).
                if escalate:
                    prim_breached[pid] = prim_breached[pid] or cell_breached
                    cells_left[pid] -= 1
                    if (
                        cells_left[pid] == 0
                        and not prim_breached[pid]
                        and not escalation_budget_hit
                    ):
                        if (
                            escalate_max_spend is not None
                            and stats.escalation_spend_usd >= escalate_max_spend
                        ):
                            escalation_budget_hit = True
                            logger.warning(
                                "escalation budget $%.2f reached — skipping further "
                                "escalation for the remainder of the sweep",
                                escalate_max_spend,
                            )
                        else:
                            remaining = (
                                None if escalate_max_spend is None
                                else max(0.0, escalate_max_spend - stats.escalation_spend_usd)
                            )
                            res = await run_escalation_ladder_one(
                                primitive_by_id[pid],
                                planner=planner,
                                panel=panel,
                                judge=judge,
                                configs=configs,
                                n_trials=escalate_n_trials,
                                temperature=temperature,
                                image_renderers=DEFAULT_IMAGE_RENDERERS,
                                coj_operations=COJ_OPERATIONS,
                                structured_formats=DEFAULT_STRUCTURED_FORMATS,
                                audio_styles=DEFAULT_AUDIO_STYLES,
                                budget_usd=remaining,
                            )
                            stats.escalations_run += 1
                            stats.escalation_spend_usd += res.spend_usd
                            stats.estimated_cost_usd += res.spend_usd
                            if res.winning_strategy is not None:
                                stats.escalation_breaches += 1
                                stats.escalation_winners[res.winning_strategy] = (
                                    stats.escalation_winners.get(res.winning_strategy, 0) + 1
                                )
                                logger.info(
                                    "escalation breach: parent=%s winner=%s model=%s spend=$%.3f",
                                    pid, res.winning_strategy, res.breached_on, res.spend_usd,
                                )
                                if res.child_orm is not None:
                                    try:
                                        session.add(res.child_orm)
                                        session.flush()
                                        session.commit()
                                    except Exception as exc:  # noqa: BLE001
                                        stats.persist_errors += 1
                                        session.rollback()
                                        logger.exception(
                                            "escalation persist failed: parent=%s err=%s",
                                            pid, exc,
                                        )
                            else:
                                logger.info(
                                    "escalation exhausted: parent=%s spend=$%.3f attempts=%s",
                                    pid, res.spend_usd, res.attempts,
                                )

                if pairs_done % 10 == 0 or pairs_done == n_pairs:
                    logger.info(
                        "[progress] pairs=%d/%d est_cost=$%.2f verdicts=%s",
                        pairs_done,
                        n_pairs,
                        stats.estimated_cost_usd,
                        dict(sorted(stats.verdict_counts.items())),
                    )

            stats.primitives_processed = len(primitives)

    finally:
        await panel.aclose()
        if persona_wrapper is not None:
            await persona_wrapper.aclose()
        if pair_attacker is not None:
            await pair_attacker.aclose()
        if planner is not None:
            await planner.aclose()
        engine.dispose()

    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="One-shot ROGUE reproduction sweep (§A.13)."
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
    )
    parser.add_argument(
        "--primitive-limit",
        type=int,
        default=None,
        help=(
            "Limit to top-N primitives by reproducibility_score. "
            "Omit to run against ALL canonical primitives."
        ),
    )
    parser.add_argument(
        "--n-trials",
        type=int,
        default=DEFAULT_N_TRIALS,
        help="Trials per (primitive, config) pair. Default 5.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=DEFAULT_TEMPERATURE,
        help="Sampling temperature for target-model calls. Default 0.7.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=(
            "Concurrent (primitive, config) pairs. Default 5. Lower if "
            "you cascade-429 the target providers."
        ),
    )
    parser.add_argument(
        "--persona",
        default=None,
        help=(
            "§10.7 persona augmentation. Pass a PAP persuasion technique name "
            "(e.g. 'Logical Appeal', 'Expert Endorsement', 'Storytelling') "
            "or the directive 'random' to wrap each rendered attack with a "
            "uniformly-sampled technique. Omit to run the unwrapped baseline "
            "(the A side of the A/B). The matching wrapped run produces the "
            "B side; the dashboard /api/persona/stats endpoint diffs them "
            "per-config. Pair with --primitive-limit 50 to keep within the "
            "§10.7 disciplined ~$4 LLM budget."
        ),
    )
    parser.add_argument(
        "--synthesized-only",
        action="store_true",
        help=(
            "§10.7 disciplined sweep: restrict the reproduction loop to "
            "primitives with `synthesized=True` (escalation + mutation "
            "children). Use after running synthesize_escalations.py + "
            "synthesize_mutations.py to fire just the new rows through the "
            "panel — avoids paying to re-fire harvested baselines whose "
            "breach_results already exist."
        ),
    )
    parser.add_argument(
        "--pair-max-iters",
        type=int,
        default=0,
        help=(
            "§10.7 full PAIR build. When > 0, every EVADE/REFUSED baseline "
            "trial is followed by up to N iterative attacker refinements "
            "(default attacker_strategy=mixed, locked by the n=20 A/B). "
            "Each iteration is persisted as a `pair_refinement_steps` row "
            "linked to the cell's BreachResult; `pair_iters_to_breach` is "
            "set on the BreachResult to the first-breach iter (NULL if no "
            "breach). Default 0 = no PAIR (same as before the full build "
            "shipped). Set to 3 for the §10.7 disciplined default."
        ),
    )
    parser.add_argument(
        "--no-iterative",
        action="store_true",
        help=(
            "§10.7 demo fallback: forces --pair-max-iters=0 regardless of "
            "other flags. Convenience for the demo recording when you want "
            "the unrefined baseline + the rest of the sweep behavior."
        ),
    )
    parser.add_argument(
        "--escalate",
        action="store_true",
        help=(
            "§10.8 inline escalation. OFF by default = plain reproduce. When set, "
            "any primitive the WHOLE panel refused is run through the auto-ladder "
            "(image → CoJ → structured-data → audio → crescendo→actor→acronym, "
            "stop at first breach) right after its cells finish — fold the "
            "'fail → try harder' step into the reproduce pass. COSTLY: each "
            "fully-resisting primitive can add up to ~150 LLM calls. Bound it "
            "with --escalate-max-spend."
        ),
    )
    parser.add_argument(
        "--escalate-max-spend",
        type=float,
        default=None,
        help=(
            "§10.8 escalation budget cap in USD (estimated). Once cumulative "
            "escalation spend reaches this, the remaining refused primitives are "
            "NOT escalated (the baseline reproduce still completes). Omit = no cap."
        ),
    )
    parser.add_argument(
        "--escalate-n-trials",
        type=int,
        default=1,
        help="§10.8 trials per (ladder variant × config). Default 1 to keep cost down.",
    )
    parser.add_argument(
        "--escalate-planner-model",
        default=None,
        help=(
            "§10.8 override the Tier-5 escalation planner backbone (e.g. an "
            "OpenRouter Llama that authors escalations Claude refuses). Default "
            "Claude w/ auto-fallback to Llama on refusal."
        ),
    )
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)
    # --no-iterative overrides --pair-max-iters per §10.7 demo-fallback semantics.
    if args.no_iterative:
        args.pair_max_iters = 0

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    run_id = args.run_id or uuid.uuid4().hex[:12]
    logger.info(
        "run_id=%s start: primitive_limit=%s n_trials=%d",
        run_id, args.primitive_limit, args.n_trials,
    )

    if args.persona is not None:
        logger.info("run_id=%s persona augmentation enabled: technique=%r", run_id, args.persona)
    if args.pair_max_iters > 0:
        logger.info(
            "run_id=%s §10.7 PAIR enabled: max_iters=%d strategy=mixed (locked by 2026-05-27 A/B)",
            run_id, args.pair_max_iters,
        )
    elif args.no_iterative:
        logger.info("run_id=%s --no-iterative: PAIR disabled for this run", run_id)
    if args.escalate:
        logger.info(
            "run_id=%s §10.8 inline escalation ENABLED: n_trials=%d max_spend=%s planner=%s",
            run_id, args.escalate_n_trials,
            f"${args.escalate_max_spend:.2f}" if args.escalate_max_spend is not None else "uncapped",
            args.escalate_planner_model or "claude+auto-fallback",
        )

    stats = asyncio.run(
        run_reproduction(
            database_url=args.database_url,
            primitive_limit=args.primitive_limit,
            n_trials=args.n_trials,
            temperature=args.temperature,
            concurrency=args.concurrency,
            persona_technique=args.persona,
            pair_max_iters=args.pair_max_iters,
            synthesized_only=args.synthesized_only,
            escalate=args.escalate,
            escalate_max_spend=args.escalate_max_spend,
            escalate_n_trials=args.escalate_n_trials,
            escalate_planner_model=args.escalate_planner_model,
        )
    )
    logger.info("run_id=%s done: %s", run_id, stats.summary_line())
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
