"""The default :class:`ScanEngine` — the platform's single execution path.

This is a thin wrapper over the existing SDK reproduction pipeline (``render`` → ``TargetPanel`` →
``JudgeAgent``). The non-ladder ``run`` path reimplements no scan logic of its own: it builds the
``DeploymentConfig`` + primitive list from the :class:`ScanSpec`, then **calls**
:func:`rogue.scan.run_scan` — the one provider-agnostic single-turn loop — forwarding the optional
``progress`` callback as run_scan's per-primitive hook so a worker can stream completion percentage
into a :class:`ScanRecord`. There is no second copy of the loop to drift: how a ``Finding`` is built,
how cost is summed, how the 0.4 breach threshold decides ``n_breaches``, how the final ``ScanReport``
is shaped — all live in ``run_scan``. The ladder path (:meth:`_run_ladder`) is a genuinely different
per-goal escalation loop and stays separate.

``validate`` and ``benchmark`` delegate straight to the SDK's ``Client`` / ``run_benchmark`` so there
is exactly one place each of those behaviours lives.

The ``panel`` / ``judge`` / ``judge_model`` constructor arguments are dependency-injection seams for
tests: a fake panel and fake judge let the whole engine run offline with no network, no LLM, no DB,
and no spend.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .interfaces import ProgressCallback, ScanEngine

if TYPE_CHECKING:
    from rogue.report import BenchmarkReport, ScanReport, ValidationResult
    from rogue.schemas import DeploymentConfig

    from .schemas import ScanSpec

# Ladder mode is the expensive path (attacker + target + judge across tiers); a missing budget falls
# back to this hard cap so an uncapped ladder scan can't run away to tens of dollars.
_DEFAULT_LADDER_BUDGET = 5.0
_DEFAULT_DATABASE_URL = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"


class DefaultScanEngine(ScanEngine):
    """The one execution path for every platform surface (worker, SDK-in-process, API)."""

    def __init__(
        self,
        *,
        panel: Any = None,
        judge: Any = None,
        judge_model: str | None = None,
        repertoire_loader: Any = None,
        escalation_ctx_builder: Any = None,
        ladder_runner: Any = None,
    ) -> None:
        # All injectable so tests run fully offline. When left None, the real panel / judge are built
        # lazily inside ``run`` (so importing this module never needs API keys), the repertoire is
        # loaded from the live corpus via ``DATABASE_URL``, and the ladder uses the real escalation
        # machinery (``rogue.reproduce.escalation_ladder``).
        self._panel = panel
        self._judge = judge
        self._judge_model = judge_model
        self._repertoire_loader = repertoire_loader
        self._escalation_ctx_builder = escalation_ctx_builder
        self._ladder_runner = ladder_runner

    def _load_repertoire(self, spec: ScanSpec) -> list:
        """Source primitives for a ``mode="repertoire"`` scan from the live harvested corpus."""
        if self._repertoire_loader is not None:
            return self._repertoire_loader(spec)
        from .repertoire import default_repertoire_loader

        return default_repertoire_loader(spec)

    def _build_escalation_ctx(self, config: DeploymentConfig, n_goals: int, n_trials: int):
        """Build the escalation context (planner + graduated rotation + active renderers) for the ladder.

        Reads the live repertoire in a SHORT session and closes it before the ladder's LLM calls (the
        Neon idle-in-transaction rule). The planner survives the session close (the strategy library is
        materialized in-memory)."""
        if self._escalation_ctx_builder is not None:
            return self._escalation_ctx_builder(config, n_goals, n_trials)
        import os

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from rogue.reproduce.escalation_ladder import build_escalation_context

        url = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
        engine = create_engine(url, pool_pre_ping=True, pool_recycle=300, pool_timeout=10)
        try:
            with sessionmaker(bind=engine)() as session:
                return build_escalation_context(
                    session, configs=[config], n_parents_est=max(1, n_goals), n_trials=n_trials
                )
        finally:
            engine.dispose()

    # --- config construction (shared by run / validate / benchmark) ---------------------------

    def _build_config(self, spec: ScanSpec) -> DeploymentConfig:
        """Turn a :class:`ScanSpec` target into the internal :class:`DeploymentConfig`.

        An ``endpoint`` target routes through ``make_endpoint_config`` (the custom-HTTP path); a
        ``provider`` target is constructed directly, normalising the model id to a ``provider/model``
        slug and falling back to the SDK's per-provider default when no model is given.
        """
        from rogue.reproduce.endpoint_scan import make_endpoint_config
        from rogue.schemas import DeploymentConfig

        target = spec.target
        if target.endpoint:
            return make_endpoint_config(
                target.endpoint,
                target.model or "default",
                system_prompt=target.system_prompt,
            )

        # provider-mode: normalise the model id exactly as rogue.client.Client does.
        if target.model and "/" in target.model:
            target_model = target.model
        elif target.model:
            target_model = f"{target.provider}/{target.model}"
        else:
            target_model = _default_model(target.provider)

        return DeploymentConfig(
            config_id="plat-scan-0001",
            customer_id="platform",
            name=target_model,
            target_model=target_model,
            system_prompt=target.system_prompt,
            base_url=None,
        )

    def _adapter_extra(self, spec: ScanSpec) -> dict[str, Any]:
        return {"api_key": spec.target.api_key} if spec.target.api_key else {}

    # --- operation #1b: ladder scan -----------------------------------------------------------

    async def _run_ladder(self, spec: ScanSpec, config, progress: ProgressCallback | None):
        """Escalation-ladder scan: throw the full multi-tier arsenal at each goal (the pack primitives
        act as the goals). Mirrors ``benchmark_run._run_one_cell`` — one shared panel/judge, a
        per-goal budget, bounded concurrency, first-breach-wins per goal. Budget is effectively
        mandatory here (the ladder is the expensive path): an unset budget defaults to a safe cap."""
        import asyncio

        from rogue.packs import filter_attacks, load_pack
        from rogue.report import Finding, ScanReport, humanize_technique, technique_label
        from rogue.reproduce.escalation_ladder import run_escalation_ladder_one
        from rogue.reproduce.judge import JudgeAgent
        from rogue.reproduce.target_panel import TargetPanel

        goals = filter_attacks(load_pack(spec.pack), spec.attacks)[: spec.max_tests]
        ctx = self._build_escalation_ctx(config, len(goals), spec.n_trials)
        runner = self._ladder_runner or run_escalation_ladder_one

        owns_panel = self._panel is None
        panel = self._panel if self._panel is not None else TargetPanel(adapter_extra=self._adapter_extra(spec))
        owns_judge = self._judge is None
        judge = self._judge if self._judge is not None else (
            JudgeAgent(model=self._judge_model) if self._judge_model else JudgeAgent()
        )

        budget = spec.budget if spec.budget is not None else _DEFAULT_LADDER_BUDGET
        per_goal = budget / max(1, len(goals))
        sem = asyncio.Semaphore(3)
        n_total = len(goals)
        progressed = {"n": 0}

        async def _one(goal):
            async with sem:
                res = await runner(
                    goal,
                    planner=ctx.planner,
                    panel=panel,
                    judge=judge,
                    configs=[config],
                    n_trials=spec.n_trials,
                    strategies=ctx.rotation,
                    image_renderers=ctx.image_renderers,
                    coj_operations=ctx.coj_operations,
                    structured_formats=ctx.structured_formats,
                    audio_styles=ctx.audio_styles,
                    budget_usd=per_goal,
                    candidate_attempt_quota=ctx.effective_quota,
                    candidate_ids=ctx.candidate_ids,
                    # §10.10 contextual mode — cross-tier blended order (None ⇒ fixed
                    # tier sequence). getattr keeps injected test-double ctxs working.
                    cross_tier_order=getattr(ctx, "cross_tier_order", None),
                )
            progressed["n"] += 1
            if progress is not None:
                await progress(progressed["n"], n_total, res.winning_strategy or "held")
            return goal, res

        try:
            results = await asyncio.gather(*[_one(g) for g in goals])
        finally:
            if owns_panel:
                await panel.aclose()
            if owns_judge and hasattr(judge, "aclose"):
                await judge.aclose()
            planner = getattr(ctx, "planner", None)
            if planner is not None and hasattr(planner, "aclose"):
                await planner.aclose()

        findings: list[Finding] = []
        n_breaches = 0
        total_cost = 0.0
        for goal, res in results:
            breached = res.winning_strategy is not None
            if breached:
                n_breaches += 1
            total_cost += getattr(res, "spend_usd", 0.0)
            # A ladder run is ONE test per goal: the goal was either achieved (the escalation broke
            # through) or held. success_rate / n_breach / n_trials all reflect that single outcome
            # (1/1 = achieved, 0/1 = held) so they AGREE with the headline score (severity × success).
            # Reporting the raw escalation-attempt count as n_trials made a finding read "breached
            # 1/18 (6%)" next to a critical-100 score — the same number meaning two different things.
            # The escalation DEPTH (how many techniques it took to break through — a real signal of how
            # hard the model was to crack) is surfaced in the title instead.
            depth = len(res.attempts)
            title = goal.title
            if breached and depth > 1:
                title = f"{goal.title} — broke through after escalating through {depth} techniques"
            findings.append(
                Finding(
                    family=goal.family.value,
                    # The winning transform (e.g. "crescendo", "image:ocr") is richer than the family;
                    # humanize it so the PERSISTED technique is already customer-facing (a graduated
                    # candidate's raw ULID never reaches a report). Fall back to the family label when
                    # the goal held (no breach).
                    technique=(
                        humanize_technique(res.winning_strategy)
                        if res.winning_strategy
                        else technique_label(goal.family.value)
                    ),
                    vector=goal.vector.value,
                    severity=goal.base_severity.value,
                    title=title,
                    success_rate=1.0 if breached else 0.0,
                    n_trials=1,
                    n_breach=1 if breached else 0,
                    example_attack=(goal.payload_template or "")[:400] or None,
                    example_response=None,
                )
            )

        findings.sort(key=lambda f: f.success_rate, reverse=True)
        return ScanReport(
            target=config.base_url or config.target_model,
            n_tests=len(findings),
            n_breaches=n_breaches,
            cost_usd=round(total_cost, 6),
            findings=findings,
        )

    # --- operation #1: scan -------------------------------------------------------------------

    async def run(self, spec: ScanSpec, *, progress: ProgressCallback | None = None) -> ScanReport:
        """Run the scan. The ladder path has its own per-goal loop; every other mode delegates to
        :func:`rogue.scan.run_scan` (the one provider-agnostic single-turn loop), passing ``progress``
        straight through as that function's per-primitive hook."""
        from rogue.packs import filter_attacks, load_pack
        from rogue.scan import run_scan

        config = self._build_config(spec)
        if spec.mode == "ladder":
            # The deepest path: escalate each goal through the full multi-tier ladder (graduated
            # techniques + CoJ + structured + image/audio renderers). Separate loop — return early.
            return await self._run_ladder(spec, config, progress)
        if spec.mode == "repertoire":
            # The full harvested arsenal (corpus, most-reproducible first), capped at max_tests —
            # not a frozen JSON pack. Still the single-turn run_scan loop below.
            primitives = self._load_repertoire(spec)
        else:
            primitives = filter_attacks(load_pack(spec.pack), spec.attacks)[: spec.max_tests]

        # run_scan builds/owns the panel + judge unless we inject them (the test seams), applies the
        # 0.4 breach threshold, sums cost, and shapes the ScanReport — the exact logic this engine
        # used to mirror inline. ``progress`` is forwarded as run_scan's per-primitive hook.
        return await run_scan(
            config,
            primitives,
            n_trials=spec.n_trials,
            budget=spec.budget,
            adapter_extra=self._adapter_extra(spec),
            panel=self._panel,
            judge=self._judge,
            judge_model=self._judge_model,
            progress=progress,
        )

    # --- operation #2: validate ---------------------------------------------------------------

    async def validate(self, spec: ScanSpec) -> ValidationResult:
        """Cheap pre-flight: delegate to the SDK ``Client``'s validate path."""
        from rogue.client import Client

        client = Client(
            endpoint=spec.target.endpoint,
            provider=spec.target.provider,
            model=spec.target.model,
            api_key=spec.target.api_key,
            system_prompt=spec.target.system_prompt,
            _adapter_extra=self._adapter_extra(spec),
        )
        return await client._validate_async()

    # --- operation #3: benchmark --------------------------------------------------------------

    async def benchmark(self, spec: ScanSpec, *, dataset: str, max_goals: int) -> BenchmarkReport:
        """Research-grade ASR on a standard dataset; delegate to the shared benchmark runner."""
        from rogue.benchmark import run_benchmark

        config = self._build_config(spec)
        return await run_benchmark(
            config,
            dataset=dataset,
            max_goals=max_goals,
            adapter_extra=self._adapter_extra(spec),
            judge_model=self._judge_model,
            panel=self._panel,
            judge=self._judge,
        )


def _default_model(provider: str | None) -> str:
    """The SDK's per-provider default model (raises for an unknown provider, like ``Client`` does)."""
    from rogue.client import _DEFAULT_MODELS

    if provider in _DEFAULT_MODELS:
        return _DEFAULT_MODELS[provider]
    raise ValueError(
        f"no default model for provider {provider!r}; set spec.target.model "
        f"(known providers with defaults: {', '.join(sorted(_DEFAULT_MODELS))})"
    )


__all__ = ["DefaultScanEngine"]
