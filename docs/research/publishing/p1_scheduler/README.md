# P1 — arXiv package: the scheduler / allocation paper

Self-contained arXiv submission (systems). Primary category `cs.CR`, cross-list `cs.LG`.
Title: *Allocation Is a Capability-Growth Mechanism: Telemetry and Scheduling in a Self-Growing LLM Red-Team.*

## Two build targets (shared figures + bib)
- **`main.tex`** — the full arXiv version (~12pp, all 7 findings).
- **`main_workshop.tex`** — a tightened ~6pp **workshop cut**: the allocation spine only (reachability telemetry → starvation → the 8/20 causal rate → the economic inversion). Drops the grammar A/B, planner-willingness, allocation-bias detail, cross-tier §6b, and the growth loop. Single argument, for SaTML / SoLaR / Red-Teaming-GenAI. Uses `fig-reachability.png` + `fig-cost-per-grad.png` only.

## Files
- `main.tex` — full arXiv paper (~12pp). `article` class, `natbib` + `plainnat`.
- `main_workshop.tex` — workshop cut (~6pp).
- `references.bib` — 6 citations, each twice-verified (arXiv + a second index). Provenance in `../references.bib`.
- `fig-reachability.png` — Fig 1, reachability by tier, greedy vs growth (planner 0.07→0.98).
- `fig-allocation-bias.png` — Fig 2, ladder win-share vs unbiased breach rate (the rank inversion).
- `fig-cost-per-grad.png` — Fig 3, cost-per-graduation vs K ($8.37 → $7.01 → $1.44, the economic inversion incl. the K=20 point).

The §6b cross-tier result (ASR 30→45% / 50→60%, cost −50%/−41%) is carried by **tables** (real numbers), not a figure.

## Build (no local LaTeX on this machine)
Overleaf: upload the folder, pdfLaTeX, build. Or locally:
```
latexmk -pdf main.tex      # pdflatex + bibtex + pdflatex×2
```

## Every number traces to source
- Reachability / allocation-bias / causal test (3/3): runs `sweep_p2_1780457963` (greedy) + `sweep_starv_q3_1780462736`; figure data `docs/research/figs/data/`.
- Allocation bias: full reproduction matrix, 10,872 trials (`breach_results`).
- **N=20 rate (8/20, Fisher p=0.003, $1.44/grad):** run `abq_1781308343`, 2026-06-13 (`metrics.json` → `growth_k20`).
- K=3/K=5 sweeps: `sweep_starv_q3_*`, `sweep_K5_q5_*`.
- §6b cross-tier: pilot $24.26 (20 AdvBench) + Option E $21.41 (10 AdvBench + 10 JBB), Claude Haiku.
- Grammar A/B (negative result): templates 0.25 / freeform 0.44, arms swapped, SE≈0.12 at N≈16.

## Honest framing already baked in (per the source drafts)
- 3/3 is labelled an existence proof; the **measured rate is 40% on the fresh tail** at N=20, not the optimistic small-N 87.5%.
- The "0/20" baseline = established greedy starvation, NOT a fresh randomized arm; matched arm = the quota-0-vs-3 table.
- Grammar A/B reported as the underpowered null it is; allocation-bias reported as the winner-attribution caveat.

## Before submitting
- [ ] Compile on Overleaf; check the 3 figures render and Table 4 (cross-tier, the 7-col layout) sets cleanly.
- [ ] Decide which Crescendo/PyRIT/AutoRedTeamer framing you want in §Related work (all 6 cites verified).
- [ ] Confirm author/affiliation line.
- [ ] Same one cs.CR endorsement (Hiskias) covers this and P3.
