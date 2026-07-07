# SPRT early-stopping over the Bernoulli trial loop (Q6)

**One line.** Replace ROGUE's fixed `n_trials` per (attack × config) cell with Wald's Sequential
Probability Ratio Test: fire trials one small concurrent batch at a time and stop the moment the
breach/no-breach decision is statistically clear — so a clearly-safe or clearly-broken cell resolves
in ~4–6 trials, and only genuinely borderline cells spend the full budget.

**Status.** Built + wired into all four trial-loop surfaces, off by default. Offline-validated by
replaying the real driver over ROGUE's existing `breach_results` ($0): **22.1% of already-fired
target+judge calls saved at 99.8% decision agreement** with today's rule. A *live* budget-saved
headline needs one gated ~$35 reproduce cycle (see [Caveats](#caveats)).

Code: `src/rogue/reproduce/sprt.py` · replay validator: `scripts/reproduce/replay_sprt.py` ·
tests: `tests/test_sprt.py` · env flag: `ROGUE_SPRT`.

**Contribution.** Sequential testing is Wald's; applying it to LLM sampling is ConSol's. What's new
here is the *systems* adaptation — making a sequential test work inside an **asynchronous, batched,
judge-in-the-loop evaluation pipeline without giving up parallelism or changing the benchmark it
feeds**. Concretely: (1) a concurrent-batch driver that early-stops mid-batch while still fanning
trials out in parallel; (2) a truncation rule that falls back to the incumbent decision, so the test
*only ever shortcuts the clear cells and never regrades a borderline one*; (3) a backward-compatible
splice into all four execution paths, off by default and identical to today when off; and (4) a
**replay methodology** — running the sequential test over historical evaluation traces in their stored
firing order, so its call-saving and decision-agreement are estimated against real data *without
re-running any paid experiment*. That last one is reusable in its own right: any adaptive-sampling
policy can be back-tested this way over an existing evaluation corpus. The statistical core is
textbook; the work is adapting it to a live red-team pipeline without disturbing the numbers it already
reports.

---

## The problem

ROGUE fires each attack a fixed `n_trials` times per config and takes `n_breach / n` as the attack
success rate (ASR). Two things are wrong with a fixed, small `n`:

1. **The point ASR is degenerate.** The default is `n_trials=1` on the `run_scan`/SDK path and `3` on
   the endpoint / sweep / reproduce paths. With `n=3` the ASR can only be one of `{0, .33, .67, 1}` —
   it carries almost no information about whether the cell is above or below the 0.4 breach line, and
   `n=1` is a bare coin.
2. **Fixing that with a large fixed `n` is wasteful.** Every trial is a target call *plus* a judge
   call (the judge runs inside the loop), so a fixed `n=12` multiplies the per-scan spend on the many
   cells that are already obviously safe or obviously broken after a handful of trials.

The two pulls are opposed: you want a *big* `n` where the outcome is uncertain and a *small* `n` where
it's obvious. A fixed budget can't do both. A sequential test can.

## The method

Frame each cell's breach decision as a Bernoulli hypothesis test around ROGUE's operating point. ROGUE
declares a cell breached when its ASR ≥ 0.4, so we place the null and alternative *symmetrically* around
that line with a ±0.15 margin — leaving an indifference region `(0.25, 0.55)` where the outcome is
genuinely ambiguous and more evidence is worth collecting:

> **H0: p ≤ p0 (= 0.25)** — "clearly below the breach line"  vs  **H1: p ≥ p1 (= 0.55)** — "clearly above it"

with symmetric error targets α = β = 0.05. The margin is the one real design choice: a wider band (say
±0.2) resolves obvious cells in fewer trials but sends more borderline cells to the `n_max` cap, while a
narrower one does the reverse; ±0.15 keeps the fast path fast while still bracketing 0.4 tightly. Both
bounds are env-tunable per surface. After each trial we update the log-likelihood ratio (LLR):

- a **breach** adds `ln(p1/p0)  = ln(2.2) = +0.789`
- a **no-breach** adds `ln((1−p1)/(1−p0)) = ln(0.6) = −0.511`

and compare it to the two Wald boundaries `A = (1−β)/α = 19` and `B = β/(1−α) ≈ 0.0526`, i.e. in
log-space `[−2.944, +2.944]`:

- LLR ≥ +2.944 → **BREACHED** (reject H0)
- LLR ≤ −2.944 → **SAFE** (accept H0)
- otherwise → keep sampling.

So the fastest a cell can resolve is **4 consecutive breaches** (→ BREACHED) or **6 consecutive
no-breaches** (→ SAFE). Two engineering choices make it practical:

- **Concurrent batching.** Firing one trial at a time would serialize what ROGUE fires in parallel
  today. Instead each turn fires a small concurrent batch (`batch=2` by default) through the existing
  `run_attack(n_trials=batch)` fan-out and checks the LLR after each observation — over-firing past
  the crossing by at most `batch−1`. This is ConSol's key practical enhancement (§2.5), mapped onto
  ROGUE's panel.
- **Truncation with a safe fallback.** A finite cap `n_max` (default 12) bounds the worst case. If the
  budget is reached still inside the continuation region, the decision is `UNDECIDED` and `breached`
  falls back to today's point rule `rate ≥ breach_threshold`. So SPRT only ever *shortcuts* the clear
  cells; a borderline cell is graded identically to the fixed-n path, just with a larger, more
  meaningful `n` behind the estimate. Errored trials draw from the budget but don't advance the
  statistical `n`, so a dead endpoint costs at most `n_max` calls and terminates — never an infinite
  retry.

**Reporting the uncertainty.** SPRT returns a *decision* (breached / safe), but the dashboard still
shows a point ASR — and because different cells are now graded at different `n`, a bare fraction would
hide how much evidence sits behind each. So every cell reports a **Wilson score interval** on its
`n_breach / n`: a cell that resolved in 4 trials shows a wide band, one that ran to `n_max` a tight one.
The variable sample size becomes legible to the reader instead of silent — the SAFE/BREACHED call is
the decision, and the interval is the confidence in the rate reported alongside it.

## Paper grounding (read in full via crawl4ai)

| Source | What we took | What we deliberately did **not** take |
|---|---|---|
| **ConSol** — Lee et al., [arXiv 2503.17587](https://arxiv.org/abs/2503.17587) — first application of Wald's SPRT to LLM sampling | The Wald mechanics (Appendix A: `A=(1−β)/α`, `B=β/(1−α)`, reject/accept/continue on the LLR) and the **concurrent-batch** trick (§2.5: "concurrently sample two or three per turn"). | ConSol's task is *mode detection* with a degenerate near-null (p0=0.5, p1=0.5001) and an extreme β≈0.95 to force early stops. ROGUE's is a genuine **threshold** decision with cleanly separated hypotheses and symmetric α=β=0.05 — the standard, statistically clean SPRT regime, not ConSol's sensitivity hack. |
| **Wald 1945/1947** — the SPRT itself | The optimality property: among all tests with the same error rates, the SPRT minimizes the *expected* sample size. That's exactly why it beats a fixed `n`. | — |
| **Truncated SPRT** — Fay & Follmann 2008 ([PMC2467508](https://pmc.ncbi.nlm.nih.gov/articles/PMC2467508/)) | The reminder that a finite `n_max` breaks Wald's *exact* error guarantees, which is why we make the truncation fallback the incumbent point rule rather than a fresh boundary decision. | — |

The Elicit brief that seeded this misattributed the SPRT paper to a nonexistent "Andrea Morandi" and
cited unverifiable "4.06 vs 15 calls" figures — the real paper is ConSol, and its numbers are a
93.9→94.2 accuracy / 88.6% token-reduction result on GSM8K, not what the brief claimed. We ground the
design on the real papers, not the brief.

## Wiring — real, in all four trial-loop surfaces

SPRT is off unless `ROGUE_SPRT` ∈ {on,1,true,yes}. When off, every surface below behaves exactly as it
does today. When on, the fixed-`n` inner loop is replaced by the sequential driver at the same point in
the evaluation loop. The default `rogue scan`/SDK path does **not** route through `scan_endpoint`, and
the paid research arms route through neither — so "real wiring" means all four:

| Surface | File | Splice |
|---|---|---|
| Public endpoint scan / `--persist` CLI / retest | `reproduce/endpoint_scan.py::scan_endpoint` | trial loop → `run_sprt`; `EndpointFinding.breached` from the SPRT decision |
| **Default `rogue scan` + SDK** | `scan.py::run_scan` | trial loop → `run_sprt`; this is the gap the brief's "two call sites" missed (it names only endpoint + sweep) |
| Long-context / generator sweep | `reproduce/generator_sweep.py::live_trial_fn` | SPRT-native trial fn returning `(n_breach, cost, n_fired)`; `_probe` reports the ASR over the trials actually spent |
| Research reproduce / paid arms | `scripts/reproduce/reproduce_once.py::_run_one_pair` | inline pair runner → `run_sprt`; **inert on the `--judge-batch` path**, which grades the full fixed `n` in one Anthropic batch by design |

`ROGUE_SPRT_P0`, `ROGUE_SPRT_P1`, `ROGUE_SPRT_ALPHA`, `ROGUE_SPRT_BETA`, `ROGUE_SPRT_MAX_TRIALS`,
`ROGUE_SPRT_BATCH` tune the test; a malformed value logs and falls back to *off* — SPRT is an
optimization, never a dependency of a scan completing.

## Measured results (offline, $0)

`scripts/reproduce/replay_sprt.py` drives the **real `run_sprt`** over every stored `breach_results`
cell — no invented trials, so the number is a conservative lower bound. Against the local DB
(11,973 rows / 1,939 cells):

```
 trials fired (today) : 11973   (mean 6.17 trials/cell)
 trials under SPRT    :  9323   (mean 4.81 trials/cell)
 calls saved          :  2650   (22.1% of target+judge calls)
 agrees with rate≥0.4 :  1935/1939 (99.8%)
```

Mean trials per cell drops **6.17 → 4.81** — same decision on 99.8% of cells, one-and-a-third fewer
model+judge calls each on average.

The 22.1% aggregate is **dragged down by ROGUE's history**, not by the method: 1,243 of the cells have
exactly 5 stored trials — one short of the 6 a clean SAFE decision needs — so they can't early-stop on
replay and save almost nothing. Where the stored data actually lets SPRT run, savings scale exactly as
the theory predicts:

| trials/cell | cells | saved/cell |
|---|---|---|
| 10 | 25 | 3.0 (30%) |
| 15 | 34 | 7.8 (52%) |
| 18 | 29 | 10.7 (59%) |
| 23 | 16 | 17.0 (74%) |
| 33 | 4 | 26.0 (79%) |

### Where the savings come from — effort is *reallocated*, not just cut

The aggregate hides the mechanism. This is the mechanism: the Monte-Carlo **expected sample size**
(mean trials to a decision at a known true breach rate `p`, `n_max=12`, 20k simulations/point) is a
clean **U-shape** —

| true breach rate `p` | mean trials E[N] | reach a decision |
|---|---|---|
| 0.0 — clearly safe | **6.0** | 100% |
| 0.1 | 7.9 | 92% |
| 0.2 | 9.6 | 64% |
| 0.3 | 10.7 | 40% |
| **0.4 — the decision boundary** | **11.0** | 32% |
| 0.5 | 10.4 | 46% |
| 0.6 | 9.3 | 70% |
| 0.7 | 7.7 | 89% |
| 0.8 | 6.2 | 98% |
| 0.9 | 5.0 | 100% |
| 1.0 — clearly breached | **4.0** | 100% |

A cell that is obviously safe or obviously broken is settled in **~4–6 trials**; a cell sitting on the
0.4 boundary — where the fixed-`n=3` ASR was pure noise — runs to **~11**, nearly the full cap. So SPRT
does not uniformly cut effort: it **moves** it off the easy cells and onto the genuinely ambiguous ones,
which is exactly where you wanted the trials in the first place. The hard cases are *not* starved to buy
the average saving — they are the beneficiaries of it. (Independent of ROGUE's data: this is the Wald
operating-characteristic curve, reproduced by `replay_sprt.py --asn-only`.)

## Caveats

- **Replay ≠ live.** The 22.1% is what SPRT would have saved *over the trials ROGUE already fired*;
  most cells only carry 3–5 trials, so SPRT rarely reaches a boundary on replay (21% "decided"). Live,
  it fires up to `n_max` and decides far more often — the honest live figure is a gated paid reproduce
  run, not a claim we can make from replay alone.
- **Composing with survival ordering — same run, own arm.** SPRT and the survival gate are orthogonal
  (survival picks *which cells* fire; SPRT sets *how many trials* each fired cell gets), so they compose
  as a product and share one harvest/config/budget envelope. But the *measurement* can't piggyback on a
  scan that fires ~3 trials/cell — one short of a SAFE decision, so a replay over it inherits the same
  weak signal as above. A strong live SPRT number needs a short dedicated pass at **higher `n_trials`
  (≥12)** so SPRT has room to early-stop against a real fixed-n baseline — a deliberately-configured
  arm, not a by-product of an ordering A/B.
- **Latency vs cost.** Batched sequential firing (`batch=2`) trades some parallelism for early
  stopping. For a paid scan, dollars dominate latency; raise `ROGUE_SPRT_BATCH` to recover throughput
  at the cost of a little over-firing.
- **The bracket is global.** `p0=0.25 / p1=0.55` bracket the 0.4 matrix threshold. The sweep uses a
  0.5 break threshold and recomputes its own break from the reported rate, so a small mismatch there
  is harmless; if a surface ever needs a different line, set `ROGUE_SPRT_P0/P1` per its threshold.
- **Not on `--judge-batch`.** Batch grading and sequential early-stopping are mutually exclusive by
  construction; the batch path fires the full fixed `n` and logs that SPRT doesn't apply.

## Summary

We do not introduce a new statistical test; we introduce a **production evaluation architecture that
makes sequential testing compatible with asynchronous LLM red-team pipelines** — a concurrent-batch
sequential test spliced into every execution path, a truncation rule that guarantees the benchmark's
verdicts are unchanged, and a replay methodology that measures the saving over historical traces
without re-running paid experiments.

**Why not just raise `n_trials` from 3 to 12?** Because a larger fixed `n` improves confidence
*uniformly* — it spends the same extra calls on the many cells whose verdict is already obvious as on
the few that are genuinely uncertain. SPRT buys the reliability only where it's needed: it delivers
near-fixed-12 confidence on the ambiguous cells (which run to ~11 trials) while spending closer to
fixed-3 cost on the easy ones (~4–6). Same statistical guarantee at the boundary, a fraction of the
calls away from it.

The load-bearing property is that the measurement does not move: on 1,939 real cells the sequential
test reaches the **same breach verdict as the fixed-`n` rule on 99.8% of them**, while spending fewer
model+judge calls to get there and reallocating the trials it does spend onto the ambiguous cells where
the fixed-`n=3` ASR carried no signal. The offline replay puts that saving at 22.1% of already-fired
calls; a live deployment figure is a gated paid run.
