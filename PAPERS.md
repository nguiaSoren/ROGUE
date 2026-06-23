# Papers & writing

ROGUE's findings are written up as papers and posts. This is the index: each one links to its preprint (when posted) and to the code + data in *this* repo that reproduces it — one repo, every result traceable. Released data follows [`RESPONSIBLE_RELEASE.md`](RESPONSIBLE_RELEASE.md): derived artifacts only, never the raw scraped corpus.

> arXiv links are added here once each preprint is posted (one cs.CR endorsement covers all of them). Until then a paper's row says *preprint — posting soon*.

## Papers

### P1 — Allocation Is a Capability-Growth Mechanism
*Telemetry and Scheduling in a Self-Growing LLM Red-Team.* In a self-growing red-team, evaluation **allocation** is a capability-growth lever, not an efficiency layer: a greedy first-breach ladder starves harvested candidates (reachability 7%), and starvation-aware ordering + a candidate quota convert them into graduated capabilities — **8 of 20 starved candidates graduate vs 0 of 20** under the greedy baseline (Fisher exact *p* = 0.003), backed by a 10,872-trial allocation-bias result.
- **Venue:** arXiv `cs.CR` (×`cs.LG`) · *preprint — posting soon*
- **Reproduce:** frozen results in `data/research/scheduler_results.json` (the causal 8/20, reachability, cost-per-graduation, and allocation-bias matrix); regenerate via `scripts/reproduce/candidate_quota_ab.py` + the `ladder_attempts` telemetry log.

### P2 — [withheld — under anonymized review]
*A per-type consummation gate and an independence discipline for operator-labeled ground truth.* Every breach number is an LLM verdict, so the judge is the load-bearing component. One **consummation-gate** template ("engagement ≠ breach; consummation = breach") instantiates calibrated judges across breach classes, with a self-diagnosing REFINE/SHIP harness validated against independent human labels (JBB **91.0%** — top of field, reproducible from `data/calibration/` — up from a 70.3% v1 judge after a diagnosed recalibration; info-disclosure 97.3%).
- **Venue:** arXiv `cs.CR` (×`cs.CL`) · *preprint — posting soon*
- **Reproduce:** `scripts/calibration/run_calibration.py`, `eval_wildguard.py`, `second_grader_pass.py`, `eval_jbb_judge.py`. See [`docs/judge-calibration.md`](docs/judge-calibration.md).

### P3 — [withheld — under anonymized review] Don't Reproduce in Deployment
*A provenance-stratified audit against a patch-immune anchor, and why a claimed success rate is not evidence.* Most grey-literature-claimed jailbreaks do not survive as working *carriers* under conservative judging in deployment context: reproduction collapses 40.5% → 9.0% → 3.7% as the target hardens, and a source's claimed rate carries no usable signal (Spearman −0.10, *n* = 56; of 17 techniques claiming ~100%, only seven reproduce at all, and reproduction averaged across all 17 is 13.3%) — in tension with the closest comparable community-corpus study, a disagreement we trace to the judge.
- **Venue:** arXiv `cs.CR` · **lead paper for the endorsement ask** · *preprint — posting soon*
- **Reproduce:** `scripts/research/reproducibility_gap.py` (pinned to the frozen snapshot) + `reproducibility_gap_figs.py`; frozen aggregates in `data/research/reproducibility_gap_results.json`, and the per-primitive (claimed, measured) table in `data/research/reproducibility_gap_pairs.csv` (recomputes the funnel and the Spearman null with no database).

### P4 — [withheld — under anonymized review]
*Liveness-guarded measurement of canary leakage from shared agent skill pools.* "We scrub entities" is a claim, not a control: a planted canary is recovered from **85%** of skills on a weak model despite an explicit never-reveal instruction, and across four models leakage tracks *alignment*, not size (llama-3.1-8b 85%, llama-3.3-70b 65%, gpt-oss-20b 35%; qwen3-32b 100%, whose rate counts canaries surfaced in inline chain-of-thought, not only the final answer). The four-model ordering rests on a single run of n=20 canaries per model (wide, overlapping CIs). Includes a methods result — an un-instrumented extraction harness silently reports a *fake* 0% when its calls die.
- **Venue:** arXiv `cs.CR` (×`cs.LG`) — also a workshop/blog candidate (Red Teaming GenAI / SoLaR lineage) · *preprint — posting soon*
- **Reproduce:** `scripts/memory/run_leakage_redteam.py --paraphrase-judge`.

## Posts

### Oversight meaningfulness
Measuring whether human oversight of an AI gate is *meaningful* — a false-approve rate against an independent key, plus a bias-laundering guard. Framed honestly as method + instrument + proof-of-concept (n = 1).
- **Where:** LessWrong → AI Alignment Forum + personal site · *drafted, not yet posted*

---

*Built by [Benaja Soren Obounou Lekogo Nguia](#). Every reported number traces to a script or a released data slice in this repo; citations in each paper are twice-verified against arXiv + a second index.*
