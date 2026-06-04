"""ROGUE external benchmark layer — the stable-reference (evaluation) side of the
wall: AdvBench + JBB as frozen jailbreak-eval denominators, used to answer
"is this month's ROGUE better than last month's?" against a fixed external
yardstick. Never the generation side — these are harmful goals, not techniques."""

from benchmark.datasets import (
    CANONICAL_DATASETS,
    BenchmarkGoal,
    JudgeComparisonItem,
    load_advbench,
    load_canonical,
    load_jbb_harmful,
    load_jbb_judge_comparison,
)

__all__ = [
    "CANONICAL_DATASETS",
    "BenchmarkGoal",
    "JudgeComparisonItem",
    "load_advbench",
    "load_canonical",
    "load_jbb_harmful",
    "load_jbb_judge_comparison",
]
