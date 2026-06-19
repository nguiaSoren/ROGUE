---
license: mit
language: [en]
tags: [llm-security, jailbreak, prompt-injection, red-team, threat-intelligence]
pretty_name: ROGUE Attacks 2026-05
size_categories: [n<1K]
---

# ROGUE Attacks 2026-05

Continuous-harvest dataset of LLM attack primitives discovered across
Reddit, X, arXiv, GitHub, security blogs, MITRE ATLAS, and OWASP LLM Top
10 between {start_date} and {end_date}. Each primitive is a portable,
slot-templated attack pattern with reproducibility score, severity, source
provenance (URL + Bright Data product used), and family classification.

License: MIT. Built by ROGUE (github.com/<handle>/rogue), a Bright Data ×
lablab.ai hackathon submission, May 2026. Powered by Bright Data.

## Schema

One JSONL record per attack, mirroring the ROGUE `AttackPrimitive` schema.

## Citation

```
@misc{rogue_attacks_2026_05,
  author = {Obounou Nguia, Soren},
  title  = {ROGUE Attacks 2026-05: A Continuous-Harvest Dataset of LLM Attack Primitives},
  year   = 2026,
  url    = {https://huggingface.co/datasets/<handle>/rogue-attacks-2026-05}
}
```
