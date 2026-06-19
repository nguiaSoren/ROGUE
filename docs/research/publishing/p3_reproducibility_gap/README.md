# P3 — arXiv package: reproducibility-gap paper

Self-contained arXiv submission. **Lead paper for the endorsement ask** (primary category `cs.CR`).

## Files
- `main.tex` — the paper (~8pp with figures/refs). `article` class, `natbib` + `plainnat`.
- `references.bib` — 9 citations, every one twice-verified (arXiv + DBLP/ACL); provenance in `../references.bib`.
- `fig-teaser-p3-final.png` — Fig 1 (teaser), the one-figure framing (459 claims → 7 reproduce → mean 13%, plus the arXiv-vs-grey-lit collapse strip).
- `fig-funnel.png` — Fig 2, the reproduction collapse (arXiv vs grey-lit × 3 targets, real CIs).
- `fig-scatter.png` — Fig 3, the C2 null (claimed vs measured, ρ=−0.10, n=56).
- `fig-family.png` — Fig 4 (§C3), family-ordering: measured reproduction (bars) vs mean claimed potency (diamonds); the orderings are unrelated (Spearman −0.044). Frozen-data, restyled.

## Build (no local LaTeX on this machine)
Overleaf: upload the whole folder, set compiler to pdfLaTeX, build. Or locally once you have a TeX dist:
```
latexmk -pdf main.tex          # runs pdflatex + bibtex + pdflatex×2
# or manually:
pdflatex main && bibtex main && pdflatex main && pdflatex main
```

## Every number traces to source
- Corpus counts, Table 1: live DB snapshot 2026-06-13 (459/369/56; source-type split).
- Table 2 / Fig 1 funnel: `data/research/reproducibility_gap_results.json` (40.5/9.0/3.7 pooled; arXiv 51.9/13.9/8.9; grey-lit 36.5/7.2/1.8).
- C2: ρ=−0.098 [−0.374, 0.171], n=56; re-extraction audit (33/40 agree, 7 material) → `data/research/reextracted_claims.json`.
- Judge instrument numbers: companion judge-calibration study (JBB 89.3–91.0%, in-dist FP 2.56%, κ≥0.80).
- Coverage-validity support: ρ=0.35, 0 reversals.

## Before submitting
- [ ] Compile on Overleaf; eyeball that all four figures render (teaser, funnel, scatter, family).
- [ ] arXiv endorsement (cs.CR) from Hiskias; then submit, cross-list cs.CL/cs.LG.
- [ ] Confirm author/affiliation line.
