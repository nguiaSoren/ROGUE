# Skill-leak multi-model run (2026-06-13) — DIAGNOSIS: curve is NOT valid

Raw log: `skill_leak_curve_2026-06-13.log`. Run: `run_leakage_redteam.py --model <M> --max-templates 4 --paraphrase-judge` over 4 Groq targets.

## Verdict: only ONE data point is real
The reported "85% → 0% → 0%" strength curve is an artifact. Verified by a post-run liveness probe + a direct Groq per-model status check.

| Model | Reported | Real status | Trust |
|---|---|---|---|
| `llama-3.1-8b-instant` | 85% (17/20) | live, answering | ✅ VALID (re-confirms the prior baseline) |
| `gemma2-9b-it` | 0% (0/20) | **HTTP 400 — decommissioned on Groq** | ❌ GARBAGE (all calls failed; a dead call can't leak) |
| `openai/gpt-oss-120b` | 0% (0/20) | live (HTTP 200) but returns **empty `content`** to `_groq.groq_chat` | ❌ LIKELY ARTIFACT (reasoning-model output-field mismatch → empty resp graded as non-recovery) |
| `llama-3.3-70b-versatile` | errored (traceback) | live (HTTP 200); single call works | ⚠️ NO DATA (128-call sweep rate-limited; transient) |

**Control FP=0 does NOT rule out the artifact** — an errored/empty control also recovers nothing.

## Why this matters
This is the same failure mode as the original 10%→85% correction (dead calls report as non-recovery). It was caught *before* publication this time by the verification step. Do not report any 0% from this run as "model resists."

## Redo plan (when resuming — needs fixes first, then ~$2–5)
1. **Drop `gemma2-9b-it`** (decommissioned). Pick currently-live Groq models, e.g. `llama-3.1-8b-instant` (weak), `llama-3.3-70b-versatile` (strong/aligned), `moonshotai/kimi-k2-instruct` or a `qwen` mid, and an aligned non-reasoning model.
2. **Fix reasoning-model content extraction** in `scripts/memory/_groq.py` — `gpt-oss-*` put output in a reasoning field; the helper reads only `message.content` and gets ''. Either parse the reasoning field or avoid reasoning models as targets.
3. **Pace harder** to avoid the sweep rate-limit that killed `llama-3.3-70b` (lower concurrency / longer backoff, or `--max-templates 3`).
4. **Add a liveness assertion** to `run_leakage_redteam.py`: fail loudly if >X% of target calls return error/empty, instead of silently reporting 0% (this is the structural fix that prevents the artifact class entirely).

## State of the skill-leak finding
Still rests on the single weak-model number (llama-3.1-8b, 85%). The multi-model strength curve is NOT yet established — the blog/workshop upgrade is pending a clean redo.
