# Encoding operators (Q16) — highest-yield guardrail-evasion families as live, gated obfuscation operators

**Status:** BUILT + offline-validated ($0). Live behind `ROGUE_OBF_EXTENDED` (off by default; byte-identical to today when off). Bypass-rate delta is the one pending live number — it rides the next scheduled reproduce run once the flag is on; no dedicated paid arm required.

## What this is

ROGUE already runs a deterministic obfuscation layer (`src/rogue/obfuscation/`): ten operators (`leetspeak`, `homoglyph`, `zero_width`, `fullwidth`, `zalgo`, and `base64`/`rot13`/`hex`/`unicode_escape`/`html_entity` decode-wraps) that skin an almost-defended payload so the reproduction panel measures whether a target defends the *technique* or merely the *exact surface string*. Q16 adds the four highest-yield families the baseline set was missing, taken from the 2026 guardrail-evasion literature, and — this is the point — adds a **CI coverage invariant** so a verified evasion family can never again silently lack a live operator.

The four new operators:

| operator | kind | what it does | paper |
|---|---|---|---|
| `nested_cipher` | wrap | RoguePrompt dual-layer: word-partition even/odd → Vigenère (key `RESEARCH`) the odd words → concatenate `[even ‖ ciphertext]` → ROT‑13 the whole → prepend a self-decode directive | Tafreshian 2511.18790 |
| `variation_selector_smuggle` | inline | hide the payload's UTF‑8 bytes in a run of emoji **variation selectors** trailing a benign carrier (visible surface = one emoji) | Hackett 2504.11168 |
| `unicode_tag_smuggle` | inline | map each printable-ASCII char to its invisible **Unicode-tag** twin (`U+E0000 + ord(c)`); many models still read tag chars as the ASCII they mirror | Hackett 2504.11168 |
| `diacritics` | inline | replace vowels with accented twins (`hèllö`); folds back through the existing NFKD + combining-strip | Hackett 2504.11168 |

`kind` follows the existing taxonomy: **inline** = in-band, a model that silently normalizes reads the same request (no decode instruction); **wrap** = encoded + an explicit decode instruction. The three invisible/visual injections are `inline` (like `zero_width`/`homoglyph`); the cipher is `wrap` (like `base64_wrap`).

## Paper grounding — and a fact-check the survey brief got wrong

The survey brief (Elicit) that seeded this build **misstated the headline RoguePrompt numbers**, exactly the "treat Elicit as a lead, never a citable source" hazard. Pulled and read in full:

- **Hackett et al., *Bypassing Prompt Injection and Jailbreak Detection in LLM Guardrails* (arXiv 2504.11168).** Character-injection attacks against six production guardrails (Azure Prompt Shield, Meta Prompt Guard, Vijil, Protect AI v1/v2, NeMo Guard). **Emoji smuggling reached 100% ASR** (the single highest family); **Unicode-tag smuggling 90.15%/81.79%** (prompt-injection/jailbreak). Protect AI v2 hardened the baseline (PI ASR 20.26%) and was *"only heavily bypassed by Emoji and Unicode tag Smuggling"* — the two families we add first. Diacritics/homoglyph/zero-width sit in the 44–76% band. These numbers are verified against the paper.
- **Tafreshian, *RoguePrompt: Dual-Layer Ciphering for Self-Reconstruction to Circumvent LLM Moderation* (arXiv 2511.18790).** The real method and numbers: partition the prompt into even/odd word subsequences, **Vigenère-encipher the odd words under the fixed key `RESEARCH`**, concatenate the plaintext even words + a decode recipe + the ciphertext, **ROT‑13 the composite**, and wrap it in a directive that tells the model to decode, decipher, re-interleave, and execute. Measured on GPT‑4o over **n=2,448** hard-rejected prompts: **84.7% bypass / 80.2% reconstruction / 71.5% execution** (strongest baseline ≤58.1% execution); effective across GPT‑4o, Gemini‑1.5, Llama‑3. The **313** figure is the size of the underlying StrongReject hard-reject corpus, not the eval, and the survey brief's inflated headline bypass figure appears nowhere in the paper. We implement the method faithfully and cite the paper's real result — **84.7% / n=2,448** — everywhere, and do not carry the brief's number.
- **Kumar et al., *Certifying LLM Safety against Adversarial Prompting* (arXiv 2309.02705).** The defense's exact, narrow guarantee: erase-and-check certifies robustness only against **bounded-length** token manipulation in three modes — adversarial **suffix**, **insertion**, **infusion** (e.g. 92% certified detection at suffix length 20). Encoding transforms (cipher, tag/variation-selector smuggling, homoglyph) are **outside its threat model** — they leave the bounded-edit ball entirely. This is the framing point: certified defenses guarantee a small neighborhood; these operators measure whether the model is robust *outside* it.

## Real wiring — every surface, not a standalone module

The operators live inside the paths ROGUE actually runs, gated by `ROGUE_OBF_EXTENDED` (off by default). `active_operators(extended=…)` is the seam: baseline ten always, plus the extended four only when opted in. Every enumeration site was moved onto it, so a flag-off run is byte-identical to today.

Forward (operator produces the variant):
- `src/rogue/reproduce/search/actions.py::cheap_mutation_actions` — the **live MCTS/bandit search** action space (`obf:*`).
- `scripts/reproduce/synthesize_obfuscations.py` — the **§10.7 augmentation sweep** that persists obfuscated children for the panel.
- `scripts/research/obfuscation_flip_rate.py` — the flip-rate research runner.
- `obfuscate()` in the module (default enumeration).

Backward (recover the plaintext so the variant is *usable*, not silently dropped):
- `src/rogue/reproduce/search/goal_preservation.py` — the live search gates every mutation through `check_goal_preserved`; a variant whose plaintext it can't recover is discarded. `nested_cipher` is reversed via `try_decode_nested_cipher`; tag/variation-selector fold through `canonicalize(decode_transport=True)`; `diacritics` fold through the pre-existing NFKD + combining-strip.
- `src/rogue/obfuscation/canonical.py` — tag + variation-selector decoding added under the existing `decode_transport=True` opt-in only. The harvest dedup path calls `canonicalize` **without** that flag, so it stays byte-identical; the variation-selector fold is guarded (run length ≥ 4 and a printable-UTF-8 round-trip) so real single presentation selectors (`❤️`) survive.

`apply_operator(name, …)` resolves against the full baseline+extended registry regardless of the flag, so a variant persisted under a prior flagged run is always re-applicable.

## The coverage invariant (the durable contribution)

`ENCODING_FAMILY_COVERAGE` maps every verified encoding family to its live operator and taxonomy grammar-node (`ENCODING_OBFUSCATION` / `INVISIBLE_INJECTION`). The CI test `tests/test_obfuscation.py::test_verified_families_map_to_live_operator` asserts every row resolves to a registered operator **and** a real `GrammarNode` — so a family the literature verifies can never silently lack an operator or a taxonomy home. Gaps surface in CI, not in a scan. (Multimodal visual smuggling is verified but deliberately out of scope for these text operators — it rides `multimodal_injection`.)

## Offline validation ($0) — the real number, and its ceiling

The build is deterministic, so it validates offline with no paid call. `scripts/research/q16_encoding_offline_validation.py` replays the operators over **N=215 real harvested jailbreak prompts** (`data/research/promptrend_corpus.jsonl`) and measures **non-neutering fidelity** — does the live goal-preservation gate accept the variant (so it actually fires) rather than drop it?

| operator | kept/N | rate | 95% Wilson CI |
|---|---|---|---|
| `nested_cipher` | 215/215 | 100.0% | [98.2%, 100.0%] |
| `variation_selector_smuggle` | 215/215 | 100.0% | [98.2%, 100.0%] |
| `unicode_tag_smuggle` | 215/215 | 100.0% | [98.2%, 100.0%] |
| `diacritics` | 214/215 | 99.5% | [97.4%, 99.9%] |

All four change the surface on 215/215. The single `diacritics` miss is benign: the payload carried an identifier `pAMK0CuYQ`, and the goal gate's canonicalizer leet-folded the `0`→`o` inside it, so exact-match recovery missed — an ID/leet interaction, not a neutered attack.

**Honest gap.** Fidelity means *the operator fires*, **not** that it bypasses a guardrail. The bypass-rate delta — "which of these families still breach frontier guardrails in 2026, and by how much over the baseline set" — needs the paid reproduction panel. Because the operators are in the live search action space, that number rides the **next scheduled reproduce run once `ROGUE_OBF_EXTENDED` is on** (marginal cost $0), or a dedicated cycle (~$35). Until then the offline fidelity above is the ceiling of what we can claim, and no bypass number is headlined.

## Going live

1. Merge (done: operators + wiring + CI coverage + offline validation, all green, ruff clean).
2. Flip `ROGUE_OBF_EXTENDED=on` in prod (its own explicit step) so the next scheduled reproduce run captures the flip-rate-per-encoding-family table.
3. Post-run: turn the offline fidelity framing into the measured bypass-rate delta in this doc and the flip-rate research runner; only then is any bypass number quotable.
