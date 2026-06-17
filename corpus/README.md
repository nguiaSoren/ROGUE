# ROGUE attack corpus

**The red-team that never sleeps.** A public, auto-updating, *measured* corpus of
LLM jailbreaks and prompt-injection attacks.

Most jailbreak repos are dumps: a wall of prompts with no evidence any of them
still work. This is the opposite. Every attack here carries a **measured
reproduction layer** — run against real models, judged by a calibrated judge, with
the score attached. You can see what breaches what, today, and re-run it yourself.

## What makes this different

- **Measured reproduction, not claims.** Each attack ships per-model breach
  verdicts and rates from real reproduction runs (`breaches anthropic/claude-haiku-4-5
  at 80% (4/5)`), judged by ROGUE's calibrated judge — not the author's "trust me, it
  works."
- **Freshness / decay.** `first_seen` and `last_verified` are on every record. A
  jailbreak that worked in March and is stone-cold dead now looks different from one
  verified this week. Defenses age; the corpus tracks it.
- **Structured taxonomy.** 15-family classification + entry vector + severity, so you
  can filter to *your* threat model (e.g. only `tool_use_hijack` via `tool_output`).
- **Blue-team framing.** ROGUE reproduces an attack's *carrier mechanism* against a
  neutral objective (eliciting the target's own system prompt) — it measures mechanism
  survival, not a harmful-content recipe. See [RESPONSIBLE_RELEASE.md](../RESPONSIBLE_RELEASE.md).
- **One-liner reproduce.** Every row carries `rogue reproduce <id>` — point ROGUE at
  your own `model × system_prompt × tools` and see if it breaches *you*.

## Files

- [`attacks.jsonl`](./attacks.jsonl) — one attack per line.
- [`attacks.json`](./attacks.json) — the full array plus generation metadata.
- [`INDEX.md`](./INDEX.md) — human-readable table.
- [`SCHEMA.md`](./SCHEMA.md) — every field, the measured layer, and the redaction rule.

## Responsible use

This corpus is **derived and redacted**. The actual prompt text is included **only for
attacks that are already public elsewhere** (Pliny / L1B3RT4S, public GitHub, arXiv,
public tweets/blogs). Anything ROGUE synthesized, or that isn't demonstrably public, has
its payload redacted to `[redacted — novel/synthesized; see ROGUE]` — but its measured
layer (families, vector, per-model breach rates, freshness, source attribution) is still
published. The **raw scraped corpus is never released.** Read
[RESPONSIBLE_RELEASE.md](../RESPONSIBLE_RELEASE.md) before using this — it is for
defenders and guardrail builders.

## How it stays current

Auto-updated from ROGUE's live breach matrix: the export
(`scripts/corpus/export_public_corpus.py`) re-reads the already-harvested matrix and
regenerates these files. It **never triggers a new harvest** — it only projects what
ROGUE has already measured. Publishing is manual, pending owner sign-off (see
`.github/workflows/publish-corpus.yml`).
