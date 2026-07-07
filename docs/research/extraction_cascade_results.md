# Extraction cascade — raw local-model sweep receipts (Q17)

Verbatim evidence behind the negative result in
[`extraction_cascade.md`](extraction_cascade.md): three off-the-shelf `qwen2.5`
sizes run through the real `ExtractionAgent` `local/` branch against the golden
source-doc fixtures. Kept so the finding is auditable **without re-pulling three
models** (reproduction otherwise needs Ollama + a slow 32B inference pass).

## Reproduce

```bash
# $0, local — Ollama serving qwen2.5:{3b,14b,32b}
OPENAI_BASE_URL=http://localhost:11434/v1 OPENAI_API_KEY=ollama \
  uv run python scripts/extract/eval_extractor_fields.py \
  --models local/qwen2.5:3b,local/qwen2.5:14b,local/qwen2.5:32b
```

**Environment.** Ollama (Apple silicon, 24 GB), `temperature=0` (deterministic),
extraction prompt `v3` + `_LOCAL_SCHEMA_HINT` (the field-contract + enum vocab
injected into the local system prompt). Fixtures: `01` multilingual jailbreak
paper (arXiv HTML), `02` copirate-365 indirect-prompt-injection CVE (blog HTML).
Long docs head+tail-truncated to ~16 KB for the LLM (ROGUE's standard TPM cut).
Run date: 2026-07-08.

## Verbatim raw model output (`_call_local_json`, pre-normalizer)

| model | fixture | raw JSON the model emitted | normalizer verdict |
|---|---|---|---|
| **qwen2.5:3b** | multilingual | `{"is_attack": false, "reason": "The provided HTML content does not describe any specific attack or vulnerability."}` | abstain → None |
| **qwen2.5:3b** | copirate | `{"is_attack": false, "reason": "…a blog post about various AI vulnerabilities … but it does not explicitly describe any specific attack mechanism."}` | abstain → None |
| **qwen2.5:14b** | multilingual | `{"is_attack": false, "reason": "…a footer section of a webpage … does not contain any information about an exploit or attack."}` | abstain → None |
| **qwen2.5:14b** | copirate | `{"is_attack": true, "attack_primitive": "Data exfiltration via image rendering and delayed tool invocation to maintain persistence in Microsoft Copilot."}` | **R5 demote** (no `payload_template`) → None |
| **qwen2.5:32b** | multilingual | `{"is_attack": false, "reason": "…a footer section of a web page … does not contain any description or details related to an attack primitive."}` | abstain → None |
| **qwen2.5:32b** | copirate | `{"is_attack": true, "AttackPrimitive": "Prompt Injection"}` | **R5 demote** (no `payload_template`) → None |

**Recall 0/2 for every model.** No model produced a usable `AttackPrimitive`.

## What the receipts show

- **3B** — no recognition. Flatly `is_attack: false` on both real attacks.
- **14B / 32B — recognition without structuring.** On the copirate CVE both flag
  `is_attack: true` and the 14B's prose summary is *materially accurate* ("data
  exfiltration via image rendering and delayed tool invocation") — but neither
  emits the structured fields. They nest a value under a wrapper key
  (`attack_primitive` / `AttackPrimitive`) and hand back a prose summary (14B) or
  a two-word label (32B) instead of a `payload_template`, so the R1–R8 normalizer
  (R5) demotes to `is_attack: false`. **Prompt-resistant:** `_LOCAL_SCHEMA_HINT`
  explicitly says "emit fields at the top level, do NOT nest under a wrapper key,
  payload_template = the actual attack text," and at temperature 0 both models
  deterministically ignore it.

So scaling params **15×** (3B→32B) *and* handing the model the schema both leave
it at 0/2 — the failure is neither capacity nor prompting. It is the free-text
`payload_template` synthesis (Lincoln 2605.05532's predicted weak field), and it
is why the fix is a **fine-tune**, not a bigger download.

## Honest caveats

- **The multilingual abstention is partly a preprocessing artifact.** Both larger
  models describe the input as a *"footer section"* — the head+tail truncation of
  that arXiv HTML fed them boilerplate/nav rather than the method section. So the
  clean signal is **copirate** (recognized-but-unstructured); the multilingual
  recognition failure is confounded by truncation and should not be over-read.
- **n = 2 source-doc fixtures** (fixture 03 is golden-only). The *model* axis is
  now covered (3B/14B/32B); the *document* axis is thin — directional + a
  mechanism proof, not a powered benchmark.
- **No Haiku baseline here** (that is a paid call). This artifact is the local
  side only; the bar it must clear is Haiku's own field-F1, gated behind
  `--include-haiku`.

## Scorer self-check (golden as a perfect extractor, $0, deterministic)

The field-eval scorer is validated independently of any live model by scoring the
golden fixture against itself:

- structural macro field-agreement (enum/bool/set/dict/ordinal) = **1.00**
  (family, vector, payload_slots, … all exact);
- `payload_template` **span-grounding varies by attack type** — **0.26** for the
  reconstructed research-paper attack (01) vs **0.67** for the copied-blog payload
  (02). That variance is why grounding is used as an *anti-fabrication floor*
  (0.15), not a correctness gate.
