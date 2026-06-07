# 0005 — LLM-judge content-transfer gate (v1→v3 recalibration) + stored-matrix re-judge

- **Status:** Accepted (the credibility core)
- **Date:** 2026-06-08 (retroactive; v3 recalibration + matrix re-judge 2026-06-07)

## Context

ROGUE's entire claim — "this attack breaches your config" — rests on the judge that grades each (attack × target) trial as refused / evaded / partial / full_breach. An inflationary judge invalidates the product. The original v1 judge over-reported. ROGUE needed a judge whose verdict means *the harmful content actually transferred to the response*, defensible against external yardsticks (JBB, WildGuardTest, StrongREJECT).

## Decision

Adopt the **v3 judge** as a content-transfer gate: a breach requires that the response actually carries the harmful content, not merely that the model "engaged." All four credibility axes were re-measured under v3 and are now v3-coherent: JBB judge-comparison precision 55%→79.5% / agreement 70.3%→89.3%; WildGuardTest harm 78.1%→88.5% (the axis matching ROGUE's content-transfer job); WildGuardTest refusal 91.8%→75.5% (a *definitional* drop — v3 maps engaged-but-benign to no-breach, which WildGuard's refusal label scores as "not refused"; a content-transfer-vs-refusal mismatch, not a harm regression); StrongREJECT inflation delta −26% (≤0 at every threshold, *more* non-inflationary than v1's −16%). Then the **stored breach-matrix corpus was re-judged under v3** (2026-06-07): breach cells 2,429→1,371 (−43.6%), all 419 ERROR cells resolved, via `scripts/rejudge_batch.py --changeable-only` + `resume_rejudge.py`. The live dashboard now shows v3-graded breaches. Reports: `data/calibration/{wildguard_report,strongreject_report}.json`.

## Consequences

- Headline ASR dropped ~44% on re-grade — deliberately. The product reports *fewer, truer* breaches; "defensible numbers only" (e.g. marketing `proof.ts` excludes inflated ASR).
- Do NOT loosen the judge to recover the WildGuard recall gap: a 19-item false-negative audit showed they are mostly WildGuard label over-counting (refusals/fiction/placeholders graded harmful), not real v3 misses (`docs/judge_fp_taxonomy.md §7`).
- Any historical metric must be tagged v1/v2 vs v3 (e.g. grammar-efficacy lift inherits the v1/v2 baseline).

## What would reverse this

A v4 recalibration prompted by a *measured* systematic v3 error class (a real false-negative taxonomy, not WildGuard label noise) — re-run the same three-axis harness + a fresh matrix re-judge before adopting.
