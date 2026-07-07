# Pre-fire Prompt Pruning in the Escalation Search (Q12/Q10)

**The question.** *In an automated jailbreak search that fires a paid rollout per generated variant,
how many of those rollouts are spent on prompts that are near-duplicates of ones already tried — and
can they be skipped before the money is spent?*

**One line.** A **per-search pre-fire gate**: before firing a candidate prompt against the target,
embed it and **skip the rollout** if it is cosine ≥ 0.92 to a prompt already fired *this search* —
plus an opt-in **EvoJail soft-novelty reward** that steers the searcher toward diverse prompts. Real
wiring into ROGUE's escalation search (`reproduce/search/`), **off by default**, byte-identical when
off, no new dependency.

## The main finding: the flat bandit burns most of its budget re-firing identical prompts

Two things measure for free against data ROGUE has already paid for, and they are the two numbers
that decide whether the gate is worth turning on. Reproduce both with
`uv run python scripts/reproduce/replay_prefire_prune.py`.

**(1) In-search redundancy — the un-confounded number.** Run the *real* MCTS and bandit searchers
over 40 real seed payloads with a $0 all-refused rollout (the common "stuck" regime — most attacks
don't breach) and a string-identity embedding, so the gate skips only *exact regenerations* — a clean
lower bound on the near-duplication a searcher produces in its actual per-search regime (one seed, one
config):

| Searcher | Exact-regeneration prune rate | |
|---|---|---|
| MCTS | **7.0%** of expansions | tree expansion pops each action once per node → little exact repetition |
| **bandit** (ROGUE's prod-default searcher) | **87.9%** of expansions | flat hill-climb from best-so-far + Thompson re-sampling the same arms on the same stuck prompt → it re-fires the *identical* child over and over |

The bandit result is the headline: **ROGUE's default escalation searcher, when it isn't finding an
improvement, spends the overwhelming majority of its paid rollouts re-firing prompts it has already
fired.** These are exact-string duplicates — a hard *lower* bound; the semantic near-duplicates the
0.92 cosine gate also catches sit strictly above it. (Honest scope: measured under an all-refused
rollout — the rate falls as the search finds improving mutations and the best-so-far prompt moves —
but "stuck" is the modal case on a hardened target, which is exactly when wasted budget hurts.)

**(2) Corpus semantic redundancy — with real paid embeddings.** Replay the greedy 0.92 gate over
ROGUE's 416 real `attack_primitives` (embeddings already stored), in harvest order:

- **near-duplicate prune rate 14.9%** [95% CI 11.8%, 18.6%] (62 of 416 prompts are ≥0.92 cosine to
  one already admitted).

**The safety caveat, stated plainly.** Of the pruned prompts that *breached*, 11 of 18 had an
admitted near-neighbour that also breached (a **free** prune — the breach is still represented) and 7
did **not** (a **lossy** prune). That 39% corpus-level lossy rate is **config-confounded**: two
textually-near primitives can differ on "ever breached" only because they were tested against
*different* configs, not because the payload is weaker — so it overstates the risk in the gate's
actual regime, where it dedups one seed against **one** config and a near-duplicate genuinely shares
the target's verdict. This confound is *why the pruner is per-search, not a global corpus dedup*, why
it is **off by default**, and why the safer knob in ambiguous regimes is the soft λ reward (which
never drops a candidate — it only re-orders). The live breach-per-dollar lift is a gated ~$35 A/B.

## The problem

ROGUE's escalation search (`reproduce/search/`, AutoPT F1–F4) takes a refused primitive and searches
a mutation space for a breaking variant. Node = a prompt; edge = a mutation (a $0 deterministic
obfuscation op) or an LLM refine; each expansion is evaluated by a **real rollout** — one target call
+ one judge call, the paid unit. `Budget(max_rollouts=30)` means up to 30 paid rollouts per seed, and
**today every expansion fires one**, with no check for whether the candidate is something already
tried.

The only existing novelty signal, `coverage.NoveltyReward`, embeds each rollout's **response** and
rewards behavioural diversity — but it acts *after* the rollout is already paid for. It steers the
search; it never skips a call. The missing piece is a **pre-fire** gate on the **prompt**.

## Grounding in the literature (full-text reads, not the brief)

All three papers were pulled in full via crawl4ai (ar5iv → arXiv HTML) and the report's numbers
fact-checked against them.

- **TAP — "Tree of Attacks with Pruning"** (arXiv 2312.02119). TAP's ablated contribution is
  *prune-before-fire*: its Phase-1 evaluator discards off-topic prompts before they reach the target,
  cutting target queries from a `w·b·d`-bounded 400 to **< 30** on average while holding ASR within
  ~12% (§3.2, Table 4). Crucially, §3.2 also names the exact waste ROGUE measures — **"Prompt
  Redundancy": "the prompts generated from the first iteration follow nearly-identical strategies in
  many repetitions."** TAP prunes on *relevance* (an LLM off-topic judge); ROGUE's existing
  `goal_preservation` gate already plays TAP's Phase-1 role, so the **new** mechanism here is the
  *near-duplicate* prune — a different axis TAP observes but doesn't mechanize. TAP's Phase-2 width-w
  prune does **not** port: ROGUE expands **one child per step** (MCTS pops one untried action; the
  bandit samples one) — a b=1, PAIR-shaped loop with no width-w frontier to trim — so the
  per-expansion cosine skip is ROGUE's equivalent query-saver.

- **EvoJail — "Evolutionary Diverse Jailbreak Prompt Generation"** (arXiv 2605.02921). Makes
  population diversity a first-class objective via the multi-objective fitness (their Eq. 6)
  `F(p) = w₁·S(p) + w₂·D(p|P)`, where `S(p)` is the safety-risk (≈ compliance) score and (Eq. 8)
  `D(p|P) = 1 − (1/(N−1))·Σⱼ sim(p, pⱼ)` is prompt novelty vs the population. ROGUE adopts the
  objective as the opt-in soft reward `S(p) + λ·D(p|P)`, with two faithful adaptations: EvoJail uses
  *mean* cosine over **TF-IDF** vectors; ROGUE uses `1 − max` cosine over the **neural embeddings** it
  already computes (stricter, and consistent with `coverage.NoveltyReward`). >93% ASR / +5.6%
  diversity both verify from the paper.

- **KDA — "A Knowledge-Distilled Attacker"** (arXiv 2502.05223). The source for *how to measure*
  set-level diversity: Topic Diversity Ratio, Type-Token Ratio, GPT-2 perplexity. ROGUE surfaces the
  prune rate + fired-set diversity rather than adopting KDA's BERTopic dependency.

The Elicit brief's error the read caught: it credited Mask-GCG with finding "most suffix tokens
redundant" — Mask-GCG finds the **opposite**, and is white-box token-level, irrelevant to a black-box
prompt generator. Only TAP's prompt-level, black-box prune is the relevant lever.

## How it works (the system)

`reproduce/search/pruning.py` adds one stateful, injectable object mirroring the existing
`goal_preservation` gate:

- **`PromptPruner.admit(prompt) → bool`.** Embeds the candidate, records its novelty
  (`1 − max` cosine to already-fired prompts = EvoJail's `D(p|P)`), and returns `False` — skip the
  rollout — when it is a near-duplicate (max cosine ≥ threshold) of something already fired *this
  search*; otherwise records it as fired and returns `True`. The seed always fires and is recorded, so
  children dedup against it. Constructed fresh per search — the fired set is the search's own history,
  never a global corpus (see the confound above).
- **Reuse, no duplication.** The threshold is `dedupe.DEFAULT_COSINE_THRESHOLD` (0.92, the same
  constant the harvest deduplicator uses); the cosine is `coverage._cosine`; the embedding seam is the
  same `EmbedFn` shape as `dedupe`/`coverage` and reuses `live.make_embed_fn` (OpenAI
  `text-embedding-3-small`) on a paid run. No new dependency, no new constant, no duplicated math.
- **The gate placement.** In both `MCTSSearcher` and `BanditSearcher`, immediately after the existing
  `goal_check` and *before* `rollout(child_prompt)`: a pruned child charges only the (≈$0) mutation
  cost, is recorded in the trace as `skipped: "prefire_prune"`, and — in the bandit — penalises the
  action's Thompson arm (it produced a redundant child). The MCTS variant simply doesn't graft the
  dead child. Byte-identical to today when `pruner is None`.
- **EvoJail soft reward (opt-in, `λ` default 0).** When `λ > 0`, the value the searcher climbs
  becomes `reward(outcome) + λ·pruner.last_novelty` — the diverse-and-effective objective — leaving
  the reported `best_compliance` pure. `λ = 0` leaves the search dynamics untouched.

**Env surface (off by default).** `ROGUE_SEARCH_PRUNE` (off), `ROGUE_SEARCH_PRUNE_THRESHOLD` (0.92),
`ROGUE_SEARCH_PRUNE_LAMBDA` (0.0). With the flag unset, `resolve_pruner` returns `None` and both
searchers are byte-identical — **zero** embedding calls, **zero** behaviour change. When on but no
`embed_fn` is available on the search path, it safely degrades to fire-all rather than guessing.

## Surfaces wired (all of them)

The escalation search is itself an **opt-in** subsystem (measure-first: the bandit stays prod-default
until the A/B promotes MCTS). Within it, every entry point that constructs or runs a searcher is
wired:

- `search_escalate` (`run.py`, F1) — resolves the pruner from the env when an `embed_fn` is present.
- `harden_from_remediation` (`run.py`, F4) → `harden_check` (`harden.py`) — same env resolution.
- `ab_compare` (`ab.py`) — takes a `make_pruner` factory (fresh per search, like `make_reward`) so the
  A/B can measure bandit+prune vs bandit; the report surfaces `pruned` + `prune_rate` per searcher.
- Both `MCTSSearcher.search` and `BanditSearcher.search` — the shared loop, the actual skip site.
- `SearchResult.n_pruned` surfaces the count (0 when off) — no silent drop.

**Not wired, deliberately:** `generator_sweep` sweeps *one* generator parameter (e.g. many-shot K) and
its sweep values are intentionally distinct points on a curve — not near-duplicates — so a cosine
dedup there would be wrong. It is out of scope and noted so no one "completes" it later.

## Verification (wired *and* run)

- **17 unit + integration tests** (`tests/test_search_pruning.py`): the `PromptPruner` gate + threshold
  boundary + EvoJail novelty math; the env resolver (off-by-default, needs-embed, threshold/λ, override);
  and — driving the **real** MCTS + bandit loops — byte-identical-when-off, an all-dup embed collapsing
  a 20-rollout search to a **seed-only** run (a counting rollout proves the target was queried exactly
  once), the false-skip-safety invariant (no novel prompt is ever skipped), and `ab_compare` surfacing
  prune stats. All green.
- **End-to-end, env-resolved (not injected):** `search_escalate` and `harden_from_remediation` driven
  with a mock panel/judge ($0) and `ROGUE_SEARCH_PRUNE=on` — the resolver builds the pruner, the loop
  consults it, and the search collapses to the seed-only run (20→1 rollouts, 10 pruned); with the flag
  unset both fire all 20 (byte-identical). This is the "wired ≠ run" check on the actual entry points.
- **$0 replay over real Neon data** — the two findings above.
- Full search suite green; `ruff check src/` clean.

## Why it's novel (systems framing)

The mechanisms are precedented — TAP prunes before firing, EvoJail rewards diversity, ROGUE's own
`dedupe` clusters near-duplicates at harvest. The contribution is the **integration and the
measurement**: a *per-search, black-box, near-duplicate* pre-fire gate inside a live continuous
red-team's escalation loop, with (a) the redundancy it removes **measured on the real searchers**
(the bandit's ~88% exact-regeneration rate when stuck is a concrete, unreported systems result), (b)
its breach-coverage risk measured and its confound named, and (c) byte-identical-when-off deployment
across every search surface. It composes with the sibling budget levers: Q6 (per-cell trial budget),
Q7/Q11 (which pairs to fire), Q2 (judge economics) — this one cuts the *search-expansion* budget, a
distinct axis. Folds into the systems paper as a search-budget section.

## Status & configuration

Built + offline-validated ($0). Off by default (`ROGUE_SEARCH_PRUNE`), byte-identical when off. The
live breach-per-dollar lift needs the gated ~$35 A/B (bandit vs bandit+prune via `ab.py`); the flag
stays off until then. ⚑ possibly publishable as a systems result.
