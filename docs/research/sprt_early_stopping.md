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

Frame each cell's breach decision as a Bernoulli hypothesis test bracketing the 0.4 breach threshold:

> **H0: p ≤ p0 (= 0.25)** — "below the breach line"  vs  **H1: p ≥ p1 (= 0.55)** — "above it"

with symmetric error targets α = β = 0.05. After each trial we update the log-likelihood ratio (LLR):

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
  cells; a borderline cell is graded byte-identically to the fixed-n path, just with a larger, more
  meaningful `n` behind the estimate. Errored trials draw from the budget but don't advance the
  statistical `n`, so a dead endpoint costs at most `n_max` calls and terminates — never an infinite
  retry.

The reported point ASR keeps a **Wilson score interval**, so a borderline cell that ran to `n_max`
still surfaces its uncertainty honestly rather than as a bare fraction.

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

SPRT is off unless `ROGUE_SPRT` ∈ {on,1,true,yes}. When off, every surface below is byte-identical to
today. When on, the fixed-`n` inner loop is replaced by the sequential driver at the same fire+judge
seam. The default `rogue scan`/SDK path does **not** route through `scan_endpoint`, and the paid
research arms route through neither — so "real wiring" means all four:

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
 trials fired (today) : 11973
 trials under SPRT    :  9323
 calls saved          :  2650  (22.1% of target+judge calls)
 agrees with rate≥0.4 :  1935/1939 (99.8%)
```

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

The Monte-Carlo **expected sample size** (trials to a decision at a known true rate `p`, `n_max=12`)
shows the same shape independent of ROGUE's data: E[N] = 6 at p=0 (50% of a fixed 12), E[N]=4 at p=1
(67% saved), peaking near the fixed cap only in the genuinely-ambiguous p≈0.35–0.45 band — which is
precisely where you *want* to spend the trials.

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

## Positioning

The one-liner: everyone reports an ASR from a fixed handful of trials; nobody treats the trial budget as
*sequential*. Reframing "fire N, divide" as a Wald test recovers the same breach verdict for ~⅓–¾
fewer calls on the clear cells and, more importantly, *reallocates* those trials to the borderline
cells where the ASR was meaningless — at 99.8% agreement with the incumbent rule on 1,939 real cells.
The live savings % is gated on one paid cycle; until then it's a directional "we're seeing…", not a
headline stat.
