# Noise-corrected calibration — de-biasing a judge-labelled breach rate (Q4)

**One line.** Every breach rate ROGUE reports off an LLM judge is the judge's *raw* positive
fraction; when the judge has a non-zero false-positive rate that number is biased *upward* exactly in
the low-true-rate safety regime. This overlay estimates the judge's TPR̂/FPR̂ from the existing
human-labelled calibration set and (a) **de-biases** the reported rate with a confidence interval that
folds in both the test-run and the calibration-set uncertainty, and (b) emits a finite-sample
**certification** verdict ("true breach rate < α, Type-I ≤ ζ") — so a headline number can finally ship
off the previously-uncalibrated judges.

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

**Contribution.** The statistics are Feng's and Lee's (both 2025–26). What's new here is the *systems*
adaptation: making finite-sample noisy-judge certification run **inside a live red-team benchmark's
reporting layer, over judge runs already logged, without moving a single stored verdict**. Concretely:
(1) the correction reads the *same* 2×2 the calibration harness already computes
(`AxisAgreement` → TPR̂/FPR̂) — no new labelling pipeline; (2) it treats the existing `breach_results`
table as the large judge-labelled set `D_J`, so the de-bias is estimable **$0 over historical traces**;
(3) it splices into both report runners as a **purely additive** block — a report written with the flag
off is byte-identical to today, so every historical calibration artifact stays comparable; and (4) it
**refuses rather than fabricates** when the judge is not usefully better than random on an axis
(TPR̂ ≤ FPR̂) or a calibration cell is empty. The recipe is off-the-shelf; the work is wiring a
validity guarantee into an operating benchmark without disturbing the numbers it already reports.

**Why this isn't "just apply the formula."** The reporting layer violates the clean textbook setup in
load-bearing ways: the calibration set and the judge run are **different populations** (the human labels
were collected on a curated set; the judge run is the live reproduction corpus), so TPR̂/FPR̂ transfer is
an explicit, stated assumption the tooling surfaces (`source: large_judge_run` vs `self_calibration_set`)
rather than hides; the judge's error profile is estimated from **small cells** (here n_M0 = 190
human-clean items), so the calibration-set variance *dominates* the CI and must be carried, not dropped;
and the same overlay must attach to **heterogeneous judges** (redaction / RTBF / user-safety / PII /
agent-memory) that all flow through one binary-axis report. The value is the plumbing that makes the
guarantee real on live data, not the closed form.

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

The headline: **roughly twelve of every thirteen "breaches" the judge flags across ROGUE's reproduction
population fall within the judge's own false-positive floor** (FPR̂ = 12.6%). The de-biased true breach
rate is ~1%, and the CI's width is set almost entirely by the calibration-set uncertainty (n_M0 = 190) —
a live demonstration of Feng's "Oracle Gap" (scarcer calibration ⇒ wider interval). This is exactly the
low-true-rate upward bias Feng/Lee warn about, measured on real data.

## Caveats

- **Cross-population transfer is an assumption, not a result.** In the $0 replay, `D_M` is the JBB
  adversarial-harmful calibration set while `D_J` is ROGUE's own reproduction population. TPR̂/FPR̂
  estimated on the former are applied to the latter. The replay validates the *pipeline* and the
  *magnitude* of the correction; a shipped per-judge certification needs a calibration set drawn from
  the same population as the judge run. The tooling tags `source` so a reader never mistakes the demo
  for a headline.
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
labels** on a set drawn from the judge's own population (reuse `sample_calibration_set.py`) → TPR̂/FPR̂,
plus **one judge-only paid pass** over a large unlabelled set from the same population → `R̂_J`, `n_J`.
Then the overlay emits "corrected leak X% [CI], certifies < α at ζ=0.05" per judge. Cost is dominated by
the human labelling (free but real effort); the judge pass is one modest paid run per judge, foldable
into the queued paid session, and tracked as a gated paid arm (one judge-only pass per judge).

## Summary

A validity guarantee for LLM-judge rates, wired into ROGUE's reporting layer over judge runs it already
paid for, off by default and additive so no historical number moves. The $0 replay shows the correction
is not cosmetic: a raw 13.5% breach rate de-biases to ~1% once the judge's own 12.6% false-positive
floor is subtracted — the difference between an alarming headline and a true one.
