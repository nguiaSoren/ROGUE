"""Frozen external benchmark assets — the *stable reference* side of the wall.

ROGUE's internal metrics (harvested / graduated / reachability / cost-per-breach /
K) tell you how the system *behaves*; none tell you whether this month's ROGUE is
better than last month's against a fixed external yardstick. AdvBench + JBB are the
standard jailbreak-eval denominators used across the literature. We freeze them
**once** (pull → versioned local JSONL + a sha256 manifest), commit the frozen
files, and load offline thereafter — a benchmark you re-pull live is not a
benchmark, because the denominator can drift under you.

These are harmful *goals* (and, for judge_comparison, human-labeled responses) — NOT
attack techniques. They live here on the evaluation side and are never ingested as
primitives (see `scripts/analyze_hf_datasets.py`: 0 new families).

Freeze (one-time, needs HF_TOKEN with gated-repo read for AdvBench)::

    uv run python -m benchmark.datasets --freeze

Load (offline, free)::

    from benchmark.datasets import load_advbench, load_jbb_harmful, load_jbb_judge_comparison
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

FROZEN_DIR = Path(__file__).resolve().parent / "frozen"
_DS = "https://datasets-server.huggingface.co"


# --------------------------------------------------------------------------- #
# Frozen record types
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BenchmarkGoal:
    """A harmful behavior to elicit — the unit the ASR benchmark attacks."""

    goal: str
    target: str  # the affirmative completion the benchmark considers a success
    category: str = ""
    source: str = ""


@dataclass(frozen=True)
class JudgeComparisonItem:
    """One JBB judge_comparison row: a target response with human ground truth
    AND the competing classifiers' jailbroken labels — so ROGUE's judge can be
    scored against humans on the same axis as LlamaGuard / GPT-4 / HarmBench."""

    index: int
    goal: str
    prompt: str
    response: str
    human_majority: bool  # ground truth: was the response jailbroken?
    baselines: dict  # {"harmbench": bool, "gpt4": bool, "llamaguard2": bool, "llama3": bool}


# --------------------------------------------------------------------------- #
# HF datasets-server pull (freeze time only)
# --------------------------------------------------------------------------- #
def _rows(dataset: str, config: str, split: str) -> list[dict]:
    tok = os.environ.get("HF_TOKEN")
    headers = {"User-Agent": "rogue-benchmark/1.0"}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    out: list[dict] = []
    offset = 0
    while True:
        url = f"{_DS}/rows?dataset={dataset}&config={config}&split={split}&offset={offset}&length=100"
        payload = None
        for attempt in range(5):  # datasets-server 5xx/timeouts are transient
            try:
                with urllib.request.urlopen(
                    urllib.request.Request(url, headers=headers), timeout=40
                ) as r:
                    payload = json.load(r)
                break
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                code = getattr(exc, "code", None)
                if attempt == 4 or (code is not None and code < 500 and code != 429):
                    raise
                import time

                time.sleep(2 * (attempt + 1))
        batch = payload.get("rows", [])
        out += [b["row"] for b in batch]
        total = payload.get("num_rows_total")
        offset += len(batch)
        if not batch or (total is not None and offset >= total):
            break
    return out


def _write_frozen(name: str, records: list[dict], source: str) -> dict:
    FROZEN_DIR.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in records)
    (FROZEN_DIR / f"{name}.jsonl").write_text(body, encoding="utf-8")
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    meta = {"name": name, "source": source, "n": len(records), "sha256": sha}
    (FROZEN_DIR / f"{name}.meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def _read_frozen(name: str) -> list[dict]:
    path = FROZEN_DIR / f"{name}.jsonl"
    if not path.exists():
        raise FileNotFoundError(
            f"frozen benchmark '{name}' not found at {path}. Run the one-time "
            "freeze: `uv run python -m benchmark.datasets --freeze`"
        )
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# --------------------------------------------------------------------------- #
# Public loaders (offline, free)
# --------------------------------------------------------------------------- #
def load_advbench() -> list[BenchmarkGoal]:
    return [
        BenchmarkGoal(goal=r["goal"], target=r.get("target", ""), source="walledai/AdvBench")
        for r in _read_frozen("advbench")
    ]


def load_jbb_harmful() -> list[BenchmarkGoal]:
    return [
        BenchmarkGoal(
            goal=r["goal"],
            target=r.get("target", ""),
            category=r.get("category", ""),
            source="JailbreakBench/JBB-Behaviors:harmful",
        )
        for r in _read_frozen("jbb_harmful")
    ]


def load_jbb_judge_comparison() -> list[JudgeComparisonItem]:
    return [
        JudgeComparisonItem(
            index=r["index"],
            goal=r["goal"],
            prompt=r["prompt"],
            response=r["response"],
            human_majority=bool(r["human_majority"]),
            baselines=r["baselines"],
        )
        for r in _read_frozen("jbb_judge_comparison")
    ]


# --------------------------------------------------------------------------- #
# Freeze (one-time)
# --------------------------------------------------------------------------- #
def freeze_all() -> list[dict]:
    metas = []

    # AdvBench (gated) — cols: prompt (the harmful instruction), target (affirmative)
    adv = _rows("walledai/AdvBench", "default", "train")
    metas.append(
        _write_frozen(
            "advbench",
            [{"goal": r["prompt"], "target": r.get("target", "")} for r in adv],
            "walledai/AdvBench:default/train",
        )
    )

    # JBB harmful behaviors — cols: Goal, Target, Behavior, Category, Source
    jbb = _rows("JailbreakBench/JBB-Behaviors", "behaviors", "harmful")
    metas.append(
        _write_frozen(
            "jbb_harmful",
            [
                {
                    "goal": r["Goal"],
                    "target": r.get("Target", ""),
                    "category": r.get("Category", ""),
                }
                for r in jbb
            ],
            "JailbreakBench/JBB-Behaviors:behaviors/harmful",
        )
    )

    # JBB judge_comparison — human-labeled responses + competing classifiers
    jc = _rows("JailbreakBench/JBB-Behaviors", "judge_comparison", "test")
    metas.append(
        _write_frozen(
            "jbb_judge_comparison",
            [
                {
                    "index": r["Index"],
                    "goal": r["goal"],
                    "prompt": r["prompt"],
                    "response": r["target_response"],
                    "human_majority": int(r["human_majority"]),
                    "baselines": {
                        "harmbench": int(r["harmbench_cf"]),
                        "gpt4": int(r["gpt4_cf"]),
                        "llamaguard2": int(r["llamaguard2_cf"]),
                        "llama3": int(r["llama3_cf"]),
                    },
                }
                for r in jc
            ],
            "JailbreakBench/JBB-Behaviors:judge_comparison/test",
        )
    )
    return metas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", action="store_true", help="one-time pull + freeze")
    args = parser.parse_args(argv)
    if not args.freeze:
        for name in ("advbench", "jbb_harmful", "jbb_judge_comparison"):
            try:
                meta = json.loads((FROZEN_DIR / f"{name}.meta.json").read_text())
                print(f"  {name}: {meta['n']} rows  sha={meta['sha256'][:12]}  ({meta['source']})")
            except FileNotFoundError:
                print(f"  {name}: NOT FROZEN — run --freeze")
        return 0
    from dotenv import load_dotenv

    load_dotenv()
    for meta in freeze_all():
        print(f"froze {meta['name']}: {meta['n']} rows  sha={meta['sha256'][:12]}  ({meta['source']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
