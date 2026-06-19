# What the bandit is, in plain English

*A non-jargon explainer of `src/rogue/harvest/bandit.py` and the `/feed` dashboard
widget. For the technical spec, see ROGUE_PLAN.md §11.6.*

---

This is describing a system for **automatically discovering new jailbreak
techniques against AI models**. Let me break it down, because the jargon is
doing a lot of heavy lifting here.

## The core problem it solves

Imagine you run 10 web searches every day looking for new AI jailbreaks. Some
searches consistently turn up new stuff, others are duds. A static list never
learns this. A bandit learns.

## What "multi-armed bandit" actually means

"Multi-armed bandit" is a classic problem from probability theory. Picture a
row of slot machines ("one-armed bandits"), each with a different unknown
payout rate. You want to figure out which machines pay best while also
actually winning money. The tension: do you keep pulling the lever you
currently think is best (**exploit**), or try others in case they're secretly
better (**explore**)?

Mapping that to this system:

- The **"arms"** are 36 different search queries, like
  `site:reddit.com/r/GPT_jailbreaks "new method" after:2026-05-01`. Each is
  one slot machine.
- **"Pulling an arm"** means running that search and seeing what comes back.
- The **"payout"** is `mean_yield = novel_canonical_primitives / cost_usd` —
  in plain English, *how many genuinely new jailbreak techniques did this
  search find, per dollar spent running it?* "Canonical" means deduplicated
  to a standard form so you don't double-count the same trick written two
  ways.

## ε-greedy (epsilon-greedy) — the strategy

With probability ε (here 10%), pick a random arm to **explore**. The other
90%, pick the arm with the best track record so far (**exploit**). The 10%
exploration is the "prevents lockup" bit — without it, if a good arm got
unlucky early, you'd never try it again.

**Cold-start** means: before any of this learning kicks in, try each arm in
the pool (39 arms) once. Otherwise you'd have no data to be greedy about. (If
arms are added later, they're cold too — they get pulled first on the next run,
which is why the live "warm" count can trail the pool size for a run or two.)

## The daily loop

1. **`select(k=10)`** — pick 10 queries using the ε-greedy rule.
2. **Run them**, scrape results, extract jailbreak techniques, dedupe against
   everything you've seen before.
3. **`record(arm_id, novel, cost)`** — for each query, log how many new
   techniques it produced and what it cost.
4. **Save stats** to `data/discovery_bandit.json` so tomorrow's run picks up
   where today left off.

Over time, the system concentrates effort on queries that actually find new
stuff, and quietly stops wasting money on dead ones — while still
occasionally checking whether the dead ones came back to life.

## Where you can see it

The dashboard's `/feed` page (right sidebar) renders the live bandit state as
a small widget:

```
┌──────────────────────────────────────┐
│ ε-GREEDY BANDIT                      │
│ DiscoveryAgent self-tunes SERP query │
│ selection · §11.6                    │
│                                      │
│ TOP 3 ARMS              (green)      │
│   github_pliny_umbrella    8000.0/$  │
│   arxiv_prompt_injection   3333.3/$  │
│   arxiv_jailbreak_llm      3333.3/$  │
│                                      │
│ BOTTOM 3 ARMS           (muted)      │
│   blog_lakera_attack        266.7/$  │
│   reddit_localllama_uncensor 133.3/$ │
│                                      │
│ 39 arms · 36 warm                    │
│ seeded 2026-05-27 · last live 2026-05-27
└──────────────────────────────────────┘
```

The `XXXX.X/$` number is the per-query yield (new primitives per dollar). The
footer line distinguishes the **seeded** baseline (warm-prior from corpus
attribution) from the **last live pull** (most recent actual harvest run) —
so the widget reads honestly about its provenance instead of pretending all
its knowledge came from live observation.

## Why this matters for the project

ROGUE is a "continuous open-web red team" — it watches public sources for new
attacks every day and runs them against customer AI deployments. The bandit
is what makes the discovery layer self-improving: instead of a Day-0 analyst
hand-picking 10 queries forever, the system measures which queries actually
work and reallocates effort accordingly. Six months in, it's discovered which
subreddits are productive vs which went quiet, which arXiv search terms catch
new papers, etc. — without anyone manually re-tuning.
