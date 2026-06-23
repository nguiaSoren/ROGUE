#!/usr/bin/env python3
"""Reproduction self-check for the skill-leak study ("A Dead Call Cannot Leak").

Loads every released run record under data/research/skill_leak_*.json and
re-derives every headline number cited in docs/research/publishing/p4_skill_leak/main.tex
directly from the records, asserting each within tolerance. This is the
"an independent re-runner with code access checks the harness reproduces the rates" gate:
run it before any ship and it must print ALL-PASS.

It does NOT call any model or spend money -- it only recomputes paper claims
from the already-recovered JSON. Rates/CIs are read from the records' own
fields (the harness wrote them); the t-interval endpoints are rounded to the
paper's integer-percent convention before comparison.

Usage:  uv run python scripts/memory/verify_p4_numbers.py
Exit 0 = every cited number reproduces; exit 1 = at least one mismatch.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data" / "research"

FILES = {
    "census": "skill_leak_census_2026-06-16.json",
    "tint": "skill_leak_tint_2026-06-16.json",
    "ladder": "skill_leak_ladder_2026-06-16.json",
    "or70b": "skill_leak_70b_openrouter.json",
    "llama8b_or": "skill_leak_llama8b_or.json",
    "packB": "skill_leak_packB_llama_3run.json",
    "judgepass": "skill_leak_judgepass_2026-06-16.json",
    "grid_pass1": "skill_leak_grid_pass1_2026-06-16.json",
    "mistral": "skill_leak_mistral_or.json",
    "dist_llama": "skill_leak_distilled_llama_instruct.json",
    "dist_gemma": "skill_leak_distilled_gemma.json",
    "align_or": "skill_leak_alignment_or.json",
    "hermes4_or": "skill_leak_hermes4_or.json",
}


def load(tag: str) -> dict:
    return json.loads((DATA / FILES[tag]).read_text())


def by_id(tag: str) -> dict:
    """Index a file's results by canonical_id (falling back to model)."""
    out = {}
    for r in load(tag)["results"]:
        out[r.get("canonical_id") or r["model"]] = r
    return out


def pct(x: float) -> int:
    return round(x * 100)


def ci(r: dict) -> tuple[int, int]:
    return pct(r["across_run_ci_low"]), pct(r["across_run_ci_high"])


PASS, FAIL = [], []


def check(label: str, got, want, tol: float = 0.0):
    ok = (got == want) if tol == 0 else (abs(got - want) <= tol)
    (PASS if ok else FAIL).append((label, got, want))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}: got {got!r}  want {want!r}")


def main() -> int:
    tint = by_id("tint")
    cen = by_id("census")
    lad = by_id("ladder")
    or70 = by_id("or70b")
    jp = by_id("judgepass")
    pb = by_id("packB")

    print("== Headline: instruction-following is not containment ==")
    llama = cen["meta-llama/Llama-3.1-8B-Instruct"]
    check("Llama-3.1-8B-Instruct single-draw 17/20 (85%)", max(llama["per_run_rates"]), 0.85, tol=1e-9)
    check("Llama-3.1-8B-Instruct three-run mean 83%", pct(tint["meta-llama/Llama-3.1-8B-Instruct"]["leakage_rate"]), 83)
    check("Llama-3.1-8B-Instruct three-run CI [76,91]", ci(tint["meta-llama/Llama-3.1-8B-Instruct"]), (76, 91))

    print("== Alignment axis (the load-bearing claim) ==")
    ins = tint["meta-llama/Llama-3.1-8B-Instruct"]
    abl = tint["mlabonne/Meta-Llama-3.1-8B-Instruct-abliterated"]
    check("abliterated mean 97%", pct(abl["leakage_rate"]), 97)
    check("abliterated CI [89,100]", ci(abl), (89, 100))
    check("instruct runs 80/85/85", [pct(x) for x in ins["per_run_rates"]], [80, 85, 85])
    check("abliterated runs 100/95/95", [pct(x) for x in abl["per_run_rates"]], [100, 95, 95])
    check("instruct<abliterated per-run non-overlapping",
          max(ins["per_run_rates"]) < min(abl["per_run_rates"]), True)
    gem_i = tint["google/gemma-2-9b-it"]
    gem_s = tint["MergeBench-gemma-2-9b-it/gemma-2-9b-it_wildguard_jailbreak_2epoch"]
    check("gemma instruct 100%", pct(gem_i["leakage_rate"]), 100)
    check("gemma extra-safety 65% (sd 0)", (pct(gem_s["leakage_rate"]), gem_s["sd"]), (65, 0.0))
    check("gemma extra-safety < instruct per-run", max(gem_s["per_run_rates"]) < min(gem_i["per_run_rates"]), True)
    check("Lexi-uncensored 100%", pct(tint["Orenguteng/Llama-3.1-8B-Lexi-Uncensored-V2"]["leakage_rate"]), 100)
    check("Qwen2.5-7B abliterated 100%", pct(tint["huihui-ai/Qwen2.5-7B-Instruct-abliterated"]["leakage_rate"]), 100)
    base = tint["meta-llama/Llama-3.1-8B"]
    check("Llama base 80% [68,92]", (pct(base["leakage_rate"]), ci(base)), (80, (68, 92)))

    print("== Size axis (conservative supporting claim, within-provider) ==")
    check("Qwen-0.5B three-run 45% [20,70]", (pct(lad["Qwen/Qwen2.5-0.5B-Instruct"]["leakage_rate"]),
          ci(lad["Qwen/Qwen2.5-0.5B-Instruct"])), (45, (20, 70)))
    check("Qwen-1.5B three-run 77% [69,84]", (pct(lad["Qwen/Qwen2.5-1.5B-Instruct"]["leakage_rate"]),
          ci(lad["Qwen/Qwen2.5-1.5B-Instruct"])), (77, (69, 84)))
    check("Qwen-3B saturated 100%", pct(cen["Qwen/Qwen2.5-3B-Instruct"]["leakage_rate"]), 100)
    check("Qwen-0.5B single-draw 55% (shipped anchor)", pct(cen["Qwen/Qwen2.5-0.5B-Instruct"]["per_run_rates"][0]), 55)
    check("Qwen-1.5B single-draw 90% (shipped anchor)", pct(cen["Qwen/Qwen2.5-1.5B-Instruct"]["per_run_rates"][0]), 90)

    print("== Provider serving-stack gap ==")
    check("Llama-3.1-8B Featherless 83%", pct(tint["meta-llama/Llama-3.1-8B-Instruct"]["leakage_rate"]), 83)
    check("Llama-3.1-8B OpenRouter 68% [54,83]", (pct(load("llama8b_or")["results"][0]["leakage_rate"]),
          ci(load("llama8b_or")["results"][0])), (68, (54, 83)))

    print("== Large models on OpenRouter (flagged, not pooled) ==")
    check("Llama-70B 67% [48,86]", (pct(or70["meta-llama/llama-3.1-70b-instruct"]["leakage_rate"]),
          ci(or70["meta-llama/llama-3.1-70b-instruct"])), (67, (48, 86)))
    check("Qwen-72B 87% [68,100]", (pct(or70["qwen/qwen-2.5-72b-instruct"]["leakage_rate"]),
          ci(or70["qwen/qwen-2.5-72b-instruct"])), (87, (68, 100)))
    check("DeepSeek-R1-70B 100%", pct(or70["deepseek/deepseek-r1-distill-llama-70b"]["leakage_rate"]), 100)

    print("== Reasoning trace is a distinct leak surface ==")
    gpt = tint["openai/gpt-oss-20b"]
    check("gpt-oss answer 0%", pct(gpt["channels"]["answer"]["rate"]), 0)
    check("gpt-oss reasoning-inclusive 87%", pct(gpt["channels"]["reasoning_inclusive"]["rate"]), 87)
    check("gpt-oss CoT-only surface +87", pct(gpt["cot_only_surface"]), 87)
    check("gpt-oss mean 42% [16,68]", (pct(gpt["leakage_rate"]), ci(gpt)), (42, (16, 68)))
    check("gpt-oss runs 50/30/45", [pct(x) for x in gpt["per_run_rates"]], [50, 30, 45])
    r1 = or70["deepseek/deepseek-r1-distill-llama-70b"]
    check("DeepSeek-R1-70B answer 3%", pct(r1["channels"]["answer"]["rate"]), 3)
    check("DeepSeek-R1-70B reasoning 100% (+97)", pct(r1["channels"]["reasoning_inclusive"]["rate"]), 100)

    print("== Judge is not load-bearing ==")
    for tag, recs in (("tint", tint), ("census", cen), ("or70", or70), ("ladder", lad), ("packB", pb)):
        bad = [k for k, r in recs.items() if r.get("recovered_via_judge_total", 0) != 0]
        check(f"judge_increment == 0 across all {tag} records", bad, [])
    check("judgepass Llama 15 via marker", jp["meta-llama/Llama-3.1-8B-Instruct"]["recovered_via_marker_total"], 15)
    check("judgepass Llama 0 via judge", jp["meta-llama/Llama-3.1-8B-Instruct"]["recovered_via_judge_total"], 0)

    print("== Disjoint second pack (packB) robustness ==")
    pbi = pb["meta-llama/Llama-3.1-8B-Instruct"]
    pba = pb["mlabonne/Meta-Llama-3.1-8B-Instruct-abliterated"]
    check("packB instruct 82% [74,89]", (pct(pbi["leakage_rate"]), ci(pbi)), (82, (74, 89)))
    check("packB abliterated 98% [91,100]", (pct(pba["leakage_rate"]), ci(pba)), (98, (91, 100)))
    check("packB instruct<abliterated per-run non-overlapping",
          max(pbi["per_run_rates"]) < min(pba["per_run_rates"]), True)

    print("== Mistral third-family size ladder (the third-family size-ladder check) ==")
    mis = by_id("mistral")
    for size_id, b in (("mistralai/ministral-3b-2512", 3), ("mistralai/ministral-8b-2512", 8),
                       ("mistralai/ministral-14b-2512", 14)):
        r = mis[size_id]
        check(f"Ministral-{b}B = 100%% (sd 0)", (pct(r["leakage_rate"]), r["sd"]), (100, 0.0))

    print("== Real-distilled construct validity (the real-distilled construct-validity check) ==")
    dl = by_id("dist_llama")["meta-llama/Llama-3.1-8B-Instruct"]
    check("distilled Llama-instruct 100% [100,100], 0 errors", (pct(dl["leakage_rate"]), ci(dl), dl["n_errors"]),
          (100, (100, 100), 0))
    check("distilled Llama-instruct runs 100/100/100", [pct(x) for x in dl["per_run_rates"]], [100, 100, 100])
    dg = by_id("dist_gemma")
    gi = dg["google/gemma-2-9b-it"]
    gs = dg["MergeBench-gemma-2-9b-it/gemma-2-9b-it_wildguard_jailbreak_2epoch"]
    check("distilled gemma-instruct >=60% lower bound [48,72]", (pct(gi["leakage_rate"]), ci(gi)), (60, (48, 72)))
    check("distilled gemma-extra-safety >=53% [15,91]", (pct(gs["leakage_rate"]), ci(gs)), (53, (15, 91)))
    check("distilled gemma cells are error-floored (n_err>0, same for both)",
          gi["n_errors"] > 0 and gi["n_errors"] == gs["n_errors"], True)
    check("distilled gemma per-run NOT separable (gradient unmeasurable here)",
          max(gs["per_run_rates"]) > max(gi["per_run_rates"]), True)

    print("== Second-provider alignment check (OpenRouter, de-confound) ==")
    ao = by_id("align_or")
    aoi = ao["meta-llama/llama-3.1-70b-instruct"]
    aoh = ao["nousresearch/hermes-3-llama-3.1-70b"]
    check("OR Llama-70B instruct (aligned) 70% [58,82]", (pct(aoi["leakage_rate"]), ci(aoi)), (70, (58, 82)))
    check("OR Hermes-3-70B (permissive) 95% [83,100]", (pct(aoh["leakage_rate"]), ci(aoh)), (95, (83, 100)))
    check("OR ordering reproduces: permissive > aligned", aoh["leakage_rate"] > aoi["leakage_rate"], True)
    check("OR alignment contrast error-free + 0 control-FP",
          (aoi["n_errors"], aoh["n_errors"], aoi["control_false_positives"], aoh["control_false_positives"]),
          (0, 0, 0, 0))

    print("== Recency check (OpenRouter, Hermes-4 Aug-2025, de-vintage) ==")
    h4 = by_id("hermes4_or")
    h4i = h4["meta-llama/llama-3.1-70b-instruct"]
    h4h = h4["nousresearch/hermes-4-70b"]
    check("Hermes-4 recency: instruct 70% [37,100]", (pct(h4i["leakage_rate"]), ci(h4i)), (70, (37, 100)))
    check("Hermes-4 recency: permissive 98% [91,100]", (pct(h4h["leakage_rate"]), ci(h4h)), (98, (91, 100)))
    check("Hermes-4 recency: ordering holds on 2025 weights (permissive > aligned)",
          h4h["leakage_rate"] > h4i["leakage_rate"], True)

    print("== Liveness / integrity invariants ==")
    for tag in ("tint", "census", "or70b", "llama8b_or", "packB", "judgepass", "ladder", "grid_pass1"):
        for r in load(tag)["results"]:
            cfp = r.get("control_false_positives")
            if cfp not in (0, None):
                FAIL.append((f"{tag}:{r.get('model')} control_false_positives", cfp, 0))
    check("0 control false-positives across every shipped record",
          [f for f in FAIL if "control_false_positives" in f[0]], [])

    # Liveness guard: every CITED rate must trace to a guard-passing (live) capture.
    # The tint record holds the cited three-run alignment-arm / gpt-oss / DeepSeek captures.
    check("every tint capture passed the liveness guard (live==True)",
          [r["model"] for r in load("tint")["results"] if r.get("live") is not True], [])
    # The census is single-run; its alignment-arm rows were OVERWRITTEN with the tint
    # three-run mean (see the census file's top-level note). openai/gpt-oss-20b is the one
    # row whose *liveness* fields are the superseded single-run probe (live=False, 27/104
    # errored) left under the live three-run *rate* — a known shell, NOT a guard violation:
    # the rate it reports is the live tint capture's. We assert that explicitly so the
    # self-contradictory-looking row can never be mistaken for a reported-but-dead model.
    SUPERSEDED_LIVENESS = {"openai/gpt-oss-20b"}
    check("every census row live except the documented superseded gpt-oss shell",
          [r["model"] for r in load("census")["results"]
           if r.get("live") is not True and r["model"] not in SUPERSEDED_LIVENESS], [])
    cen_gpt = next(r for r in load("census")["results"] if r["model"] == "openai/gpt-oss-20b")
    tint_gpt = next(r for r in load("tint")["results"] if r["model"] == "openai/gpt-oss-20b")
    check("superseded census gpt-oss rate == its live tint three-run capture",
          (cen_gpt["leakage_rate"] == tint_gpt["leakage_rate"]) and (tint_gpt.get("live") is True), True)

    print(f"\n{'='*60}")
    print(f"PASS: {len(PASS)}   FAIL: {len(FAIL)}")
    if FAIL:
        print("FAILURES:")
        for label, got, want in FAIL:
            print(f"  - {label}: got {got!r} want {want!r}")
        return 1
    print("ALL-PASS: every cited number reproduces from the shipped records.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
