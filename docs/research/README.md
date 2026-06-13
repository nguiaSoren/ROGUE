# docs/research — studies, papers, and figures

The single home for **our own** research writeups (manuscripts, focused studies, lab notes, figure specs, the research-todo). *Distinct from the root `papers/` folder, which is downloaded **external** literature + red-team tooling (PolyJailbreak, Crescendo/pyrit, VPI-Bench, …) that the codebase depends on — do not confuse the two.*

## Contents

| File | What it is | Status |
|---|---|---|
| `judge_calibration_paper.md` | **Judge calibration + generalization** (the v3 content-transfer gate → per-rule consummation judges). Seeded 2026-06-08. | tracked · draft |
| `coverage_validity_study.md` | **Attack-coverage calibration** validity study — does coverage predict breach-detection power? (ρ=0.35, validated modest). 2026-06-08. | tracked |
| `reproducibility_gap_study.md` | **Grey-literature reproducibility gap** study skeleton — do community-claimed jailbreaks reproduce as carrier mechanisms in deployment context? (C1/C2/C3, n=56 claimed+measured, core runs on collected data). 2026-06-12. | tracked · skeleton |
| `measured_remediation_finding.md` | **Surface-1b measured remediation** lab note — catching a fix that *doesn't hold* (RA06 + the accept-loop hardening). 2026-06-09. | tracked |
| `grammar_efficacy.md` | The grammar-component predictive-power **null result** study (#TRS-C). | tracked |
| `bandit_for_humans.md` | The discovery/yield-bandit write-up (live-vs-observational honesty). | tracked |
| `adaptive_orchestration_paper.md` | The workshop paper — the cross-tier scheduler result. | gitignored (local) |
| `scheduler_allocation_study.md` | Focused study behind the scheduler paper. | gitignored (local) |
| `adaptive_orchestration_systems.md` | Lab notes for the orchestration work. | gitignored (local) |
| `paper_figures.md` | Figure specs. | gitignored (local) |
| `figs/` | Generated figures (F1–F10 PNGs) + `figs/data/` (frozen CSVs/metrics). Written by `scripts/paper_figs.py`. | gitignored (local) |
| `RESEARCH_TODO.md` | The prioritized research-track action list (e.g. the K-saturation curve). | gitignored (local) |

## Conventions

- **Figures:** `scripts/paper_figs.py` reads `docs/research/figs/data/` and writes PNGs to `docs/research/figs/`. Regenerate after any finding that changes the underlying numbers (CLAUDE.md "keep the research record current").
- **Tracked vs local:** drafts that are still moving or that duplicate internal planning are gitignored; writeups that are stable / partly public (grammar null-result, bandit, the judge paper) are tracked.
- **One topic per paper.** The scheduler/orchestration work and the judge-calibration work are *separate* papers (different subjects); the grammar null-result is its own study.
- **Provenance + honesty:** every reported number traces to `breach_results` / `data/calibration/` / a named external benchmark; mark pending/unmeasured results as pending (do not quote a number we haven't collected).
- [Oversight meaningfulness](oversight_meaningfulness.md) — Surface-2 human-gate: measuring a false-approve rate vs an independent key + the bias-laundering guard (novel; real number pending reviewers)
- [Skill-pool leakage](skill_pool_leakage.md) — Surface-3: measured adversarial leakage on a privacy-contained agent-skill pool (85% [70-100%]; canary ground truth; the first 10% was a rate-limit artifact; publishable)
- [Verified-promotion](skill_pool_promotion.md) — Surface-3: do accumulated skills help? 1/4 cleared the gate on held-out tasks (the gate works; reproduces SkillProbe); +3 bugs caught incl. a rate-limit artifact
- [Payload-embedding technique signal](payload_embedding_technique_signal.md) — Tier-A pilot: payload embeddings carry only a faint, non-separating technique signal (silhouette ≈ 0; n=45, MiniLM + prod embedder); confirms surface dominates technique → shelves the unified multimodal+multilingual embedding idea before Tier-B spend (negative result, on file)
- [**`publishing/`**](publishing/) — the arXiv/workshop **submission packages**: P1 scheduler, P2 judge-calibration, P3 reproducibility-gap, and skill-leak, each a self-contained `main.tex` + figures + `references.bib` + `README.md`. Also holds `PUBLICATION_MAP.md` (dissemination plan) and `BUILD_PLAN.md` (the at-a-glance tracker). Build on Overleaf.
