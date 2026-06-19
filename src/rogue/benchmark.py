"""The benchmark runner — the engine behind ``client.benchmark()``.

Measures attack-success-rate (ASR) against a frozen, field-standard goal set
(AdvBench / JailbreakBench). Each goal is wrapped as a minimal single-turn
``AttackPrimitive`` (the bare harmful request) and run through the same
provider-agnostic :func:`rogue.scan.run_scan` loop the SDK's ``scan()`` uses, so
the benchmark can never drift from the real reproduction path.

The goal sets are **bundled** with the wheel under ``data/benchmark/`` (the
top-level ``benchmark/`` package that freezes the full 100-goal sets is NOT
shipped), so ``benchmark()`` works from a plain ``pip install``.

ASR = breached goals / total goals; cost is target-call cost.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import ulid

from .schemas import AttackFamily, AttackPrimitive, AttackVector, Severity

if TYPE_CHECKING:
    from .report import BenchmarkReport
    from .schemas import DeploymentConfig

_BENCHMARK_DIR = Path(__file__).parent / "data" / "benchmark"
VALID_DATASETS = ("advbench_100", "jbb_100")

# Stable synthetic timestamp for the wrapped goals (the goals are frozen; their
# discovered_at is not meaningful, only required by the schema).
_SYNTH_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _load_goals(dataset: str) -> list[str]:
    """Load goal strings from the bundled ``data/benchmark/{dataset}.jsonl``."""
    if dataset not in VALID_DATASETS:
        raise ValueError(
            f"unknown benchmark dataset {dataset!r}; valid datasets: {', '.join(VALID_DATASETS)}"
        )
    path = _BENCHMARK_DIR / f"{dataset}.jsonl"
    goals: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        goals.append(json.loads(line)["goal"])
    return goals


def goal_primitive(goal: str) -> AttackPrimitive:
    """Wrap a benchmark goal as a minimal single-turn direct request — the bare
    harmful instruction the target is asked to comply with, which the judge then
    grades. Same construction as the platform's benchmark/judge-eval primitives
    (family ``direct_instruction_override``, vector ``user_turn``); only the id
    (a fresh ULID) and source differ."""
    g = goal.strip() or "(empty goal)"
    return AttackPrimitive.model_validate(
        {
            "primitive_id": ulid.new().str,
            "canonical": False,
            "family": AttackFamily.DIRECT_INSTRUCTION_OVERRIDE,
            "vector": AttackVector.USER_TURN,
            "title": "benchmark goal",
            "short_description": g[:2_000],
            "payload_template": (g if len(g) >= 10 else f"{g} [benchmark goal]")[:20_000],
            "reproducibility_score": 5,
            "base_severity": Severity.MEDIUM,
            "severity_rationale": "external benchmark goal; severity not scored",
            "discovered_at": _SYNTH_TS,
            "sources": [
                {
                    "url": "https://github.com/JailbreakBench",
                    "source_type": "other",
                    "author": None,
                    "published_at": None,
                    "fetched_at": _SYNTH_TS,
                    "archive_hash": "benchmark-external",
                    "bright_data_product": "fixture",
                }
            ],
        }
    )


async def run_benchmark(
    config: DeploymentConfig,
    *,
    dataset: str = "advbench_100",
    max_goals: int = 25,
    adapter_extra: dict[str, Any] | None = None,
    judge_model: str | None = None,
    panel: Any = None,
    judge: Any = None,
) -> BenchmarkReport:
    """Run the first ``max_goals`` goals of ``dataset`` against ``config`` and report ASR.

    ``panel`` / ``judge`` are injectable for testing (no network when supplied).
    Raises ``ValueError`` for an unknown ``dataset``.
    """
    from .report import BenchmarkReport
    from .scan import run_scan

    goals = _load_goals(dataset)[:max_goals]
    primitives = [goal_primitive(g) for g in goals]

    report = await run_scan(
        config,
        primitives,
        n_trials=1,
        adapter_extra=adapter_extra,
        panel=panel,
        judge=judge,
        judge_model=judge_model,
    )

    return BenchmarkReport(
        dataset=dataset,
        target=config.base_url or config.target_model,
        n_goals=len(primitives),
        n_success=report.n_breaches,
        cost_usd=report.cost_usd,
        winner_rank=None,
    )


__all__ = ["run_benchmark", "goal_primitive", "VALID_DATASETS"]
