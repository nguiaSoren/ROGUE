# Multilingual continuous coverage + camouflaged-intent tag (Q20)

ROGUE harvests jailbreaks from 19 open-web sources — every one English-centric — and reproduces every
attack in English. So the corpus it fires against any given deployment has a measured, striking
property: **~99% of harvested primitives carry no language variation whatsoever** (see *Measured*
below). That dataset observation motivates the whole build. The language axis is a *known-dangerous,
already-demonstrated* attack surface — GPT-4 fell to low-resource-language jailbreaks (Yong et al.
2310.02446) — yet the academic coverage of it is a handful of **static benchmark campaigns**. To our
knowledge, prior academic work evaluates multilingual robustness with those static campaigns rather than
as a **continuous, deployment-time measurement over harvested attacks**.

Q20's one-sentence claim: **ROGUE continuously measures English-vs-non-English safety regression on the
exact attack corpus deployed against a model.** *Continuous* here has a specific operational meaning: the
multilingual reproduction re-runs automatically whenever new harvested attacks enter the corpus or the
model panel changes — not a one-off campaign that produces a single table.

Three env-gated components, none of which moves an existing (English) verdict (off by default,
byte-identical when off):

1. **Translate-then-reproduce** (the core) — expand each attack into its untouched English baseline plus
   one translated, round-trip-gated variant per target language, fire them all, and measure the
   **per-deployment English-vs-non-English breach delta**.
2. **Multilingual harvest source** — non-English Reddit keyword discovery so in-the-wild non-English
   attacks enter the pipeline natively.
3. **Camouflaged-intent tag** — a cheap harvest-time prior for *stratifying* attacks by whether they
   hide a harmful ask behind a benign frame. **Orthogonal to the language axis and deliberately
   secondary** (see the note under *Measured*): it is a stratification aid, not part of the multilingual
   story, and would be the first thing to cut if the write-up needs to be tight.

Positioning (honest, per the marketing-honesty filter): **the contribution is the reusable measurement
*system* + the deployment-corpus framing — not the multilingual attack, which is prior art.** The novelty
is **the combination** — multilingual × continuous × per-deployment × real-harvested attacks — *not* "we
invented multilingual red teaming." Prior work established the vulnerability and measured it statically;
ROGUE assembles existing ideas (harvest → translate → reproduce → dashboard) into a system that observes
the regression *on the deployed corpus*, continuously.

## Paper grounding (read in full via crawl4ai; Elicit's numbers fact-checked against the papers)

- **MM-ART — Singhania et al., "Multi-lingual Multi-turn Automated Red Teaming" (arXiv 2504.03174).**
  The core "does translation raise breach?" evidence. VERIFIED: multi-turn depth alone lifts English ASR
  **+71%** (21→36% at turn 5); **Japanese × 5-turn is +195%** vs single-turn English (62% vs 21%) — but
  that headline is *translation × depth combined on the 4-larger-model subset*, **not** pure translation
  (the honest single-turn-translation delta is +9% for Latin scripts, **+45–79% for non-Latin**: ja
  +79%). Attacks are **machine-translated** (Amazon Translate); the design pattern we port is *reason in
  English, translate the prompt, judge in-language*. MM-ART also shows the **judge dominates the signal**
  (Claude Sonnet 3.5 caught 4–5× more violations than Llama-Guard-3) — so we disclose the judge.
- **Atil et al., "Do Methods to Jailbreak and Defend LLMs Generalize Across Languages?" (arXiv
  2511.00689, EMNLP 2025 Findings).** The load-bearing nuance and the reason the default panel spans
  **script × resource**: under *plain* queries low-resource languages are least safe, but **under
  jailbreak attacks the trend REVERSES** — high-resource languages (English) can be *least* safe because
  the model understands the adversarial framing well enough to be steered by it (a
  performance-vs-robustness tradeoff). Attacks "generalize across models but **inconsistently across
  languages**." Native-language judging beat translate-back (α > 0.70); a multilingual-embedding response
  classifier generalizes cross-lingually at F1 ≈ 0.87 (a cheap future pre-judge).
- **Deng et al., "Multilingual Jailbreak Challenges in LLMs" (arXiv 2310.06474, ICLR 2024).** The
  foundational anchor + the public **MultiJail** corpus (3,150 samples = 315 prompts × 9
  human-translated languages, github.com/DAMO-NLP-SG/multilingual-safety-for-LLMs) — free human-reference
  translations for validating our machine translation per language. LRL ≈ 3× more unsafe under plain
  translated queries; English AIM + translated prompt → ChatGPT 80.9%.
- **Zheng, Zandsalimy & Sushmita, "Behind the Mask: Camouflaged Jailbreaks" (arXiv 2509.05471).**
  Grounds the camouflaged-intent tag. VERIFIED: 500 prompts (400 harmful/100 benign), 7 dimensions, judge
  GPT-4o, targets Llama-3.1-8B / gemma-3-4b-it / Mistral-7B-v0.3; harmful scores 8.86–12.34/20,
  Implementation-Safeguard + Harmful-Potential all < 10; 94% Full Obedience on harmful prompts (binary
  reject/comply, no partial band). **Crucially, the paper argues keyword detection FAILS against
  camouflage** ("preserve semantic intent while altering token distributions") and prescribes LLM
  semantic reasoning — so our lexical tag is an explicit **weak prior, not a detector**, and it fires only
  on the **co-occurrence** of a benign frame AND a dual-use marker (Zheng's Table-2 false positive: an
  engineering-domain heuristic alone over-triggers on a benign gardening story).
- **Positioning papers.** Purpura 2503.01742 (survey) — does **not** list multilingual as an open gap in
  its §9 conclusion (it treats it as a documented vuln + the XSafety benchmark); §9 asks for "continuous
  monitoring and adaptive security" and attacks "diverse and relevant to a given target system." Belaire
  2508.04451 — "current automated methods … rely on brittle prompt templates or single-turn attacks,
  failing to capture the … interactive nature of real-world adversarial dialogues." Yong et al.
  2310.02446 (GPT-4 broke on low-resource languages) and Wang XSafety 2310.00905 are the vulnerability
  precedents. Marx & Dunaiski 2605.18239 (the existing `01_multilingual_african_languages.json` fixture):
  translation *quality* dominates jailbreak success (BLEU r=0.92); human > Google Translate by +12–20%.

## The default language panel (script × resource, every entry backed by a number)

`en` (reference, always fired untranslated) · `es` (HRL-Latin negative control, +9% @turn5) · `de`
(worst Latin, +30%) · `ar` (mid non-Latin, in all three papers) · `ja` (largest gap, +74%/+79%) · `bn`
(LRL worst case, ~3×). Extension offered, not default: `sw` (LRL-Latin, isolates resource from script),
`zh` (HRL non-Latin, exposes Atil's reversal). 5 of 8 have human parallels in MultiJail.
See `src/rogue/reproduce/multilingual/languages.py`.

## Controlling the translation-artifact confound

A translated attack could "break" because MT mangled it, not because translation bypassed alignment.
Controls, grounded in the papers:

- **Round-trip gate** — before a variant is fired, back-translate it and require content preservation
  (`translate.round_trip_ok`); empty/garbled output is dropped as **invalid** (never counted as safe or
  as a breach — Deng/Atil both carve out an invalid class).
- **The bias runs the safe way** — MM-ART Fig 3: MT artifacts *deflate* the low-resource signal, so an
  MT-driven multilingual breach is a **conservative lower bound**.
- **Native-language judging** is the recommended default (Atil α > 0.70); disclose the judge (MM-ART's
  4–5× judge gap).
- **MultiJail human parallels** validate our MT per language before a headline claim.

## Where it's wired (every surface — grepped, not trusted to the brief)

The brief named `harvest/sources/*` + "instantiator". Reality has more, all off-by-default,
byte-identical-when-off:

| surface | how | consumer |
|---|---|---|
| `scan.run_scan` (default `rogue scan` + SDK) | env `ROGUE_MULTILINGUAL`; `apply_multilingual` expands after m2s | `ScanReport.multilingual` `{n_variants,n_invalid,languages}` |
| `reproduce.endpoint_scan.scan_endpoint` (API / `--persist`) | env-gated `apply_multilingual` | `EndpointScanReport.n_multilingual_variants` + persist FK-remap |
| `reproduce_once.run_reproduction` (paid research arm) | `--multilingual`; expands `primitives` UP-FRONT | `breach_results.language` per row (delta query) |
| `harvest.discovery_agent.default_plugins` | env `ROGUE_MULTILINGUAL_HARVEST` → registers `multilingual_forum` | `RawDocument.metadata["language"]` |
| `harvest_once._to_orm_primitive` | env `ROGUE_CAMOUFLAGE_TAG` → sets tag | `attack_primitives.camouflage_score/label` |

**The load-bearing seam (the "wired ≠ run" trap).** `breach_results.primitive_id` is an FK and
`reproduce_once` builds `primitive_by_id`/`cells_left`/`prim_breached` from the `primitives` list. A
naïve fan-out at the pair level would (a) break those by-id dicts and (b) violate the FK with unknown
variant ids. So variants carry **distinct in-memory ids** (for aggregation) but each fired trial
persists against its **BASE** primitive_id with the language on the row (`expand.fire_identity` reads the
`_ml_lang`/`_ml_base` markers off `rendered.resolved_slots`) — FK valid, corpus not polluted, idempotent
on re-run. This was **verified by running it**, not just reading it (below).

## Measured offline ($0, read-only Neon census — `scripts/reproduce/replay_multilingual.py`)

Over the real 635-primitive corpus:

- **English-centrism — the motivating result.** Only 0.2% of primitives are `language_switching` family
  and 0.9% carry any language slot: **~99% of the harvested corpus contains no language variation
  whatsoever.** This is the dataset observation that justifies the feature — the corpus fired at every
  deployment is monolingual by construction, so any non-English regression is, today, entirely
  unmeasured.
- **Camouflaged-intent tag (secondary, orthogonal):** 1.9% camouflaged **[95% Wilson CI 1.1%, 3.3%]**,
  24.6% overt, 73.5% ambiguous — a deliberately conservative co-occurrence prior. This is a **weak
  lexical prior intended for stratified analysis, not attack detection** (Zheng shows keyword detection
  can't reliably catch camouflage) — a way to slice the corpus, not a classifier, and independent of the
  multilingual axis.

**NOT measured offline (the honest gap):** the English-vs-non-English **breach delta** across the panel.
That needs the paid `--multilingual` cross-model reproduce (real translation + real victims); the offline
census reports coverage + tag distribution only.

## Verification (wired ≠ run)

- 25 unit tests (`tests/test_multilingual_q20.py`): camouflage co-occurrence + 3 labels; language panel;
  Echo/LLM translator + round-trip; expand (distinct ids, provenance, invalid handling, non-translatable
  skip, `fire_identity` base-remap, overflow); gate off-identity + on-expand; harvest source + env-gated
  registration + fail-soft.
- **Drove all three fire surfaces via the REAL env resolver** (not only an injected config) with a
  counting panel + `EchoTranslator` ($0): `run_scan`/`scan_endpoint` fire base + one per language and
  surface the count; **off → byte-identical** (base only, no report key).
- **Ran `reproduce_once(multilingual=True)` end-to-end against a real local Postgres** (mock panel/judge,
  `EchoTranslator`, `escalate=False`): 1 base primitive → **3 breach_results rows all FK'd to the BASE
  id**, `language ∈ {NULL(en), es, ja}`, distinct breach_ids, **corpus still 1 primitive (not polluted)**
  — the FK-remap consumer proven, not assumed.
- Migrations 0045 (camouflage) + 0046 (breach language) apply **and reverse** on a real DB (full
  0001→0046 chain applies on a fresh DB).
- Camouflage persist-site env-gated: flag off → column NULL (byte-identical); on → tag set.
- `ruff` clean; full suite green.

## Status

BUILT + LOCAL (2026-07-09). Off by default at every surface. Migrations 0045/0046 present (additive,
nullable). Going live = push (approval) → set `ROGUE_MULTILINGUAL=on` (+ optionally
`ROGUE_CAMOUFLAGE_TAG` / `ROGUE_MULTILINGUAL_HARVEST`) on Render → one paid `--multilingual` cross-model
reproduce for the breach-delta headline. Production translation is a real paid Anthropic call
(`LLMTranslator`, no new dependency); tests/dry-runs use `ROGUE_MULTILINGUAL_TRANSLATOR=echo`.

## Publishable? — a module of ROGUE, not a standalone paper

Assess the two contributions separately (the split a reviewer would make):

- **Engineering / systems: strong.** The build states precisely what is new, what already exists, what is
  measured vs unmeasured, and what is offline vs online — and proves the integration *end-to-end*
  (migrations, persistence, the FK-remap, a real DB, all three fire surfaces run, not just wired). That
  is the credible half today.
- **Research / empirical: contingent on the paid run.** Without the multilingual reproduce, the honest
  reading is "measurement infrastructure." *With* a run that reveals model-specific multilingual
  regressions — e.g. a deployment safe in English that regresses in Japanese/Bengali (and, *if* Atil's
  reversal holds on real harvested attacks, a per-language ranking that itself differs by model — an open
  question this run would answer, not a claim) — the reading becomes "this infrastructure surfaces a
  deployment-specific regression that static benchmark campaigns were not designed to observe (they answer
  a fixed-corpus-once question, not one over continuously harvested attacks)." Those are very different
  outcomes, and the second is the one worth publishing.

**How it differs from prior work:** MM-ART/Atil/Deng each measure a multilingual gap *once, statically, on
synthetic/benchmark prompts, and produce one table* — they answer a different question. ROGUE measures the
gap *continuously, per deployment, on attacks harvested from the open web that are actually being fired at
that model* (the contribution stated up front: the measurement *system*, not the attack).

**Where it fits:** one module inside the larger ROGUE platform — alongside the provenance-instrumentation
framework, the persistent-memory channel, obfuscation, harvesting, reproduction — which together
frame ROGUE as an end-to-end adversarial *measurement* platform rather than a bag of isolated tricks. It
is paper-worthy in that context; it is **not** a standalone paper. The paid `--multilingual` cross-model
reproduce is the single gated experiment that upgrades it from "engineering infrastructure" to
"engineering + empirical insight"; the offline census (~99% English-only) is the motivating dataset
observation, not the result.

**LinkedIn: worth a post once the paid run lands — not before.** The honest hook today is the coverage
gap (99% English-only) + the framework; the striking number ("safe in English, breaks in language X") is a
"we're seeing…" note only after the cross-model run. The camouflaged-intent finding is a
measurement-integrity note (a weak lexical prior for stratifying the corpus), not a headline.
