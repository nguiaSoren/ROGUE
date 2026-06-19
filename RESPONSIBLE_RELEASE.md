# Responsible release

ROGUE is a defensive red-team. This note states what it measures, what it releases, and what it deliberately does not.

## What ROGUE measures
ROGUE reproduces a harvested attack's **carrier mechanism** against a **neutral objective** — getting a target to disclose its own system prompt — not harmful-content attack-success-rate. A carrier that cannot elicit a model's own system prompt (a behavior models resist far less than, say, weapons synthesis) almost certainly fails at the harder original goal, so a carrier failure is strong evidence the carrier is dead, while a carrier success is *not* shown to deliver any harmful payload — which ROGUE never tests and never claims. This is what lets the work be published openly: the measured quantity is mechanism survival, not a recipe.

## What is released
Derived, defensive artifacts only:
- Calibration corpora and the figure data behind the papers (frozen CSVs / results JSONs).
- Extracted `AttackPrimitive` records — the canonical, deduplicated *structure* of an attack (family, vector, slotted template), not a working end-to-end exploit.
- The public **dataset is access-gated** on Hugging Face: download requires agreeing to defensive-research-only terms, so the corpus reaches researchers and guardrail builders rather than the next attacker.

## What is never released
- The **raw scraped corpus** — `website/`, raw page text, and the Neon `raw_document` blobs — is never bulk-released, for two reasons: Bright Data's terms of service, and third-party copyright on the scraped pages.
- Secrets, customer data, and internal planning are kept out of the public repo by `.gitignore`.

## Reporting
If you find a vulnerability in ROGUE itself, or believe a released artifact crosses the defensive line, open a private security advisory on the repo rather than a public issue.
