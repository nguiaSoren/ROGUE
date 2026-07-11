# M2S — Multi-turn-to-Single-turn Consolidation (Q14)

**The question.** *ROGUE's corpus carries multi-turn (Crescendo / gradient) attacks that fire as a
real back-and-forth — K sequential victim calls per trial. Can that multi-turn coverage be bought at
single-turn cost without re-engineering the attacker?*

**One line.** Fold a multi-turn primitive's ordered turns into ONE structured single-turn prompt using
a deterministic string formatter (Ha et al.'s **Hyphenize / Numberize / Pythonize**), so it fires
through the existing, fully-tested `render` → `run_attack` path at **1× trial** — one victim call,
zero attacker-LLM cost — instead of the K sequential calls `run_conversation` spends. Real wiring into
ROGUE's three fire surfaces, **off by default** (`ROGUE_M2S` unset), byte-identical when off, no new
dependency.

## Paper grounding (read in full via crawl4ai)

**M2S — *One-Shot is Enough* (Ha et al., arXiv 2503.04856), the load-bearing paper.** Read the full
ar5iv text, not the brief. What it establishes and how it shaped the build:

- **The three formatters are the whole method** (§3.1–3.3). Hyphenize prefixes each turn with `-` under
  a "respond sequentially, hyphens only" header; Numberize replaces the bullets with `1. 2. 3.`;
  Pythonize wraps the turns as a `questions = [...]` list inside a runnable Python skeleton. They are
  *pure string templates* — no attacker LLM. ROGUE reproduces the exact paper templates in
  `reproduce/m2s/consolidate.py`.
- **The mechanism is "contextual blindness"** (§1, Table 2): consolidating the sequence into one prompt
  embeds the harmful progression inside structural formatting that turn-based input/output safeguards
  don't inspect turn-by-turn — so the consolidated form can *evade guardrails the multi-turn form
  trips*. This is why M2S "often increases or maintains" ASR rather than merely approximating it.
- **The headline numbers are the Ensemble, not any single method** (Table 1, verified line-by-line
  against the crawl). On GPT-4o: Hyphenize 81.4 (**+9.9**), Numberize 68.2 (**−3.3**), Pythonize 85.8
  (**+14.3**), **Ensemble (best-of-3) 89.0 (+17.5)**. On Mistral-7B the Ensemble reaches **95.9%**.
  **Individual methods are mixed — some *lower* ASR** (Numberize −3.3 on GPT-4o; every single method is
  negative on one model block). The "+17.5% / 95.9%" the brief cites are the **best-of-3 Ensemble** (3
  trials, any-breach), *not* a single 1× fire. This nuance drove the design decision below.
- **Threshold 0.25** (StrongREJECT, F1-maximised on a 2-expert human-labelled set) — noted for
  calibration parity; ROGUE grades with its own judge, not StrongREJECT.

**MT-AgentRisk — *Unsafer in Many Turns* (Xu Li et al., arXiv 2602.13379).** Full read. Supports the
coverage thesis: transforming single-turn harmful tasks into multi-turn sequences raises ASR **+16% on
average** across open/closed models (their ToolShield defense recovers −30%). This is *why* multi-turn
coverage is worth having cheaply — and it corrects the brief's phantom "Pengcheng Li" to **Xu** Li.

**X-Teaming (Rahman et al., arXiv 2504.13203).** The *adaptive* multi-agent runner (planner +
optimizer + verifier, "up to 98.1%" ASR — a **max**, not an across-models figure). Deliberately **not
built here**: it costs ~K× victim + K× attacker-LLM calls per trial (~6×). M2S buys most of the
multi-turn win at 1× cost; the adaptive runner is the sequenced-second follow-on, not this build.

## Design — one consolidation, not the Ensemble

`consolidate_primitive(primitive, method)` returns a schema-valid **single-turn** derived primitive:
`payload_template` becomes the M2S prompt, `multi_turn_sequence` / `slot_requirements` are cleared and
`requires_multi_turn` set False. It keeps the **same `primitive_id`** — this is a render-time
substitution ("fire this primitive's turns consolidated"), not a new corpus row, so nothing forks the
matrix or the FK graph. `{slot}` placeholders inside a turn pass through untouched; the single-turn
renderer substitutes them exactly as for any payload (its substitution is regex-based, so Pythonize's
literal `{i}` / `{question}` f-string braces survive verbatim — verified). Because the consolidated
render carries one user turn, every surface's existing `user_turn_count(rendered) >= 2 →
run_conversation` branch **automatically** routes it to the single-invoke `run_attack` path. No
per-surface fire-loop change; the whole feature is a list transform before the loop.

**Why a single method (default `pythonize`) and not the paper's best-of-3 Ensemble.** The Ensemble is
where the headline lift lives, but it fires **three** variants per cell and takes any-breach — a 3×
fan-out that changes the trial-loop structure and is a *paid research* concern, not the default
operational path. One method keeps the operational win at a true **1× trial** and the splice a pure
transform. Default is `pythonize` (the strongest single method on GPT-4o, +14.3, and positive on 3 of
4 model blocks); `ROGUE_M2S_METHOD` selects `hyphenize`/`numberize`/`pythonize`. The Ensemble is the
natural shape of the paid A/B (fire scripted vs each M2S variant, compare), noted as future work.

## Where it's wired (every surface — grepped, not trusted to the brief)

The brief named `escalation_planner.py → single-turn run_attack path` (one location). The real fire
surfaces that render a corpus primitive and branch multi-turn-vs-single are three:

- **`scan.py::run_scan`** — the default `rogue scan` + SDK path. `apply_m2s(primitives)` after the
  survival/prefire gates (so only the primitives that *will* fire are folded); `ScanReport.m2s =
  {n_consolidated, method, note}` surfaces it (None when off → dict byte-identical).
- **`reproduce/endpoint_scan.py::scan_endpoint`** — public API / `--persist` CLI. Same gate;
  `EndpointScanReport.n_m2s_consolidated` + `m2s_note`.
- **`scripts/reproduce/reproduce_once.py::run_reproduction`** — the paid research arm. **Explicit
  opt-in only** (`--m2s-consolidate` → `apply_m2s_pairs`), because consolidating *replaces* the
  scripted multi-turn fire; the A/B compares a consolidated run vs a scripted (M2S-off) run keyed by
  `primitive_id`. Off → the pair set is byte-identical.

**Deliberately NOT wired:** `generator_sweep.py` (its swept payloads are single-turn by construction —
nothing to consolidate) and the **escalation ladder** itself (`escalation_ladder.py` — that *is* the
true-multi-turn experiment; consolidating inside it would corrupt the very thing it measures). M2S
consolidates **corpus** multi-turn primitives at the fire surface, not the ladder's live escalation.

## Measured offline ($0, read-only Neon census — `scripts/reproduce/replay_m2s.py`)

M2S's value is *cheaper multi-turn coverage*, and that cost reduction is **deterministic** — provable
from the corpus turn counts with no target/judge call:

- **56 of 635 primitives (8.8%)** carry a `multi_turn_sequence` of ≥2 turns — the consolidation
  surface. Mean **3.45** turns each (median 3, max 13), 193 turns total.
- **Victim-call reduction on that slice: 193 → 56 calls per trial = 71.0% fewer.** A multi-turn
  primitive fired via `run_conversation` spends one victim call per turn; its M2S form spends one.
- **2,219 `breach_results` rows** already sit on multi-turn primitives — the fired surface is real and
  heavily exercised, not a corner case.

**What is NOT measured by the offline census (the efficacy question).** Whether the consolidated
single-turn form *retains or lifts* ASR versus the scripted multi-turn original — Ha's central claim —
requires firing **both** forms on a live panel. A first **directional** A/B ran 2026-07-11 (below); the
offline headline remains the **cost** number (71% fewer calls on the multi-turn slice), and the
efficacy read is small-n, not yet a powered stat.

## Measured live — first directional A/B (2026-07-11, small-n, judge = `openai/gpt-5.4-mini`)

⚠️ Directional, small-n — **NOT a headline**. The judge here is `gpt-5.4-mini` (a proxy; the calibrated
production judge was unavailable at run time), so read this as directional. Breach = `full_breach + partial_breach` (`evaded`/`refused` are non-breaches).

- **OpenAI (gpt-5.4-mini + nano, 15 multi-turn primitives × 2 trials = 60 cells/pass):**
  scripted **3/60 = 5.0%** → M2S-consolidated **5/60 = 8.3%** — consolidation **retained + slightly
  lifted** breach (+3.3 pts; all partial; 3 cells moved off "refused"). Directionally supports Ha's
  contextual-blindness claim on aligned targets.
- **Featherless Qwen3-32B (scripted only — the consolidated pass was killed for slowness at
  concurrency-1 under the Featherless 4-unit cap):** **10/15 = 66.7%** (5 full + 5 partial). No Qwen
  A/B, but the scripted rate is a striking **cross-vendor permissiveness gap** vs OpenAI's 5.0% (the
  "model is the variable" / safeguard-variance theme).

Data: Neon `breach_results` + `data/agent_exec/session_2026-07-11_arms_3_8a_19_21.md`. This is a
"we're seeing" directional read (n=15 primitives), not the powered A/B; `ROGUE_M2S` stays OFF in prod.

## Verification (wired ≠ run)

Beyond 22 unit tests (formatter goldens, escaping, order preservation, schema-valid derivation, the
20k overflow guard, the env resolver, byte-identical-off), **all three fire surfaces were driven
end-to-end** (not wired-and-read):

- **`run_scan` / `scan_endpoint`** — driven through the real env resolver (`ROGUE_M2S=on`, not an
  injected config) with a counting panel: a multi-turn primitive fired via **`run_attack` exactly
  once** (single-turn, 1× trial) with the flag on, and via **`run_conversation`** with it off — the
  behavioural flip M2S exists to produce; `ScanReport.m2s` / `EndpointScanReport.n_m2s_consolidated`
  surfaced.
- **`reproduce_once::run_reproduction`** — a **real $0 end-to-end run against a local Postgres**
  (`rogue_test`, mock panel/judge, `escalate=False`): a 3-turn crescendo primitive seeded into the DB,
  `run_reproduction(m2s_consolidate=True)` under `ROGUE_M2S=on`, and the panel received the primitive
  **folded to exactly one user turn** with a `BreachResult` row **persisted** — proving the ORM→Pydantic
  conversion, the `if m2s_consolidate:` splice, `apply_m2s_pairs`, and the fire→judge→persist loop all
  ran on the consolidated primitive; the off control received all 3 turns (byte-identical). (This is
  the local test DB, not Neon; the *paid* cross-model efficacy A/B is still the gated arm — but the
  splice itself is run, not assumed.)

## Status

**BUILT + wired + $0-census-validated (2026-07-08), off in prod.** `ROGUE_M2S` is unset everywhere;
today's behaviour is byte-for-byte unchanged. The **efficacy headline (ASR retained/lifted vs scripted
multi-turn) is the gated paid A/B** — until it lands this doc reports only the deterministic 71%
call-reduction, not an ASR claim.

## Publishable? / LinkedIn?

**Not a standalone paper.** M2S is a *known* technique (Ha 2503.04856); ROGUE reuses it. The only
research-shaped result would be a small **coverage-vs-cost** measurement — "corpus multi-turn attacks
consolidate to 1× cost (71% fewer victim calls); ASR parity holds at X% on our panel" — which, if the
paid A/B confirms parity, is a *supporting* systems observation (sibling to the Q12 search-budget
section), not a contribution of its own. **LinkedIn: borderline, below the survival/SPRT/cascade
posts.** The honest offline hook is the cost number; the efficacy hook needs the paid A/B and the
marketing-honesty gate.
