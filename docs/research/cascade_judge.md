# Confidence-gated cascade judge (Q2)

**One line.** Grade every trial with ROGUE's free regex `HeuristicJudge` first and escalate to the paid
calibrated LLM `JudgeAgent` only when the cheap tier isn't a confident *non-breach* — so a paid scan
stops paying a frontier model to read the flat refusals that make up the safe majority of trials, **and
the benchmark's breach metric is provably unchanged.**

**Status.** Built + wired into the three default judge-construction surfaces (`run_scan`,
`scan_endpoint`, `reproduce_once`), off by default in code. **Live in production** since 2026-07-08
(`ROGUE_CASCADE_JUDGE=on` on the Render API+worker), so customer scans already cascade. Offline-validated
by replaying the cascade over ROGUE's existing `breach_results` ($0, read-only, on Neon): at the safe
default gate **18.4% of paid judge calls saved at 99.8% agreement** with the calibrated verdict (95% CI
99.5–99.9%, n=12,452), rising to **46.5% saved at a certified ≥95% agreement floor**. A live dollar/latency
headline needs one gated ~$35 A/B — but note (below) the offline number is already close to decisive here.

Code: `src/rogue/reproduce/cascade_judge.py` · replay validator: `scripts/reproduce/replay_cascade.py` ·
tests: `tests/test_cascade_judge.py` · env flag: `ROGUE_CASCADE_JUDGE`.

## Contribution

Existing LLM-judge cascades optimize **inference cost**: grade with a cheap model, escalate to an
expensive one when the cheap one is unsure (Ramírez 2405.02134; Jung 2407.18370). A *security benchmark*
carries an additional constraint those methods never face: **the benchmark's headline metric — the breach
rate — must remain invariant.** A cascade that occasionally lets the cheap tier assert a breach would
silently rewrite the number the whole system exists to report.

Q2 is the adaptation that satisfies that constraint, in three moves:

1. **Asymmetric escalation (the security-specific core).** A generic cascade short-circuits whenever the
   cheap tier is *confident, in either direction*. Ours short-circuits **only on a confident non-breach**;
   any breach signal from the free tier is *always* escalated to the calibrated judge before it can count.
   So the free tier can never *add* a breach — the reported breach rate is, by construction, exactly what
   running the calibrated judge on every trial would produce. The cascade moves cost, not verdicts.

   ```text
   generic cascade                 ROGUE cascade (asymmetric)
   ───────────────                 ──────────────────────────
   cheap model                     heuristic
     confident? → answer             confident SAFE?  → stop        (bank the saving)
     else       → expensive          says BREACH?     → escalate    (never assert a breach free)
                                      unsure?          → escalate
   ```

2. **A $0 cheap tier.** ROGUE's cheap tier is a network-free regex, not a smaller *paid* model — so the
   structural floor on cascade savings (Bouchard: you always pay the cheap model before deciding) is
   literally zero here. Every short-circuit removes a full judge call for nothing.

3. **A transparent adapter across benchmark stages.** Existing cascades assume interchangeable
   evaluators; ROGUE's heuristic and calibrated judges expose different interfaces and execution
   semantics, so the cascade wraps them behind one interface that preserves compatibility across every
   stage that consumes a judge (the default scan, the endpoint/persist path, the paid research arm, and
   the deep PAIR/escalation stages that reach into judge internals).

**Where it sits in the system.** Q2 is one of four orthogonal resource controls in ROGUE's evaluation
loop, each governing a different budget:

| Module | Governs | Question it answers |
|---|---|---|
| Survival (Q11) | attack budget | *which* attacks deserve evaluation? |
| SPRT (Q6) | sampling budget | *how many* trials per evaluated attack? |
| **Cascade (Q2)** | **judge budget** | *which trials* actually need the expensive judge? |
| Noise-correction (Q4) | measurement validity | can we *trust* the resulting breach rate? |

Q11/Q6/Q2 are efficiency controls sharing the reproduce panel; Q4 is a validity control on the judge
output. Q2 completes the cost story: without it the system chooses which attacks and how many trials but
still pays the frontier judge on every trial.

## Why a regex cheap tier is enough

The asymmetry isn't just a safety rail — it's matched to what the cheap tier is actually good at. A safe
generation is overwhelmingly a *refusal*, and refusals are **semantically narrow**: "I can't help with
that.", "I'm not able to assist with that request.", a short deflection. A regex is excellent at these —
high precision, near-zero miss. A *breach*, by contrast, is **semantically diverse** — synthesis steps,
exploit code, operational detail, in any domain — exactly where a regex is weak. So the heuristic has
**high precision on refusals and poor precision on breaches**, which is precisely the profile the
asymmetric cascade exploits: let the regex settle the thing it's reliable at (confident refusals),
escalate everything else. The measured 99.8% agreement on the short-circuited set is that profile showing
up in the data.

**"Why not a small LLM instead of a regex?"** A small LLM still costs money, still adds latency, still
needs an API call, and still introduces another model dependency to version and calibrate. The regex is
deterministic, zero-latency, zero-network, and $0 — and for the one job it's assigned (recognising a
confident refusal) it is strong. Ramírez's own finding is that the cheap tier's *own* signal beats a
trained router; here the cheap tier is cheaper still, with no signal to train.

## The gate and its calibration

Short-circuit — return the heuristic verdict, no LLM call — **iff** `confidence ≥ τ` **and**
`verdict ∉ {PARTIAL_BREACH, FULL_BREACH}`; otherwise escalate. `τ` (`ROGUE_CASCADE_TAU`, default **0.7**,
the heuristic's confidence cap) starts refusal-only; lower it to bank confident evasions once the
agreement is certified.

`calibrate_tau` is the principled gate-picker (Jung's fixed-sequence-testing idea): over a labelled set
of `(heuristic_confidence, heuristic_is_breach, reference_is_breach)` triples it sweeps candidate gates
high→low and returns the *lowest* gate whose short-circuit agreement's **Wilson lower bound** still clears
the target — maximum savings at a certified agreement floor (never a silent fallback).

## Offline validation ($0) — the savings/agreement tradeoff

`scripts/reproduce/replay_cascade.py` re-grades every un-redacted `breach_results` row with the free
heuristic and reports, per `τ`, the fraction of LLM-judge calls skipped and the skipped verdicts'
agreement with the stored calibrated verdict. Over **12,452 rows** (LLM-labelled breach rate 13.5%):

```text
agreement
 100% ┤
      │        ● 0.62 (τ=0.62)   ● 0.70 (τ=0.70)
99.8% ┤          ╲______________●
      │                          (refusal-only: 18.4% saved, 99.8% agree)
      │
      │   ● 0.50
95.6% ┤    ╲
      │     ╲__________________________________
      │      (also grade confident evasions: 46.5% saved, 95.6% agree, ≥95% certified)
      └────┬─────────┬─────────┬─────────┬──────
          20%       30%       40%       50%
                    LLM judge calls saved
```

| τ | LLM calls saved | agreement @ saved | 95% CI |
|---:|---:|---:|---:|
| 0.70 (default) | 18.4% | 99.8% | 99.5–99.9% |
| 0.60 | 19.0% | 99.5% | 99.1–99.7% |
| 0.50 | 46.5% | 95.6% | 95.1–96.1% |

`calibrate_tau` certifies **τ=0.50 → 46.5% saved at a ≥95% agreement floor** (Wilson floor 95.1%,
n=5,789). The default banks ~18% at near-perfect agreement; the knob trades a small certified agreement
drop for ~2.5× the savings.

## On "agreement" — and the residual-error question

Agreement here is measured against the calibrated judge's *own* stored verdict, so the obvious reviewer
question is: **what if the calibrated judge is itself wrong?** Q2 does not try to answer that — and
shouldn't. It has one job: don't move the benchmark relative to running the calibrated judge everywhere.
It provably meets that (asymmetry) and near-perfectly matches it on the trials it grades free (99.8%).
The judge's *own* residual error is a separate axis, handled independently by the **Q4 noise-corrected
certification layer**, which de-biases the calibrated breach rate against the judge's measured TPR̂/FPR̂
and emits a finite-sample certified claim. So the division of labour is clean: **Q2 preserves the
calibrated judge's verdicts cheaply; Q4 bounds that judge's error.** Neither is asked to do the other's
job.

## The live experiment (folds into the paid session, $0 extra)

Unlike SPRT (which can barely early-stop over ROGUE's shallow historical cells) and survival (whose
offline back-test is on only 8 configs), **Q2's offline replay is already close to decisive** — 12,452
real rows, a directly-measured agreement, and a savings that is a deterministic function of the fixed
heuristic. The live A/B therefore mostly *confirms* rather than *proves*: it measures the realised
**dollar** savings, the **latency** reduction, and that there are **no unexpected interactions** with
the SPRT/survival controls when all three run together. It rides the same gated paid session as those
efficiency arms at ~$0 extra — toggle `ROGUE_CASCADE_JUDGE` on the relevant cells of the shared
factorial. Until it lands, the headline stays "offline replay," not a live dollar figure.

## Caveats

- **Offline, not yet live-measured.** The replay is a backtest; "agreement" is consistency with the
  calibrated judge's stored verdict, not ground truth. Live dollar/latency confirmation is a gated paid A/B.
- **Redacted local DB.** The docker snapshot is `model_response='[redacted]'`, so the replay reads Neon
  (reads are $0 — no LLM calls).
- **Prod-only flag.** Live-on in prod (Render); local `reproduce_once` runs cascade only if
  `ROGUE_CASCADE_JUDGE=on` is exported in that shell (kept out of `.env` so the test suite stays
  byte-identical-off — matching how `ROGUE_SPRT`/`ROGUE_SURVIVAL` are handled).
- **Heuristic quality caps savings.** Only confidently-graded trials short-circuit; a softer refusal the
  LLM still calls "refused" won't reach the gate. Improving the heuristic's refusal recall raises the
  savings directly — a cheap future lever.

## Venue fit

A systems/measurement optimization for security benchmarks, not an ML paper — strongest at **USENIX
Security** (excellent fit) and **NDSS** (very good); **CCS** good. **IEEE S&P** would want a broader
measurement story than Q2 alone provides. Q2 lands most naturally as the **judge-allocation** component
of the combined efficiency paper (**Q11 + Q6 + Q2** — *"Adaptive Budget-Aware Red-Team Evaluation"*: which
attacks, how many trials, which judges), with Q4 as a sibling **measurement-validity** paper.

## Grounding (read in full via crawl4ai)

- **Ramírez, "Optimising Calls to LLMs with Uncertainty-Based Two-Tier Selection"** (arXiv 2405.02134,
  CoLM 2024) — the decision criterion should be the cheap tier's *own* confidence, not a trained router
  (wins 25/27 setups). Grounds gating on the heuristic's confidence.
- **Jung, Brahman, Choi, "Trust or Escalate"** (arXiv 2407.18370, ICLR) — Cascaded Selective Evaluation;
  pick the gate by fixed-sequence testing for a provable agreement floor; cascade cuts API cost ~40% vs
  always-GPT-4 (Table 5; ChatArena coverage 63.2% at target agreement 0.85, Table 3). We take the
  threshold-calibration idea but **not** their *Simulated Annotators* confidence measure — it runs N
  in-context LLM personas, i.e. adds model calls, defeating a free cheap tier.
- Elicit fact-check: the brief inflated Jung's coverage to "~80%" (real 63.2% at 0.85, per Table 3) and
  over-counted "five independent studies"; the directional claim held. Elicit is a lead, never a citable
  source.
