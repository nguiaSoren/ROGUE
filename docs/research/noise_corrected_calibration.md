# Noise-corrected calibration — de-biasing a judge-labelled breach rate (Q4)

**One line.** Every breach rate ROGUE reports off an LLM judge is the judge's *raw* positive
fraction; when the judge has a non-zero false-positive rate that number is biased *upward* exactly in
the low-true-rate safety regime. This is a **certification layer** for the benchmark: it estimates the
judge's TPR̂/FPR̂ from the existing human-labelled calibration set and turns a raw judge count into
(a) a **de-biased rate** with a confidence interval that folds in both the test-run and the
calibration-set uncertainty, and (b) a finite-sample **certified security claim** ("true breach rate
< α, Type-I error ≤ ζ") — so a headline number can finally ship off the previously-uncalibrated judges.

It sits at the end of the evaluation pipeline, converting observations into trustworthy claims:

```
human calibration set  ─┐
                        ├─► estimate judge noise (TPR̂/FPR̂)  ─┐
large judge-labelled ───┘                                    ├─► corrected rate + CI ─► CERTIFIED
evaluation corpus (D_J) ─────────────────────────────────────┘                          security claim
```

**Status.** Built + wired into both binary-breach-axis calibration report surfaces, **off by default**
(`ROGUE_NOISE_CORRECTED_CALIBRATION`). Offline-validated $0 by replaying it over data already paid for
— the harm judge's 300-item human-labelled set (`D_M`) and the 12k-row `breach_results` judge run
(`D_J`): **raw judge breach rate 13.5% → noise-corrected 1.0% [95% CI 0.0%–6.6%], which certifies the
true breach rate < 20% at ζ=0.05.** A *shipped per-judge* headline for each of the headline-blocked
narrow judges needs one same-population, judge-only paid calibration pass per judge (see
[The live experiment](#the-live-experiment-the-gated-arm)).

Code: `src/rogue/reproduce/calibration/noise_corrected.py` · replay validator:
`scripts/calibration/replay_noise_corrected.py` · tests: `tests/reproduce/test_noise_corrected.py` ·
env flag: `ROGUE_NOISE_CORRECTED_CALIBRATION` (+ `ROGUE_NOISE_CORRECT_ALPHA`, `ROGUE_NOISE_CORRECT_ZETA`).

**Contribution — a certification layer, not a calibration correction.** The correction *formula* is
not ours and we do not claim a new statistical method: the point-estimate de-bias is the classical
Rogan–Gladen inversion (Lee et al., 2025); the finite-sample validity guarantee is Feng et al. (2026).
Pitched as "we apply Rogan–Gladen to LLM judges," this would be a non-contribution — that already
exists. The contribution is the **system** that makes a *certified* security claim fall out of a live
red-team benchmark's existing outputs. Four things, none of which is the closed form:

1. **A statistical validity guarantee wired into a deployed benchmark.** The correction reads the *same*
   2×2 the calibration harness already computes (`AxisAgreement` → TPR̂/FPR̂) and emits a certification
   with finite-sample Type-I control — no new labelling pipeline, no bolt-on statistics stack.
2. **Estimable $0 over historical traces.** It treats the existing `breach_results` table as the large
   judge-labelled set `D_J`, so the de-bias and its CI are computed over evaluation runs already paid
   for — the guarantee is retrofittable to every number the benchmark has already produced.
3. **A heterogeneous-judge pipeline.** One overlay attaches to *all* the narrow judges (redaction / RTBF
   / user-safety / PII / agent-memory) through one binary-axis report — the certification is a property
   of the reporting layer, not a per-judge reimplementation.
4. **Production reporting that doesn't rewrite history.** It splices in as a **purely additive** block —
   a report written with the flag off is byte-identical to today. The stored verdict ("judge flagged
   13.5%") and the statistical interpretation ("estimated true rate ≈ 1%") coexist; we correct the
   *claim*, never the observation.

And it **refuses rather than fabricates** when the judge is not identifiable — `TPR̂ ≤ FPR̂` or an empty
calibration cell returns "not identifiable," not a confident number from nonsense parameters. That
distinction — observation vs. certified claim, with an explicit *un*-certifiable case — is exactly what a
security reviewer wants and what most LLM-judge evaluations omit.

**Why this isn't "just apply the formula."** The reporting layer violates the clean textbook setup in
load-bearing ways, and the honest handling of each *is* the contribution: the calibration set and the
judge run are **different populations** (see [the headline reviewer risk](#the-headline-reviewer-risk-cross-population-transfer)),
which the tooling surfaces (`source: large_judge_run` vs `self_calibration_set`) rather than hides; the
judge's error profile is estimated from **small cells** (here n_M0 = 190 human-clean items), so the
calibration-set variance *dominates* the CI and must be carried, not dropped; and the same overlay must
attach to **heterogeneous judges** that all flow through one binary-axis report. The value is the
plumbing — and the honesty — that makes the guarantee real on live data, not the closed form.

---

## The problem

ROGUE's narrow semantic judges — redaction (`RedactionScore.leaked`), right-to-be-forgotten
(`RtbfScore.recovered`), user-safety (`UserSafetyScore.unsafe_fulfilled`), PII (`pii_semantic`), and the
agent-memory leakage/net-effect judges — each emit a binary breach/clean verdict. The reported rate is
the judge's raw positive fraction `R̂_J`. But an imperfect judge with true-positive rate `TPR < 1` and
false-positive rate `FPR > 0` makes `R̂_J` a **biased** estimate of the real breach rate `R_M`:

    E[R̂_J] = TPR·R_M + FPR·(1 − R_M)

At a *low* true rate the `FPR·(1 − R_M)` term dominates — the judge's false positives inflate the
number. So "the judge flagged 13% of trials" is **not** "13% of trials breached," and no honest
"X% leak rate" headline can ship off the raw fraction. This is why those judges are marked
**headline-blocked** in the build backlog: their precision at threshold was unknown.

## The method

Two published recipes fix this from the *same* small human-labelled calibration set `D_M` (which pins
the judge's error profile) applied to the large judge-labelled run `D_J`. We implement both.

**Judge error profile (from the 2×2 the harness already builds).** On the breach axis (positive =
breach), `TPR̂ = tp/(tp+fn)`, `FPR̂ = fp/(fp+tn)`, with calibration denominators `n_M1 = tp+fn`
(human-breach) and `n_M0 = fp+tn` (human-clean).

**Lee — de-biased point estimate + CI** (arXiv 2511.21140). The Rogan–Gladen inversion de-biases the
rate, and a delta-method plug-in variance yields a CI carrying *both* uncertainties:

    R̂  = clamp( (R̂_J − FPR̂) / (TPR̂ − FPR̂), 0, 1 )

    Var(R̂) = [ R̂_J(1−R̂_J)/n_J + R̂²·TPR̂(1−TPR̂)/n_M1 + (1−R̂)²·FPR̂(1−FPR̂)/n_M0 ] / (TPR̂ − FPR̂)²

    CI = R̂ ± z_{1−ζ/2} · √Var(R̂)      (clamped to [0,1])

**Feng — variance-corrected certification** (arXiv 2601.20913, ICLR 2026). To *certify* "the true rate
is below tolerance α," transform α into a judge-space threshold and compare `R̂_J` against a
variance-corrected critical value (their Eq. 6):

    α̂′  = FPR̂ + (TPR̂ − FPR̂)·α                                    (= TPR̂·α + FPR̂·(1−α))

    c′_J = α̂′ + Φ⁻¹(ζ) · √( α̂′(1−α̂′)/n_J
                            + α²·TPR̂(1−TPR̂)/n_M1
                            + (1−α)²·FPR̂(1−FPR̂)/n_M0 )

Reject `H₀: R_M ≥ α` (i.e. **certify** the model safe at tolerance α) iff `R̂_J < c′_J`. Feng's
Theorem 5.1 guarantees finite-sample Type-I error `≤ ζ + O(n_J^-1/2 + n_M1^-1/2 + n_M0^-1/2)` — the test
stays valid *despite* judge noise, because the three variance terms make it automatically more
conservative when calibration data is scarce (`Φ⁻¹(ζ) < 0`, so `c′_J` sits below α̂′ by exactly the
estimated standard error).

The two decompositions coincide: rederiving Lee's Eq. 19 in breach polarity by the delta method gives
the same three terms over the squared informativeness `D = TPR̂ − FPR̂` — a clean internal cross-check
that the point-estimate CI and the certification threshold rest on one variance model.

**Refusal, not fabrication.** When `D = TPR̂ − FPR̂ ≤ 0` (judge no better than random on this axis) or a
calibration cell is empty, the correction is undefined (Feng assumes TPR > FPR) and `1/D²` explodes the
variance; the module returns `informative=False` with a reason instead of a garbage number — the honest
analogue of the harness already returning `None` for an undefined FP-mode rate.

## Paper grounding (read in full via crawl4ai)

Both papers were fetched in full (`crwl crawl` → ar5iv markdown) and their load-bearing math verified
line-by-line against the code, per the "fact-check Elicit, never cite it" discipline:

- **Feng et al., "Noisy but Valid: Robust Statistical Evaluation of LLMs with Imperfect Judges"**
  (arXiv 2601.20913). Algorithm 1 + Eq. 5/6 + Theorem 5.1 verified verbatim: `α̂′ = TPR̂·α + FPR̂·(1−α)`,
  the three-term variance-corrected `c′_J`, and the `ζ + O(·)` Type-I bound. Experiments used
  `n_M=100, n_J=10,000, ζ=0.05, α=0.25` (Fig. 1) — our defaults (`α=0.20, ζ=0.05`) sit in the same
  regime. The framework is deliberately *not* PPI: it models the judge's error profile explicitly for
  interpretability, trading a little power for a diagnostic.
- **Lee et al., "How to Correctly Report LLM-as-a-Judge Evaluations"** (arXiv 2511.21140). Rogan–Gladen
  inversion (Eq. 18) + delta-method variance (Eq. 19, carrying both test- and calibration-set
  randomness) verified. Lee also gives an *adaptive calibration-allocation* rule (Prop. 2) — noted as a
  future refinement; we implement the plug-in estimator + CI, which is the piece the reporting layer
  needs now.

The Elicit brief that seeded this was directionally right but, as everywhere, imprecise: it sold
Ferrer's low ECE as a "precision guarantee" (only Feng/Lee actually deliver one) and carried two
author-name typos. The verified recipe above is Feng/Lee, not the brief.

## Wiring — real, in both binary-axis report surfaces

Off by default, byte-identical when off, no new dependency (`statistics.NormalDist` gives Φ/Φ⁻¹):

- `src/rogue/reproduce/calibration/noise_corrected.py` — the pure math + env-config resolver +
  `build_report_block` formatter. `BinaryCalibrationReport.noise_corrected(...)` is the reusable seam
  (derives TPR̂/FPR̂ from the report's own 2×2; self-applies on the calibration set when no large run is
  supplied, tagged as a demonstration).
- `scripts/calibration/calibrate_breach_type.py` — runner #1 (information-disclosure /
  unauthorized-action / redaction / RTBF / user-safety / PII). `--noise-judge-positive`/`--noise-n-judge`
  supply the large `D_J`; the `noise_corrected` block is added to `<type>_report.json` **only** when the
  flag is on.
- `scripts/memory/calibrate_memory_judge.py` — runner #2 (agent-memory leakage / net-effect judges),
  same additive pattern.
- `scripts/calibration/replay_noise_corrected.py` — the $0 validator: `D_M` = the harm judge's released
  300-item human set, `D_J` = the `breach_results` table.

Both runners were driven end-to-end with the flag on and off: off ⇒ the report JSON has **zero** extra
keys (a field-by-field diff confirms every shared key byte-identical); on ⇒ exactly one added
`noise_corrected` block. Captured as a runner regression test.

## Measured results (offline, $0)

Replaying the overlay over data already paid for, on the harm breach axis:

| quantity | value |
|---|---|
| `D_M` (JBB-300 human vs judge) | tp=107, fp=24, fn=3, tn=166 |
| TPR̂ | 0.973 (n_M1 = 110) |
| FPR̂ | 0.126 (n_M0 = 190) |
| `D_J` (breach_results) | 1,679 judge-breach / 12,452 substantive → raw **R̂_J = 13.5%** |
| **noise-corrected rate** | **1.0%  [95% CI 0.0%, 6.6%]** |
| certification (α=0.20, ζ=0.05) | **CERTIFIES** rate < 20% (R̂_J 0.135 < c′_J 0.263) |

The headline, stated carefully (the strong phrasing depends on the transfer assumption below):
**under the estimated judge error profile, the large majority of observed positives are attributable to
the judge's false-positive floor** (FPR̂ = 12.6%) rather than to real breaches. The de-biased true breach
rate is ~1%, and the CI's width is set almost entirely by the calibration-set uncertainty (n_M0 = 190) —
a live demonstration of Feng's "Oracle Gap" (scarcer calibration ⇒ wider interval). This is exactly the
low-true-rate upward bias Feng/Lee warn about, measured on real data — and it is not a minor correction:
a judge with a 10% FPR reporting an 11% raw rate can make a system with a **1% true breach rate look 10×
worse**.

## The headline reviewer risk: cross-population transfer

This is the assumption the whole certification rests on, and the first thing a careful reviewer will
attack: **the correction assumes the judge's error profile (TPR̂/FPR̂) is stable between the calibration
population and the deployment population.** In the $0 replay it is *not* the same population — `D_M` is
the JBB adversarial-harmful set, `D_J` is ROGUE's own reproduction corpus — so the estimated FPR̂ = 12.6%
is transferred across a distribution shift. The replay therefore validates the *pipeline* and the
*order of magnitude* of the correction, **not** a certified per-judge number. The tooling tags `source`
(`self_calibration_set` vs `large_judge_run`) precisely so this is never mistaken for a shipped headline.

**The experiment that removes the attack — population-matched calibration.** Draw the calibration set
from the *same* population as the judge run: take ~100 ROGUE-generated reproduction examples, human-label
them, and estimate `FPR̂_ROGUE` on that distribution. Two outcomes, both valuable:

- **If `FPR̂_ROGUE ≈ FPR̂_JBB` (≈12.6%)** → the transfer assumption holds empirically, and the per-judge
  certification ships with its central objection answered.
- **If they differ materially** → that is *itself a finding*: **LLM-judge reliability is
  distribution-dependent** — the same judge has a different false-positive floor on adversarial-harmful
  prompts vs. reproduction traffic — which is a publishable result about judge robustness in its own
  right (and a caution for every LLM-judge evaluation that calibrates on one distribution and deploys on
  another).

Either way the population-matched pass converts the headline risk into either a hardened claim or a new
finding. This is the live experiment below.

## Other caveats

- **This does not touch the harm judge model.** We deliberately do not shrink or replace the main breach
  grader; we de-bias a *reported rate*. The stored verdicts, trials, and costs are unchanged.
- **α and ζ are policy choices.** `α` is the tolerance you certify against ("we claim rate < α"); `ζ` is
  the one-sided Type-I level (and sets the 1−ζ CI). Defaults `α=0.20, ζ=0.05` are deliberately loose so
  a certify/no-certify decision is meaningful on ROGUE's low-single-digit rates; each judge should pick
  its own α from its policy.
- **The CI is Wald plug-in.** For very small calibration cells Lee's Agresti-style pseudo-count
  adjustment improves coverage; noted as a refinement. The refusal guard covers the degenerate cases the
  plug-in can't.

## The live experiment (the gated arm)

The shipped per-judge headline for each headline-blocked narrow judge needs, per judge: **~100 human
labels drawn from the judge's own population** (the population-matched calibration above; reuse
`sample_calibration_set.py`) → TPR̂/FPR̂ *on the deployment distribution*, plus **one judge-only paid
pass** over a large unlabelled set from the same population → `R̂_J`, `n_J`. Then the overlay emits
"corrected leak X% [CI], certifies < α at ζ=0.05" per judge. Cost is dominated by the human labelling
(free but real effort); the judge pass is one modest paid run per judge, foldable into the queued paid
session, and tracked as a gated paid arm. This single arm both **ships the per-judge certification** and
**settles the cross-population question** — the same ~100 labels that certify also reveal whether the
judge's error profile is distribution-stable.

## Where this sits — the measurement-validity layer of the evaluation loop

Q4 is not a standalone feature; it is the third of three orthogonal budget/validity controls, and the one
that makes the other two *trustworthy* rather than merely *efficient*:

| control | question it answers | failure mode it fixes |
|---|---|---|
| **survival ranking** (Q11) | *which* attacks to test first | wasting budget on attacks that won't transfer |
| **SPRT early-stopping** (Q6) | *how many* trials each attack gets | over-sampling obvious outcomes |
| **noise-corrected certification** (Q4) | *how accurate is the judge* | trusting a raw rate the judge's own noise inflated |

Q11 and Q6 make the evaluation cheaper; **Q4 makes the number it produces defensible.** As one system —
`harvest → survival-rank → SPRT-stop → judge → noise-corrected certification → trustworthy security
claim` — the three compose into a complete, budget-aware, statistically-valid evaluation lifecycle. Q4 is
the piece that turns "efficient red-team benchmark" into "*certifiable* red-team benchmark."

## Venue fit

As a security-measurement contribution (standalone or as the certification module of the combined
system): **USENIX Security** is the strongest fit — false alarms, certification, and measurement validity
are core concerns there — with **ACM CCS** and **NDSS** also strong ("reliable automated security
evaluation of LLM systems"). **IEEE S&P** is possible but would want broader validation (more judges,
more domains). **NeurIPS/ICML are a weak fit**: the statistics are not the ML novelty, and an ML reviewer
fixates on "the formula already exists" — exactly the framing this document avoids. Novelty is the
*integration* (validity guarantee + live benchmark + heterogeneous judges + production reporting), not
the estimator.

## Summary

A **certification layer** for LLM-judge rates — not a new estimator, but the plumbing and the honesty
that make a *certified* security claim fall out of a live red-team benchmark's existing outputs, over
judge runs already paid for, off by default and additive so no historical number moves. The $0 replay
shows the correction is not cosmetic: a raw 13.5% breach rate de-biases to ~1% once the judge's own 12.6%
false-positive floor is accounted for — the difference between an alarming number and a defensible one.
The one thing standing between the demonstration and a shipped per-judge certification is a single
population-matched calibration pass, which doubles as the experiment answering the method's central
objection.
