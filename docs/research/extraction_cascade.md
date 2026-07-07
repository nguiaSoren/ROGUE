# Local-first extraction cascade (Q17)

**Status:** BUILT + offline-validated ($0), off by default. Live adoption gated on a
field-agreement bar a specific local model must clear first.

**Code:** `src/rogue/extract/cascade.py` (the cascade + env resolver + telemetry),
`src/rogue/extract/field_eval.py` (per-field agreement scorer + span-grounding),
`src/rogue/extract/extraction_agent.py` (`local/` provider branch), spliced into
`scripts/harvest/harvest_once.py` + `scripts/harvest/harvest_url.py`. Harness:
`scripts/extract/eval_extractor_fields.py`. Flags: `ROGUE_EXTRACT_CASCADE` (off),
`ROGUE_EXTRACT_LOCAL_MODEL`, `ROGUE_EXTRACT_GROUNDING_THRESHOLD`.

## The question and the honest reframe

Q17 asks whether a small/local model can replace the per-document extraction LLM
(the harvest-cost driver that turns a raw web document into a structured
`AttackPrimitive`). The premise is half-outdated: ROGUE's extractor **already**
runs on a small model (`anthropic/claude-haiku-4-5`), so the only live win is
**Haiku → a free local model**. That reframes Q17 from "swap large→small" to
"is a local model good enough, and how do we adopt it without dropping attacks?"

## What the papers actually say (and don't)

Both load-bearing papers were read in full via crawl4ai; every number the Elicit
brief cited was fact-checked against the source.

- **Lincoln, "A Few Good Clauses" (2605.05532).** A domain-**fine-tuned** LoRA-MoE
  ("Olava Extract") beats five *zero-shot* frontier APIs on 26-field contract
  extraction — macro-F1 **0.812** vs 0.796 best-frontier (a **0.016** margin),
  78–97% cheaper, fewer hallucinated fields (verified §4.1–5.1, Tables 3/4/6).
  Two caveats the headline omits: it is a **vendor paper** pitting a heavily
  fine-tuned model against *zero-shot* baselines, and it redefines "small" as
  small *active* footprint (MoE), not 7B-class.
- **Bumgardner, "Local LLMs for Complex Structured Tasks" (2308.01727).** A
  fine-tuned local LLaMA-13B (F1 0.775) beats fine-tuned BERT/LongFormer
  (≤0.10) on structured medical codes — a **fine-tuning + deployability** result
  (local generative model scales with data where encoders collapse), explicitly
  **not** a small-beats-frontier claim; GPT-4 is never benchmarked.

**The load-bearing conclusions for ROGUE:**

1. **Only *fine-tuned* small is validated.** Neither paper supports an
   off-the-shelf small model. ROGUE's own measurement agrees decisively (below).
2. **The cost saving comes from self-hosting + batching, not from being tiny** —
   Lincoln's *unbatched* per-doc cost is ~8× worse and ties the cheapest frontier.
   And **neither paper compares against a cheap *hosted* small model like Haiku.**
   So the literature does **not** establish a Haiku→local cost win; it establishes
   a fine-tuned-self-hosted vs zero-shot-*flagship* win. This is the single most
   important honesty point in the whole build.
3. **Field types split predictably.** Small models are strong on closed-set enums
   and copied named-entity spans (→ ROGUE's `family`/`vector`), weak on free-text
   synthesis (→ `payload_template`, `payload_slots`, `reproducibility_score`) —
   but those are hard for *every* model, so Haiku doesn't rescue them much either.
4. **Once adequately trained, the small-model failure mode is *omission*, not
   *fabrication*** — the safer mode for a downstream reproduce pipeline.

## Measured, $0: off-the-shelf local is not adequate — at *any* size tested

Ran **three** off-the-shelf `qwen2.5` sizes (3B / 14B / 32B, Ollama, `local/`
prefix) through the real `ExtractionAgent` against the golden source-doc fixtures
(`scripts/extract/eval_extractor_fields.py`) — **all three score recall 0/2**, and
the *reason* sharpens with size rather than the result improving:

| model | `multilingual_paper.html` (academic jailbreak) | `copirate_365.html` (CVE injection) |
|---|---|---|
| **qwen2.5:3b** | abstains (`is_attack: false`) | abstains (`is_attack: false`) — no recognition |
| **qwen2.5:14b** | abstains | **recognizes** the attack (its prose summary is *accurate*) but emits a free-form summary / no `payload_template` → R5 demote |
| **qwen2.5:32b** | abstains | **recognizes** the attack (classification metadata) but still no `payload_template` → R5 demote |

**Recall 0/2 across the board.** Two distinct failure modes, and the important
one is prompt-resistant: (1) **recognition** — every size abstains on the harder
academic-paper attack; (2) **structuring** — 14B/32B *understand* the CVE attack
but won't render it as schema-shaped fields, specifically failing to synthesise
the free-text `payload_template` (exactly Lincoln's weak-field prediction). I gave
the models a fair shot: the `local/` path injects the full field contract + enum
vocabulary into the prompt (`_LOCAL_SCHEMA_HINT`, derived from the real enums), yet
at temperature 0 the 14B **deterministically ignores it** and keeps summarising.
So this is *not* "a 3B is too small" and *not* "under-prompted" — scaling params
15× and handing the model the schema both leave it at 0/2. That is why the fix is
a **fine-tune** (or schema-constrained decoding, which local runtimes can't
compile for a schema this large), and why the adoption mechanism is a cascade,
not a swap — a swap at *any* of these sizes would silently drop attacks.

(The field-agreement scorer itself is proven correct on the golden-as-perfect-
extractor: structural macro **1.0**, per-field enum/set/dict all 1.0, with
`payload_template` grounding varying by attack type — 0.26 for the reconstructed
research-paper attack, 0.67 for the copied-blog payload. That variance is the
reason grounding is an **anti-fabrication floor**, not a correctness gate.)

## The mechanism: a local-first cascade (sibling of the Q2 judge cascade)

Rather than switch models, ROGUE runs a **cheap local tier first and escalates to
Haiku whenever the local output can't be trusted** — so quality is never traded
for cost:

- **Local tier** (`local/<model>`, e.g. Ollama). A new `local/` provider branch
  drives the model in portable `response_format={"type":"json_object"}` mode,
  because the existing `openai/` branch pins output with
  `beta.chat.completions.parse(response_format=AttackPrimitive)`, whose grammar
  the AttackPrimitive schema is too large for local runtimes to compile (verified:
  Ollama returns *"failed to parse grammar"*). Since json-mode enforces valid
  JSON but not the *shape*, the branch injects the field contract into the prompt
  instead — `_LOCAL_SCHEMA_HINT`, the exact top-level field names + the (small)
  family/vector/severity enum vocabularies, derived from the real enums so it can
  never drift, with clauses that target the observed mid-model failures (prose
  summary instead of the payload; nesting under a wrapper key). The raw JSON flows
  through the **same** R1–R8 normalizer + Pydantic validation the Haiku path uses —
  the normalizer that already exists to absorb small-model schema drift earns its
  keep twice here.
- **Acceptance gate (asymmetric — mirrors Q2's "never assert from the cheap
  tier").** Accept the local extraction **iff** it is a schema-valid
  `AttackPrimitive` with a non-empty `payload_template` that clears an
  **anti-fabrication grounding floor** (`grounding_score` ≥ 0.15 — a
  wholesale-invention guard, *not* a correctness gate, since ROGUE payloads are
  synthesised and ground only partially even when correct). Otherwise —
  abstention, error, or a payload with almost no source overlap — **escalate to
  Haiku**. The cheap tier can only ever *save* a Haiku call; it can never *drop* a
  document on its own say-so.

Consequence, stated honestly: with a weak local model the cascade escalates
~everything (≈0 saving, **0 quality loss**); the saving materialises only for a
local model whose field agreement clears the bar — which you **measure first**
with the field-eval harness. With `qwen2.5:3b`, escalation is 100% and the local
tier saves nothing — the correct, safe outcome.

## Wiring (real, off by default, byte-identical when off)

`maybe_build_cascade_extractor()` is the single seam every harvest construction
site calls: it returns `None` unless `ROGUE_EXTRACT_CASCADE` is truthy, so the
off-path constructs the identical plain `ExtractionAgent(prompt_version="v4")` as
before. Spliced into both harvest surfaces — the production fan-out
(`harvest_once.py`, which routes through the 3-way v4 classifier) and the ad-hoc
single-URL path (`harvest_url.py`). The Haiku fallback tier is pinned to the
harvest's own resolved `extraction_model`, so turning the cascade on only *adds* a
local pre-tier; the paid tier is unchanged. Cascade telemetry
(`n_local_accepted` / `n_escalated_{abstain,ungrounded,error}` / `local_save_rate`)
is logged in the harvest summary — no silent behaviour.

**Verified end-to-end** (not just wired): the real `qwen2.5:3b` local tier ran
against a real `RawDocument` built from the copirate fixture, abstained, and the
cascade escalated to a $0 stub Haiku tier which returned the correct
`indirect_prompt_injection` primitive — fallback called exactly once,
`n_escalated_abstain=1`, `local_save_rate=0.0` surfaced. The harvest seam was
exercised in both flag states (off → `ExtractionAgent`, on → `CascadeExtractionAgent`).
The **accept path** (grounded valid local primitive → no escalation) is covered by
the stub-local unit test but was **never fired by any real off-the-shelf model** —
none of 3B/14B/32B produces a grounded primitive. 60 tests pass (13 new
cascade/field-eval + 47 extraction), ruff clean.

## Honest gaps / what a live headline needs

- **No paid run was spent.** The 0/2 recall (× 3 model sizes) is a real $0
  measurement; a Haiku *baseline* field-F1 (the bar the local model must clear) is
  a cents-level paid call, gated behind `--include-haiku`.
- **n = 2 source-doc fixtures** (03 is golden-only). The model axis is now covered
  (3B/14B/32B), but the *document* axis is thin — this is a directional signal + a
  mechanism proof, not a powered benchmark. A wider labeled-corpus A/B (>100
  scraped docs) would need a small paid Haiku baseline (~$1–2).
- **The path to an actual saving** is a *fine-tuned* local extractor. ROGUE owns
  the ideal distillation set for it — its own logged Haiku extractions
  (`attack_primitives` ⋈ source docs). That is the natural follow-on and the only
  route the literature actually validates.

## Novelty

The individual pieces are precedented (json-mode local inference; validation-gated
cascades; span-grounding as a precision signal). What is unreported is the
**combination inside a live red-team harvest**: a local-first extraction cascade
with an asymmetric never-drop rail and an anti-fabrication grounding floor, plus a
per-field agreement harness that *measures* where a local model may be trusted —
and the concrete negative result that off-the-shelf small abstains on real attack
disclosures. It composes with, and is the extraction-side sibling of, the Q2 judge
cascade (both: free cheap tier first, escalate only the ambiguous, metric-preserving
by construction). If pursued, it lands as a short **systems** note or a supporting
section, not a standalone pillar. Grounds on Lincoln 2605.05532 + Bumgardner 2308.01727.
