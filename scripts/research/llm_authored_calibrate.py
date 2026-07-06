"""Calibrate dedupe/llm_authored.py against HC3 (human vs ChatGPT). $0 — pure scorer, no API.

Downloads HC3 per-domain JSONL from Hugging Face (cached under data/research/hc3/), scores human vs
ChatGPT answers, and reports AUC + best-F1 threshold per domain + pooled. See
docs/research/llm_authored_calibration.md for the interpreted result.

    uv run python scripts/research/llm_authored_calibrate.py [--n 1500]
"""

from __future__ import annotations

import argparse
import bisect
import json
import os
import statistics as st
import urllib.request

from rogue.dedupe.llm_authored import HUMAN_AUTHORED_THRESHOLD, LLM_AUTHORED_THRESHOLD, llm_authored_score

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
CACHE = os.path.join(ROOT, "data", "research", "hc3")
DOMAINS = ("reddit_eli5", "finance", "open_qa")
BASE = "https://huggingface.co/datasets/Hello-SimpleAI/HC3/resolve/main/{}.jsonl"


def _ensure(domain: str) -> str:
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{domain}.jsonl")
    if not os.path.exists(path):
        print(f"downloading HC3/{domain} ...")
        urllib.request.urlretrieve(BASE.format(domain), path)  # noqa: S310 (trusted host)
    return path


def _load(domain: str, n: int) -> tuple[list[str], list[str]]:
    human: list[str] = []
    llm: list[str] = []
    with open(_ensure(domain)) as f:
        for line in f:
            if len(human) >= n and len(llm) >= n:
                break
            r = json.loads(line)
            if r.get("human_answers") and len(human) < n:
                human.append(r["human_answers"][0])
            if r.get("chatgpt_answers") and len(llm) < n:
                llm.append(r["chatgpt_answers"][0])
    return human, llm


def _auc(pos: list[float], neg: list[float]) -> float:
    neg_sorted = sorted(neg)
    wins = ties = 0
    for s in pos:
        wins += bisect.bisect_left(neg_sorted, s)
        ties += bisect.bisect_right(neg_sorted, s) - bisect.bisect_left(neg_sorted, s)
    return (wins + 0.5 * ties) / (len(pos) * len(neg_sorted))


def _f1(thr: float, llm_s: list[float], human_s: list[float]) -> tuple[float, float, float, float]:
    tp = sum(1 for s in llm_s if s >= thr)
    fp = sum(1 for s in human_s if s >= thr)
    fn = len(llm_s) - tp
    tn = len(human_s) - fp
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return prec, rec, f1, (tp + tn) / (tp + tn + fp + fn)


def _report(name: str, human: list[str], llm: list[str]) -> tuple[list[float], list[float]]:
    hs = [llm_authored_score(t).score for t in human]
    ls = [llm_authored_score(t).score for t in llm]
    print(f"\n== {name} (human n={len(hs)}, llm n={len(ls)}) ==")
    print(f"mean human={st.mean(hs):.3f} llm={st.mean(ls):.3f}  AUC={_auc(ls, hs):.3f}")
    p, r, f1, a = _f1(LLM_AUTHORED_THRESHOLD, ls, hs)
    print(f"@ default {LLM_AUTHORED_THRESHOLD}: P={p:.3f} R={r:.3f} F1={f1:.3f} acc={a:.3f}")
    best = max((round(t / 100, 2) for t in range(25, 85, 2)), key=lambda t: _f1(t, ls, hs)[2])
    p, r, f1, a = _f1(best, ls, hs)
    print(f"@ best {best}: P={p:.3f} R={r:.3f} F1={f1:.3f} acc={a:.3f}")
    return hs, ls


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1500, help="samples per class per domain")
    args = ap.parse_args()
    print(f"default thresholds: LLM>={LLM_AUTHORED_THRESHOLD} HUMAN<={HUMAN_AUTHORED_THRESHOLD}")
    allh: list[float] = []
    alll: list[float] = []
    for d in DOMAINS:
        hs, ls = _report(d, *_load(d, args.n))
        allh += hs
        alll += ls
    print(f"\n== POOLED == AUC={_auc(alll, allh):.3f}")
    best = max((round(t / 100, 2) for t in range(25, 85, 2)), key=lambda t: _f1(t, alll, allh)[2])
    p, r, f1, a = _f1(best, alll, allh)
    print(f"best {best}: P={p:.3f} R={r:.3f} F1={f1:.3f} acc={a:.3f}")


if __name__ == "__main__":
    main()
