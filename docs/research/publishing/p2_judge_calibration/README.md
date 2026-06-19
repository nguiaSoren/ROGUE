# P2 — arXiv package: judge-calibration paper

Self-contained arXiv submission (methodology). Primary `cs.CR`, cross-list `cs.CL`.
Title: *Consummation-Based Calibration of LLM-as-Judge Breach Detectors that Generalizes Across Breach Classes.*

## Files
- `main.tex` — the paper (~9–10pp with Table 1, 4 figures, refs). `article` class, `natbib` + `plainnat`.
- `references.bib` — 8 citations, each twice-verified (arXiv + DBLP/ACL). Provenance in `../references.bib`.
- `fig1-p2-final.png` — Fig 1 (teaser), one gate across four breach classes shown as engagement-vs-consummation, with agreement per class (harm 91.0 / info-disc 97.3 / action 98.9 / fabrication 96.9).
- `fig-generalization.png` — Fig 2, one gate across four breach classes (harm 91.0 / info-disc 97.3 / action-v3 98.9 / fabrication 96.9).
- `fig-refine-to-ship.png` — Fig 3, the unauthorized-action diagnose→refine→trace loop (FP-mode 9.38→6.25→3.12%).
- `fig-type-dependent.png` — Fig 4, the action FP-mode as a text-only-proxy artifact (tool-trace halves it).

## Build (no local LaTeX on this machine)
Overleaf: upload folder, pdfLaTeX. Or `latexmk -pdf main.tex`.

## Every number traces to source
- Diagnosis (70.3%, last of five) + the +19/+24.5pp fix + 91.0% re-confirm: `data/calibration/`, the v3 calibration history (ADR-0005), JBB `judge_comparison`.
- Honest correction (breach cells 2,429→1,371, −43.6%): re-judge of the stored matrix.
- External axes: WildGuardTest 88.5%, StrongREJECT ~26% more conservative, in-dist FP 2.56%.
- Table 1 per-type: `data/calibration/<type>_report.json` (infodisc, unauthorized_action v1/v2/v3, fabricated_sensitive_value v2).
- κ jumps (action 0.746→0.917, fabrication 0.723→0.909): `scripts/calibration/kappa_check.py` + the trace-bearing corpora.
- Figures: `scripts/calibration/judge_figs.py`.

## Honest framing baked in (matches the source's own positioning)
- The contribution is stated as **rigor + a cross-type measurement, NOT a new mechanism** — the gate idea is credited to StrongREJECT / Jailbreak Tax; cross-class judging to CompliBench / CourtGuard. (This explicit under-claim is intentional and correct.)
- Single-operator κ, synthetic-but-grounded corpora, black-box unpinned targets — all stated in §Limitations.
- "Workshop-defensible now; conference-grade needs an independent expert relabel" — keep that honesty in any cover note.

## Before submitting
- [ ] Compile on Overleaf; check Table 1 (7-col) and the 4 figures render.
- [ ] Confirm author/affiliation line.
- [ ] Same one cs.CR endorsement (Hiskias) covers P1, P2, P3.
