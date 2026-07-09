# Papers & writing

ROGUE's findings are written up as papers and posts. This is the index: each entry links to its Zenodo preprint and to the code + data *in this repo* that reproduces it — one repo, every result traceable. Released data follows [`RESPONSIBLE_RELEASE.md`](RESPONSIBLE_RELEASE.md): derived artifacts only, never the raw scraped corpus.

> Each preprint is archived on **Zenodo** with a citable DOI (linked below). Named arXiv mirrors are held while papers are under — or awaiting — double-blind review.

## Papers

### P1 · Allocation Is a Capability-Growth Mechanism
*Telemetry and scheduling in a self-growing LLM red-team.* Evaluation **allocation** is a capability-growth lever, not an efficiency layer: a greedy first-breach ladder starves harvested candidates (reachability 7%); starvation-aware ordering + a candidate quota graduate **8 of 20 vs 0 of 20** (Fisher exact *p* = 0.003), over a 10,872-trial allocation-bias result.
**Preprint** · [Zenodo · 10.5281/zenodo.21016849](https://doi.org/10.5281/zenodo.21016849)
Reproduce: `scripts/reproduce/candidate_quota_ab.py` over frozen `data/research/scheduler_results.json`.

### P2 · *(withheld — under anonymized double-blind review)*
Title, results, preprint DOI, and reproduction package are withheld until review decisions, to preserve submission anonymity (CAMLIS 2026, strict double-blind). Details restored after the venue notifies.

### P3 · *(withheld — under anonymized double-blind review)*
Title, results, preprint DOI, and reproduction package are withheld until review decisions, to preserve submission anonymity. Details restored after the venue notifies.

### P4 · *(withheld — under anonymized double-blind review)*
Title, results, preprint DOI, and reproduction package are withheld until review decisions, to preserve submission anonymity. Details restored after the venue notifies.

## Posts

### Oversight meaningfulness
Is human oversight of an AI gate *meaningful*? A false-approve rate against an independent answer key, plus a bias-laundering guard — framed honestly as method + instrument + proof-of-concept (n = 1).
LessWrong → AI Alignment Forum + personal site · *drafted, not yet posted*.

---

*Built by [Benaja Soren Obounou Lekogo Nguia](#). Every reported number traces to a script or a released data slice in this repo; citations in each paper are twice-verified against arXiv + a second index.*
