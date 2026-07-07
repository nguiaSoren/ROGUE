# Confidence-gated cascade judge (Q2)

**One line.** Grade every trial with ROGUE's free regex `HeuristicJudge` first and escalate to the paid
calibrated LLM `JudgeAgent` **only** when the heuristic isn't confident enough to stand alone — so a
paid scan stops paying a frontier model to read the flat "I can't help with that." refusals that make up
the safe majority of trials, and spends the LLM judge exactly where the verdict is ambiguous.

**Status.** Built + wired into the three default judge-construction surfaces (`run_scan`, `scan_endpoint`,
`reproduce_once`), off by default. Offline-validated by replaying the cascade over ROGUE's existing
`breach_results` ($0, read-only, on Neon where the response text is un-redacted): at the safe default
gate **18.4% of paid judge calls saved at 99.8% agreement** with the LLM judge's own stored verdict
(95% CI 99.5–99.9%, n=12,452), scaling to **46.5% saved at a certified ≥95% agreement floor** when the
gate is lowered to also grade confident evasions free. A *live* budget-saved headline on a fresh scan
needs one gated ~$35 reproduce cycle (see [Caveats](#caveats)).

Code: `src/rogue/reproduce/cascade_judge.py` · replay validator: `scripts/reproduce/replay_cascade.py` ·
tests: `tests/test_cascade_judge.py` · env flag: `ROGUE_CASCADE_JUDGE`.

**Contribution.** Confidence-gated cascades are Jung's (*Trust or Escalate*) and Ramírez's
(*Uncertainty-Based Two-Tier Selection*). What's new here is the *systems* adaptation — making a
cheap→expensive judge cascade work inside a **live red-team benchmark whose cheap tier costs nothing and
whose metric must not move**. Concretely: (1) the cheap tier is a **$0 network-free regex**, not a
smaller *paid* model, so every short-circuit removes a full judge call for zero marginal cost — the
cascade's own overhead, which Bouchard flags as the structural floor on cascade savings, is literally
zero here; (2) an **asymmetric escalation rule** specific to red-teaming — the free tier may stand alone
only on a confident *non-breach*; any breach signal is *always* re-graded by the calibrated judge, so the
headline breach rate is provably never moved by the cheap tier; (3) a **transparent-proxy** wrapper that
presents the `JudgeAgent` interface and forwards every other attribute to the wrapped judge, so it drops
into the deep PAIR/escalation stages untouched; and (4) a **replay methodology** — running the cascade
over historical judge traces to estimate its call-saving *and* its agreement-with-the-expensive-judge at
$0, before any paid experiment. The gate itself is textbook selective classification; the work is
adapting it to a judge-in-the-loop pipeline without disturbing the numbers it already reports.

**Why this isn't "just cascade the judges."** ROGUE's two graders have **incompatible call signatures**
(`HeuristicJudge.judge_sync(attack_prompt: str, …, goal)` vs
`JudgeAgent.judge(rendered: RenderedAttack, …, primitive)`) and the heuristic has no async `judge()` at
all — so a naive `--judge heuristic|calibrated` toggle can pick one but cannot *cascade* them. The
cascade has to (a) reconcile those signatures behind one interface, (b) proxy the `JudgeAgent` internals
that the deep stages and `JudgeBatch` reach for, and (c) splice into every path that builds a default
judge — the default `rogue scan`/SDK (`run_scan`), the endpoint/persist path (`scan_endpoint`), and the
paid research arm (`reproduce_once`) — off by default and byte-identical to today when off. An
off-the-shelf two-LLM cascade satisfies none of these.

---

## The mechanism

Each trial is graded in two tiers:

1. **Cheap tier ($0).** `HeuristicJudge.judge_sync(attack_text(rendered), model_response, goal)` — a
   deterministic, network-free regex grader that returns the *same* `JudgeResult` (verdict / rationale /
   confidence) the LLM judge returns, with confidence capped at 0.7.
2. **Gate.** Short-circuit — return the heuristic verdict, no LLM call — **iff** the heuristic is a
   confident *non-breach*: `confidence ≥ τ` **and** `verdict ∉ {PARTIAL_BREACH, FULL_BREACH}`. Otherwise
   escalate to the calibrated `JudgeAgent`.
3. **Expensive tier.** `await JudgeAgent.judge(rendered, model_response, primitive)` — today's calibrated
   v3 judge, unchanged, on exactly the ambiguous trials.

`τ` (`ROGUE_CASCADE_TAU`, default **0.7**) is the confidence gate — Jung's `λ`, Ramírez's uncertainty
criterion. At the default it short-circuits only the heuristic's top confidence bucket (an explicit
refusal); lower it to also bank the confident-evasion trials once [`calibrate_tau`](#calibrating-τ)
certifies the agreement holds.

### The asymmetry (the safety rail)

A red-team's costly error is a *missed* breach, and a regex is far more trustworthy at recognising an
explicit refusal than at confirming a real breach. So `escalate_on_breach` (default **on**) forbids the
free tier from ever *asserting* a breach: a heuristic breach — however confident — is always confirmed by
the calibrated judge before it can count. The consequence is load-bearing: **the breach rate is exactly
what today's calibrated judge would report**; the cascade only ever converts confident *non-breach*
grades to $0. The savings ride entirely on the safe majority, and the metric that matters is untouched.

## Surfaces

Wired at the three sites that construct a **default** judge; an *injected* judge (the `public_scan`
visitor-key judge, `--judge heuristic`, tests) is deliberately left untouched — the cascade only wraps
the default:

| Surface | Path | Cascade |
|---|---|---|
| `scan.py::run_scan` | default `rogue scan` + SDK | wraps default `JudgeAgent` |
| `endpoint_scan.py::scan_endpoint` | public API / `--persist` / retest | wraps default `JudgeAgent` |
| `reproduce_once.py::run_reproduction` | paid research arm | wraps default; **inert on `--judge-batch`** |

The deep stages (PAIR, escalation, search, domain-jargon) **inherit** the judge `run_scan` builds and
only ever call `judge.judge(...)`, so they get the cascade for free through the transparent proxy — no
separate wiring. Two paths are intentionally *not* cascaded: `JudgeBatch` (`--judge-batch`) grades the
full fixed `n` in one API batch, so there's no per-trial cheap-first decision to make (it keeps the raw
`JudgeAgent`, whose internals it reaches into); and `generator_sweep.live_trial_fn` grades through a thin
`(payload, response) → bool` closure that carries no confidence for the gate to read.

## Calibrating τ

`calibrate_tau(items, target_agreement)` is the Jung *fixed-sequence-testing* bolt-on ($0, offline): over
a labelled set of `(heuristic_confidence, heuristic_is_breach, reference_is_breach)` triples it sweeps
candidate gates high→low, and for each measures the short-circuit set's agreement with the reference and
takes its **Wilson lower bound** as a finite-sample certified floor. It returns the *lowest* gate (⇒ most
savings) still certified at the target — maximum savings at a guaranteed agreement — or, if none
certifies, the best-effort gate with its numbers exposed (never a silent fallback). The replay validator
runs this against the real corpus.

## Offline validation ($0)

`scripts/reproduce/replay_cascade.py` re-grades every un-redacted `breach_results` row with the free
heuristic and, for a sweep of `τ`, reports the fraction of LLM-judge calls the cascade would skip and the
skipped verdicts' agreement with the stored calibrated verdict. Over **12,452 rows** (LLM-labelled breach
rate 13.5%):

| τ | LLM calls saved | agreement @ saved | 95% CI |
|---:|---:|---:|---:|
| 0.70 (default) | 18.4% | 99.8% | 99.5–99.9% |
| 0.60 | 19.0% | 99.5% | 99.1–99.7% |
| 0.50 | 46.5% | 95.6% | 95.1–96.1% |

`calibrate_tau` certifies **τ=0.50 → 46.5% saved at a ≥95% agreement floor** (Wilson floor 95.1%,
n=5,789). The safe default (τ=0.70) banks ~18% at near-perfect agreement; the tunable knob trades a small
certified agreement drop for ~2.5× the savings.

## Caveats

- **Offline, not live.** The replay is a backtest over rows we already paid to grade; "agreement" is
  agreement with the calibrated judge's *own stored verdict*, i.e. consistency, not ground truth. The
  live prospective savings % on a fresh paid scan — and the confirmation that the breach rate is
  unchanged end-to-end — need one gated ~$35 reproduce cycle. It can share the paid session with the
  SPRT/survival arms (they're orthogonal: SPRT cuts *trials per cell*, survival cuts *cells fired*, the
  cascade cuts *judge cost per trial*).
- **Redacted local DB.** The docker snapshot has `model_response='[redacted]'`, so the replay must read
  Neon (reads are $0 — no LLM calls).
- **Agreement is against a black-box judge.** ROGUE's calibrated judge is itself imperfect; the cascade
  inherits its verdicts on escalated trials by construction and matches them on short-circuited ones to
  the measured floor. This composes with the Q4 noise-corrected certification, which bounds the judge's
  own error separately.
- **Heuristic quality caps the savings.** Only trials the regex grades *confidently* short-circuit; a
  softer/lecturing refusal the LLM still calls "refused" won't reach the gate. Improving the heuristic's
  refusal recall would raise the savings directly — a cheap future lever.

## Grounding (read in full via crawl4ai)

- **Ramírez, "Optimising Calls to LLMs with Uncertainty-Based Two-Tier Selection"** (arXiv 2405.02134,
  CoLM 2024) — the decision criterion should be the cheap tier's *own* confidence, not a trained router;
  a bare uncertainty gate wins 25/27 setups. Grounds gating directly on the heuristic's confidence.
- **Jung, Brahman, Choi, "Trust or Escalate"** (arXiv 2407.18370, ICLR) — Cascaded Selective Evaluation;
  pick the gate by fixed-sequence testing on a small labelled set for a provable agreement floor; their
  cascade cuts API cost ~40% vs always-GPT-4 (Table 5; ChatArena coverage 63.2% at target agreement 0.85,
  Table 3). We take the threshold-calibration idea but **do not** port their *Simulated Annotators*
  confidence measure — it runs N in-context LLM personas, i.e. it *adds* model calls, defeating a cascade
  whose whole premise is a free cheap tier.
- Elicit fact-check: the brief inflated Jung's coverage to "~80%" (real 63.2% at 0.85 agreement, per the
  paper's Table 3) and over-counted "five independent studies"; the directional claim held. Elicit is a
  lead, never a citable source.
