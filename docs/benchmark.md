# Benchmark — coverage over time

The external yardstick: frozen, field-standard goal sets run through ROGUE's own graduated escalation ladder against a fixed target, recording attack-success-rate, winner-rank, and cost-per-success to a durable table so successive runs answer one question — is this month's ROGUE better than last month's?

Every other number ROGUE reports measures how the system *behaves* (harvested, graduated, reachability, cost-per-breach). None answer the question that actually matters: **is this month's ROGUE better than last month's?** The benchmark layer is the external yardstick. It takes the frozen, field-standard goal sets — [AdvBench](https://github.com/llm-attacks/llm-attacks) (100) and [JailbreakBench](https://github.com/JailbreakBench/jailbreakbench) (100) — and runs each goal through ROGUE's **own graduated escalation ladder** (the *same* code path production uses, not a copy) against a fixed target, then records the result to a durable table. Because the goals are frozen and the target is fixed, the delta between runs is attributable to **the repertoire** — exactly the `harvest → graduate → benchmark → coverage change` loop that was impossible to measure before.

It deliberately records more than attack-success-rate, because ASR alone can't tell you whether the *orchestration* improved:

| Run #0 (Claude Haiku target) | ASR | median winner-rank | ladder depth (best/mean) | cost / success |
|---|---|---|---|---|
| **AdvBench-100** | 93.3% | 18 | 13 / 20.3 | $0.51 |
| **JBB-100** | 90.0% | 17 | 13 / 20.3 | $0.52 |

The target is chosen by a hardness probe, not a guess — soft models (Mistral, GPT-Nano) saturate at 100% on the first ladder rung and show nothing; Claude Haiku sits in the productive middle, where the repertoire breaks goals *deep* in the ladder (median rank ~17). So even with ASR near its ceiling, **winner-rank and cost have large headroom** — a better-ordered or stronger repertoire pulls winners earlier, which the benchmark sees as rank dropping and cost falling, *even if ASR holds flat*. (Run #0's top AdvBench technique is a harvested strategy — the harvest→graduate pipeline is what's breaking the external set.) Run deliberately after major harvests, never on a timer: `python ../scripts/benchmark/benchmark_run.py --tier A --yes` (and `--if-changed` reports, for free, whether the repertoire has grown enough to be worth a run).

## Is the benchmark worth putting on the live dashboard? — Yes, but not yet, and not as ASR.

Three reasons to hold:

1. **It's N=1.** "Coverage over time" with one Run is a dot, not a trend. A timeline chart needs ≥3–4 points to mean anything — and the `--if-changed` reporter just confirmed there's nothing new to plot until the repertoire grows. Shipping it now would advertise a line and show a single point.
2. **The Run #0 ASR predates the judge recalibration.** Run #0 was graded by the v1/v2 judge that JBB showed over-flagged (70.3% agreement, recall 98% / precision 55%), so "93% AdvBench coverage" is inflated. The judge has since been recalibrated (`judge_v3.md`, 89.3% on JBB), but Run #0 itself hasn't been re-run under v3 — so the table above is still the old-judge number, and a public dashboard should plot v3-graded runs, not this one.
3. **ASR is the wrong metric to feature anyway.** It's near-ceiling (90–93%, little room). The metrics with real headroom — and the ones that prove the orchestration work — are **median winner-rank** and **cost-per-success**. A chart of "winner-rank dropping 17 → 8 → 4 over successive harvests" is both more honest *and* more impressive than a flat ASR line.

When it becomes one of the strongest things on the site: now that (a) the judge recalibration has landed (`judge_v3.md` — credible ASR once runs are re-graded under it), it remains to (b) accumulate ~3–4 v3-graded Runs into a real trend. Then the figure to ship is **winner-rank ↓ and cost ↓ over time, annotated with harvest/graduation events** — the visual proof of the `harvest → graduate → benchmark → improvement` loop, which is the entire differentiator. The data's already durable in `benchmark_runs` on Neon, so nothing's lost by waiting; `build_analytics.py` can pull it in when the trend exists.

So: build the website chart after Run #3-ish + the recalibrated judge — and lead with winner-rank, not ASR. Right now it'd be a dot that oversells.
