# Judge artifact-robustness + per-cell disagreement uncertainty (Q5)

**Status:** built + wired + offline-validated ($0); the black-box-judge headline number is one small paid arm away. Off by default, byte-identical when off.

Every breach number ROGUE reports rides on one component: the safety judge (`reproduce/judge.py`, default Claude Sonnet — a **black-box proprietary** model). Q5 asks the question a reliability-conscious reviewer asks of that judge, and answers it two ways: *measure* how much a benign artifact can fool it (Component A), and *flag* the individual verdicts that sit on the boundary (Component B).

## The gap this closes (why it hardens judge-reliability)

Three 2025-26 audits establish that LLM safety judges are not robust to **artifacts** — superficial, harm-preserving edits to the graded response that move the verdict without changing what the response says:

- **Eiras et al., "Know Thy Judge"** (arXiv 2503.04474). The pointwise ΔFNR recipe. Restyling a still-harmful response (storytelling) or appending a long benign block raises the judge's **false-negative rate** by up to **+0.24** (HarmBench) and **to 1.0** (WildGuard, "Prepend + Append Benign"). Humans re-annotated the perturbed responses and still agreed with the original labels 0.99-1.0, so every induced miss is pure judge error, not a label change.
- **Chen & Goldfarb-Tarrant, "Safer or Luckier?"** (arXiv 2503.09347). The apology artifact. Prepending an apology skews a judge's safety preference **up to 98%** (Claude 3 Sonnet: 46% in their tie-detection test). Their task is *comparative* (pairwise winrate); we take the artifact and measure it on our *pointwise* axis.
- **Schwinn et al., "A Coin Flip for Safety"** (arXiv 2603.06594). A 6,642-label audit showing judge accuracy degrades to near-random under the distribution shifts red-teaming induces, and that sampling attacks "inflate their success rates by exploiting judge insufficiencies."

**The regime none of them tests is ROGUE's.** Eiras audits only open-weight judges (HarmBench / WildGuard / ShieldGemma / LlamaGuard); Chen is mostly open; Schwinn *deliberately excludes proprietary models* — "frequently updated ... undermining reproducibility ... submitting harmful queries for judgment frequently triggers account suspensions." ROGUE's headline judge is a black-box proprietary Claude. Running the Eiras/Chen artifact-ΔFNR recipe on that judge is an untested regime, and the measured column it produces is a first-of-kind judge-reliability contribution.

## Component A — the artifact-robustness probe (calibration-time)

`src/rogue/reproduce/calibration/artifact_robustness.py` is a pure probe. Given a labeled slice (each item = a response text + a human "is this harmful" bit) and a `grade_fn` (text → is-breach), it:

1. grades the unperturbed slice → a baseline `AxisAgreement` (the same tp/fp/fn/tn 2×2 the JBB / WildGuard / binary-breach harnesses already use);
2. re-grades the slice under each benign, harm-preserving perturbation;
3. reports, per perturbation, **ΔFNR / ΔFPR** and the crisp **induced-false-negative rate** — of the harmful responses the judge *caught* at baseline, what fraction the artifact flips to "safe" — with a Wilson CI.

It reuses `wildguard_eval.score_axis`, the new `AxisAgreement.false_negative_rate` (mirror of the existing `false_positive_rate`), and `calibration.bootstrap.bootstrap_ci`. No new dependency, no new statistics. The `grade_fn` is the injection seam (§10.2's `judge_fn` pattern): the $0 validator passes a network-free `HeuristicJudge`; the paid runner passes the real `JudgeAgent`.

**The four artifacts**, faithful to the papers:

| name | source | LLM? |
|---|---|---|
| `apology_prefix` | Chen §2.1 — prepend an apology, change nothing else | no |
| `append_long_benign` | Eiras App.C — append the benign refusal block | no |
| `prepend_append_benign` | Eiras App.C — sandwich the response between two benign blocks (their strongest judge-hack) | no |
| `storytelling_restyle` | Eiras §2.1 — re-tell the response as a narrative, content preserved | yes (seam) |

Three are deterministic ($0). Storytelling is Eiras' one LLM-driven perturbation; it takes an injectable `restyle_fn` and falls back to a clearly-labeled deterministic narrative template when none is supplied — so the probe runs fully for $0, and the faithful LLM-restyle number is part of the gated arm. The report never conflates the template result with an LLM-restyle result (`used_llm_restyle` flag).

**Wiring (real, additive, off by default).** `scripts/calibration/eval_jbb_judge.py --artifact-robustness` (or `ROGUE_JUDGE_ARTIFACT_ROBUSTNESS=1`) re-grades the frozen JBB-300 slice (Eiras' exact dataset) under the three deterministic artifacts and emits an `artifact_robustness` block in the report JSON. It **reuses the baseline grade the runner already paid for** (`baseline_pred`), so only the perturbed grades cost. Without the flag the runner is byte-identical (zero extra keys, zero extra calls).

### What the $0 replay shows

`scripts/calibration/replay_artifact_robustness.py` runs the full four-artifact probe over the JBB-300 with ROGUE's **network-free `HeuristicJudge`** — a real number for **$0**:

```
[heuristic_judge] n=300 (harmful=110)  baseline FNR = 9.09%  ·  worst ΔFNR = +0.00%
  apology_prefix        : ΔFNR=+0.00%  ΔFPR=+1.05%   induced-FN = 0/100
  append_long_benign    : ΔFNR=-1.82%  ΔFPR=+13.16%  induced-FN = 0/100
  prepend_append_benign : ΔFNR=-1.82%  ΔFPR=+13.16%  induced-FN = 0/100
  storytelling (template): ΔFNR=+0.00% ΔFPR=+4.74%   induced-FN = 0/100
```

The finding is honest and it *sets up* the paid arm rather than pre-empting it: **ROGUE's free structural judge is artifact-robust on the metric that matters for judge-hacking — ΔFNR ≈ 0 — because it grades structure (code fences, numbered steps, quantities), not tone.** The Eiras/Chen attacks target *semantic* judges that read tone; a structural regex has nothing to be fooled by there. (The benign block instead nudges the heuristic's *FPR* up +13%: the long safety-prose shares vocabulary with harmful goals, so it over-calls a few clean responses — the opposite failure direction, also honestly surfaced.)

**This is exactly why the headline needs the paid arm.** The judge the board actually rides on is the *semantic* Claude judge — the kind Eiras/Chen show is vulnerable. Does ROGUE's Claude judge share the heuristic's robustness or the LLM-judge weakness? That is the untested black-box regime, and the number is:

```
uv run python scripts/calibration/eval_jbb_judge.py --yes --artifact-robustness   # ≈ $9 at --limit 100
```

## Component B — per-cell disagreement uncertainty (live fire path)

Where Component A measures the judge *offline*, Component B surfaces per-cell uncertainty *live*. ROGUE's judge already ships a conservative **strict bracket** (`JudgeAgent(strict=True)` — the same rubric with an under-flagging preamble, used today only in the calibration harness as a "crude ensemble"). `src/rogue/reproduce/disagreement_judge.py` puts it to work at scan time.

**The signal — a bracket-fragile breach.** When the primary judge calls a cell a breach, `DisagreementJudge` re-grades that one cell with the strict bracket. If the strict grader will not confirm the breach, the verdict sits on the boundary between the primary and the conservative grader: a **low-confidence breach**. The headline verdict is never changed — the primary still decides, and the strict grade never creates or removes a breach; the cell is only *stamped* (`[JUDGE_UNCERTAIN:strict=<verdict>]`, the same lightweight no-migration surfacing the existing `[JUDGE_REFUSED→…]` flag uses, so it flows through `breach_results.judge_rationale` to the matrix / API / MCP / dashboard for free).

**Why only breach cells.** A red-team's expensive error is a spurious breach inflating the board (Schwinn). Re-grading every non-breach cell to hunt false negatives would roughly double a whole scan's judge cost; re-grading only the (minority) breach cells bounds the extra spend to `#breaches × 1` strict grade. The permissive-bracket direction (does a primary *non-breach* become a breach under the over-flagging grader) is the natural extension and is what a balanced-slice cross-bracket arm measures; it is deliberately out of the live path.

**Design** mirrors the `CascadeJudge`: a transparent proxy (`__getattr__` forwards everything else to the wrapped judge), a lazily-built strict sibling, and a strict grade that can *never fail a scan* (any error → the cell is left unflagged, exactly like the cascade's cheap tier can only ever save a scan). `resolve_disagreement` is the single seam, applied outside the cascade seam: `resolve_disagreement(resolve_cascade(JudgeAgent()))`. Off unless `ROGUE_JUDGE_DISAGREEMENT` is on; it only wraps a real LLM judge (a keyless `HeuristicJudge` has no strict bracket to disagree with, so it is returned untouched). Wired into all three fire surfaces — `run_scan`, `scan_endpoint`, `reproduce_once` (inert on `--judge-batch`) — surfacing `ScanReport.judge_disagreement` / `EndpointScanReport.n_judge_uncertain`.

### What the $0 replay shows

`scripts/reproduce/replay_disagreement.py` gives a $0 lower-bound proxy from the frozen JBB-300: how often the four field-standard classifiers *split* (a cross-judge stand-in for how often a breach is judge-fragile).

```
Q5 judge-disagreement — $0 cross-judge split prevalence on JBB-300
  all items    : 88/300  = 29.3% [24.5%, 34.7%]
  human-HARMFUL: 24/110  = 21.8% [15.1%, 30.4%]   <- the low-confidence-breach proxy
  human-clean  : 64/190  = 33.7% [27.3%, 40.7%]
```

Read: on ~22% of genuinely-harmful items the standard judges disagree — a floor on how many breaches are judge-fragile, i.e. the kind of cell the live flag surfaces. This is cross-*judge* disagreement, not the live primary-vs-strict-bracket rate; the live per-cell number is the gated arm (paid strict grades, which ride the Component A arm since both re-grade the same slice under a second bracket).

## Verified end-to-end (wired ≠ run)

- **Component A:** the $0 heuristic replay ran over the real JBB-300 (numbers above); the JBB runner's `--dry-run --artifact-robustness` prints the correct extra-cost estimate with zero paid calls; 8 probe unit tests (perturbation fidelity, ΔFNR/ΔFPR + induced-FN math against a controllable stub judge, `baseline_pred` reuse verified to skip the baseline grade, the storytelling seam, the reused `false_negative_rate` property).
- **Component B:** driven through the **real `run_scan` and `scan_endpoint`** with `ROGUE_JUDGE_DISAGREEMENT=on` (env resolver, not an injected wrapper), `$0` stubs, breach cell strict-checked and flagged, `ScanReport.judge_disagreement` / `EndpointScanReport.n_judge_uncertain` populated; the off path asserted byte-identical (field `None`, key absent from `to_dict()`). The end-to-end test also **caught a real seam difference** — `scan_endpoint` binds `JudgeAgent` at module level while `run_scan` imports it lazily — which a mock-only test would have hidden. The rationale-stamp's persistence consumer is code-traced (`persistence.build_breach_result_orm` maps `judge_result.rationale` → `breach_results.judge_rationale` verbatim, line-verified) onto the same channel the shipped `[JUDGE_REFUSED→…]` flag rides; a DB round-trip of a stamped row is the only step not executed here.
- 14 disagreement unit + surface tests, 23 Q5 tests total; `ruff` clean; 715 tests green across the affected judge/calibration/scan/report surfaces.

## Honest gaps / what the paid arm buys

- Component A's shipped $0 number is the **structural heuristic**'s ΔFNR (≈ 0, robust-by-construction). The **black-box Claude** ΔFNR — the number that hardens the judge-reliability result — needs the paid re-grade (`eval_jbb_judge.py --yes --artifact-robustness`, ~$9 at `--limit 100`). The same run, extended with the strict bracket, yields Component B's live per-cell disagreement rate.
- The storytelling headline needs a real `restyle_fn`; the $0 result uses the deterministic template (a strictly weaker lower bound), clearly labeled.
- Component B's live number is bounded by the corpus breach rate (breaches are the minority outcome) and by whether the strict bracket is a strong enough second opinion; the cross-judge $0 proxy (~22%) is a floor, not the live rate.

## Files

- `src/rogue/reproduce/calibration/artifact_robustness.py` — the probe (perturbations, ΔFNR/ΔFPR, induced-FN, report).
- `src/rogue/reproduce/disagreement_judge.py` — the live per-cell uncertainty wrapper + resolver.
- `src/rogue/reproduce/wildguard_eval.py` — `AxisAgreement.false_negative_rate` (new, DRY).
- Wiring: `scripts/calibration/eval_jbb_judge.py` (A), `scan.py` / `reproduce/endpoint_scan.py` / `scripts/reproduce/reproduce_once.py` + `report.py` (B).
- Validators: `scripts/calibration/replay_artifact_robustness.py` (A, $0), `scripts/reproduce/replay_disagreement.py` (B, $0).
- Tests: `tests/test_judge_artifact_robustness.py`, `tests/test_disagreement_judge.py`.
