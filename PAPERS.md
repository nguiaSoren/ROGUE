# Papers & writing

ROGUE's findings are written up as papers and posts. This is the index: each entry links to its Zenodo preprint and to the code + data *in this repo* that reproduces it — one repo, every result traceable. Released data follows [`RESPONSIBLE_RELEASE.md`](RESPONSIBLE_RELEASE.md): derived artifacts only, never the raw scraped corpus.

> Each preprint is archived on **Zenodo** with a citable DOI (linked below). Named arXiv mirrors are held while papers are under — or awaiting — double-blind review.

## Papers

### P1 · Allocation Is a Capability-Growth Mechanism
*Telemetry and scheduling in a self-growing LLM red-team.* Evaluation **allocation** is a capability-growth lever, not an efficiency layer: a greedy first-breach ladder starves harvested candidates (reachability 7%); starvation-aware ordering + a candidate quota graduate **8 of 20 vs 0 of 20** (Fisher exact *p* = 0.003), over a 10,872-trial allocation-bias result.
**Preprint** · [Zenodo · 10.5281/zenodo.21016849](https://doi.org/10.5281/zenodo.21016849)
Reproduce: `scripts/reproduce/candidate_quota_ab.py` over frozen `data/research/scheduler_results.json`.

### P2 · [withheld — under anonymized review]
*A per-type consummation gate and an independence discipline for operator-labeled ground truth.* One consummation-gate template ("engagement ≠ breach; consummation = breach") calibrates judges across four breach classes (JBB **91.0%** human agreement, top of field) — reported alongside **a null on its own headline**: an independent 6-labeler panel did not replicate the trace-modality κ lift (raw Δκ +0.011). All 45 divergences released for case-by-case adjudication.
**TMLR** (under review, anonymized) · [Zenodo · [withheld]](https://doi.org/[withheld])
Reproduce: `scripts/calibration/run_calibration.py`, `eval_jbb_judge.py`, `analyze_kappa_replication.py` over `data/calibration/`. See [`docs/judge-calibration.md`](docs/judge-calibration.md).

### P3 · [withheld — under anonymized review] Don't Reproduce in Deployment
*A provenance-stratified audit against a patch-immune anchor.* Reproduction collapses **40.5% → 9.0% → 3.7%** as the target hardens, and a source's claimed rate carries no usable signal (Spearman **−0.07**, *n* = 56; of 17 techniques claiming ~100%, six reproduce, mean measured 13.5%) — in tension with the closest community-corpus study, a disagreement we trace to the judge.
**NDSS 2027** (submission planned Aug 2026, anonymized) · [Zenodo · [withheld]](https://doi.org/[withheld])
Reproduce: `scripts/research/reproducibility_gap.py` over `data/research/reproducibility_gap_pairs.csv` (no database).

### P4 · [withheld — under anonymized review]
*Liveness-guarded measurement of canary leakage from shared agent skill pools.* A planted canary returns from **85%** of scrubbed skills on a weak model despite a never-reveal instruction; across a **22-model census** leakage tracks **alignment, not scale** (Llama-8B instruct 83% < abliterated 97%; safety-tuned gemma-2-9b 65%; reasoning channel 0% → 87%). The spine is a measurement discipline: an un-instrumented harness reports a *fake* 0% when its calls die.
**NDSS 2027** (submission planned Aug 2026, anonymized) · [Zenodo · [withheld]](https://doi.org/[withheld])
Reproduce: `scripts/memory/run_leakage_redteam.py --paraphrase-judge` over `data/research/skill_leak_census_2026-06-16.json`.

## Posts

### Oversight meaningfulness
Is human oversight of an AI gate *meaningful*? A false-approve rate against an independent answer key, plus a bias-laundering guard — framed honestly as method + instrument + proof-of-concept (n = 1).
LessWrong → AI Alignment Forum + personal site · *drafted, not yet posted*.

---

*Built by [Benaja Soren Obounou Lekogo Nguia](#). Every reported number traces to a script or a released data slice in this repo; citations in each paper are twice-verified against arXiv + a second index.*
