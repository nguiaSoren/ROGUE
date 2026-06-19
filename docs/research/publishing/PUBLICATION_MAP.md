# ROGUE — publication map & dissemination plan

*Last updated 2026-06-14. The decision record for what gets published where, in what form, and what to fix first. Companion file: `references.bib` (every prior-art citation, twice-verified against arXiv + a second independent index). Source findings live one level up in `docs/research/`.*

## At a glance — what each output is, where it goes, what's left (plain-language tracker)

**The shape: 4 papers + 1 optional blog; ignore the rest.** arXiv has no deadline and is the priority — never wait on a workshop or a blog to post to arXiv. Blogs are *independent* of the papers (you do **not** post a blog "first").

| Output | What it is | Where it goes | What YOU still do | Status |
|---|---|---|---|---|
| **P1 — Scheduler** | arXiv paper | arXiv **cs.CR** (×cs.LG) | compile on Overleaf → submit | ✅ written, figures done |
| **P2 — Judge calibration** | arXiv paper | arXiv **cs.CR** (×cs.CL) | compile → submit | ✅ written, figures done |
| **P3 — Reproducibility gap** | arXiv paper — *lead the endorsement ask with this* | arXiv **cs.CR** | compile → submit | ✅ written, 4 figures done |
| **Skill-pool leakage** | **TMLR paper** (upgraded from workshop) + blog | **TMLR** (archival); blog = **Hugging Face** | run the de-confounding Featherless census (Items 1–4) → fill numbers → compile → submit to TMLR | 🔧 reframed for TMLR 2026-06-16 (liveness = spine; retitled "A Dead Call Cannot Leak"; construct scope fixed); **paid grid sweep pending** |
| **Oversight meaningfulness** | **blog only** (honest n=1) | **LessWrong / AI Alignment Forum** + personal site | write & post the blog (recommended) | ⚪ draft exists, not posted; paper-upgrade **blocked** (needs n≥30 reviewers) |
| **Coverage-validity (ρ=0.35)** | **not its own output** — a supporting paragraph **inside P3** | (already in P3) | **nothing** | ✅ folded into P3 |
| **Discovery bandit** | **repo doc only** (not a paper/blog) | `docs/research/bandit_for_humans.md` | **nothing** (doc exists + linked) | ✅ documented |
| **Lessons / negative results** | **optional** blog, unwritten | personal site / Substack | optional — **skip-able** | ⚪ not written |

- **The 3 papers all go to one place: arXiv, primary `cs.CR`** (one endorsement covers all of cs.*; cross-list cs.LG/cs.CL per paper). Lead the endorsement ask with **P3**.
- **Post P2 with (or just before) P3:** P3's load-bearing instrument *is* P2 (the judge), so the 89.3–91.0% / κ≥0.80 numbers are only verifiable once P2 is on arXiv. Add P2's arXiv ID to P3's judge footnote when posting.
- **Blogs differ per output:** skill-leak → **Hugging Face**; oversight → **LessWrong / AI Alignment Forum** (+ personal site); the lessons post → **personal site / Substack**. A blog is never a prerequisite for a paper.
- **Workshop status (checked 2026-06-14):** spring/early-summer deadlines have passed — SaTML 2026 (Sep 2025), TrustNLP@ACL 2026 (Mar/Apr 2026), and **SeT-LLM @ KDD 2026** in Jeju, Korea (deadline was **5 Jun 2026** — missed by days). Next open window: **NeurIPS 2026 workshops** (Dec 2026; CFPs open ~Aug–Sep, deadlines ~late Sep), the natural home (Red Teaming GenAI / SoLaR lineage), 4–9pp, non-archival, arXiv-friendly. → **arXiv the skill-leak paper now; aim at a NeurIPS-2026 workshop in the fall. No workshop should delay arXiv.**
- **Oversight — recommended to post:** "meaningful human oversight of AI agents" is an active 2026 topic (EU AI Act Art. 14 + NIST RMF now demand *measurable, provable* oversight). The exact failure you measured — reviewers rubber-stamping outputs they don't fully evaluate (~33% false-approve, n=1) — is the field's named central failure mode. As an honest *method + instrument + PoC* post it's a real portfolio item in a hot area; it just can't be a *paper* without ≥30 reviewers.

## Decision: one public repo, papers link into it

No startup → maximum disclosure is the correct strategy. **arXiv timestamps priority**, which is the only thing protecting the two currently-undefended findings (oversight; the C2 null). Plan: **one public ROGUE repo** linked from every paper/post (no per-paper repos), plus a `PAPERS.md`/reproduce index mapping each paper → modules → repro script → released data slice. Release *derived* artifacts (calibration corpora, frozen figure CSVs, results JSONs, extracted `AttackPrimitive` JSONs); **never** bulk-release the raw scraped corpus (`website/`, raw page text, Neon `raw_document` blobs) — Bright Data ToS + third-party copyright. Add a responsible-release note: ROGUE measures a *neutral carrier objective* (system-prompt exfiltration), not harmful-content ASR.

## The map

| Output | Vehicle | Category / Venue | Status | Fix before shipping |
|---|---|---|---|---|
| **P1 — Scheduler** (allocation-as-capability-growth) | arXiv (systems) | cs.CR (×cs.LG) | Ready | N=20 causal run **done** (8/20 vs 0/20, Fisher $p=0.003$ — now the measured capstone, not n=3); foreground that + the 10,872-trial allocation-bias result |
| **P2 — Judge calibration** (consummation gate, cross-class) | arXiv (methodology) | cs.CR (×cs.CL) | Ready | Cite StrongREJECT + Jailbreak Tax for the gate (don't claim it); flag single-operator κ; fold coverage-validity in as a section |
| **P3 — Reproducibility gap** (source-heterogeneity + C2 null) | arXiv (measurement) | cs.CR | Ready — **lead with this for the endorser** | Cite PrompTrend (**198** vulns, opposite sign) + Jailbreak Foundry; lead with the contradiction; source-gap = "consistent & growing on hard targets," not "established" |
| **Oversight meaningfulness** | LessWrong → AI Alignment Forum + personal site | — | Blog (paper-upgrade blocked) | Method + instrument + PoC, honest about n=1. SoLaR-*paper* upgrade needs n≥30 independent reviewers — **not available**, so it stays a blog. |
| **Skill-pool leakage** | `skill_leak/` **TMLR paper** + Hugging Face blog (+ optional Substack) | **TMLR** (archival; was Red Teaming GenAI workshop) | **Reframed for TMLR — paid census pending** | Liveness guard is now the spine, leakage curve the support (retitled "A Dead Call Cannot Leak"; construct scope = instruction-following, not scrubbing-reconstruction, made explicit). TMLR upgrade work (`scripts/memory/leakage_model_grid.json` 24-model de-confounding census + CoT answer/reasoning split + `--runs` t-interval + `select_judge_subset.py` 2nd-annotator) is **built + verified**; the one paid Featherless sweep fills the numbers. See `docs/research/skill_pool_leakage.md`. |
| **Coverage-validity** (ρ=0.35) | Section/appendix inside P3 (and optionally P2) | — | Supporting only | Never headlines; gives teeth to every "this didn't reproduce" |
| **Discovery bandit** | README / docs explainer (`bandit_for_humans.md`), at most one section of the lessons post | — | README-level | Commodity ε-greedy; not a research contribution |
| **Bandit + grammar/embedding negatives + measured-remediation** | One "engineering lessons & negative results" blog | personal site / Substack | Blog | Merge the three into one honest post |

## Per-paper detail

### P1 — Scheduler (systems) — *most novel*
- **Claim:** in a self-growing red-team, evaluation **allocation** is a capability-growth mechanism, not an efficiency layer. A greedy first-breach-short-circuit ladder starves harvested candidates (reachability 7%, 85% of eligible strategy-appearances lost to early-stop); reachability telemetry + starvation-aware ordering + a candidate-quota drive candidate-tier reachability 7%→98% and convert starved candidates into graduated capabilities.
- **The causal capstone (N=20, done):** 8 of 20 starved candidates graduated under the growth schedule vs 0 of 20 under the identical-input greedy baseline (Fisher exact $p=0.003$) — a *measured* result, no longer the thin 3/3 existence proof (one flip no longer kills it). Backed by well-powered core evidence (reachability across the full rotation; allocation bias over 10,872 trials). The paid N=20 reproduction sweep has been run and written into the paper + `adaptive_orchestration_paper.md`.
- **Closest prior art:** AutoRedTeamer, AutoDAN-Turbo, Capital-One bandit, TAP — all optimize the *opposite* direction (prune/early-stop to save budget). None measures reachability/starvation in an early-stop attack cascade.

### P2 — Judge calibration (methodology) — *most complete*
- **Claim:** one **consummation-gate** template ("engagement ≠ breach; consummation = breach") instantiates calibrated breach judges across breach classes (harm-transfer, info-disclosure, unauthorized-action, fabricated-value), with a CI-gated self-diagnosing REFINE/SHIP harness and an independence invariant.
- **Measured:** JBB 70.3→89.3→91.0% human agreement; info-disclosure 97%; unauthorized-action 98.9% (tool-trace); fabrication 96.9%; WildGuardTest 88.5%; StrongREJECT scored ~26% more conservatively; in-dist FP 2.56%.
- **The catch:** the gate concept itself is **not original** — StrongREJECT and The Jailbreak Tax own the willingness-vs-capability distinction; CourtGuard/CompliBench own cross-class judging. **Reframe the contribution as the integration + the independence-invariant rigor + the self-diagnosing harness**, not the gate. Flag single-operator κ.

### P3 — Reproducibility gap (measurement) — *lead with this for the endorser*
- **Claim:** most grey-literature-claimed jailbreaks do not survive as working *carriers* under conservative judging in deployment context; community-sourced attacks reproduce worse than paper-sourced; claimed potency does not predict reproduction.
- **Measured (collected data, $0):** C1 carrier reproduction 40.5% (best-of-5) → 9.0% (frozen Llama anchor) → 3.7% (robust Claude-Haiku); C2 Spearman(claimed, measured) = −0.098 [−0.374, +0.171] (n=56) — *of 17 sources claiming ~100%, only 7 reproduce, mean 13.3%*; C3 family ordering ⊥ claimed ordering. Temperature-robust; re-extraction uniformity audit done.
- **The catch:** the source-gap CIs *touch* at n(arxiv)=79 → state it as "consistent & growing on hard targets," not "established." Lead with the C2 null because it **contradicts** PrompTrend's positive r=0.318 — that disagreement is the citable hook. Use the corrected PrompTrend stat: **198** vulnerabilities, not 352.
- **Support:** cite the coverage-validity result (ρ=0.35, 0 reversals) so non-reproductions read as "adequately tested," not "weakly tested."

## Blog venues (verified)

| Venue | Academics | Recruiters | Solo-poster? | Citable | Use for |
|---|---|---|---|---|---|
| **LessWrong → AI Alignment Forum** | High (in safety) | High | Post to LW freely; AF promotion is member-gated | Yes (cited in arXiv refs) | Oversight meaningfulness; the lessons post (safety framing) |
| **Personal site / domain** | Med | High | Yes | Yes | Canonical copy of everything (the portfolio hub) |
| **Hugging Face community blog** | Med (LLM-sec) | Med–High | Yes (any account) | Yes | Skill-pool leakage (security/practitioner framing) |
| **Personal Substack** | Med | High | Yes | Yes | Distribution mirror for the lessons/security posts |
| Medium / dev.to | Low | Low–Med | Yes | Weak | Syndication mirror only — never the home of a finding |
| distill.pub | — | — | **Closed** (hiatus since 2021) | — | Use the template, self-publish; no journal to submit to |
| Apollo / Redwood / FAR / Confirm Labs blogs | Very High | Very High | **No** (team-only) | Yes | The quality bar, not a venue you can submit to |

## arXiv mechanics

- **Endorsement is per-*domain*, and all of `cs.*` is one domain.** An endorser with ≥3 arXiv cs papers from the last ~5 years can endorse you for cs.CR / cs.CL / cs.LG / cs.AI **all at once**; the endorsement is **persistent** (covers future submissions), not per-paper. They vouch for category-fit, **not** correctness — they don't read the paper in detail.
- **Mechanics:** trigger an endorsement request from your arXiv account → it generates a 6-char code → send to the endorser → they enter it on the endorsement form. (Jan 2026 policy: institutional email alone no longer qualifies a first-time author; the personal-endorsement path is the relevant one.)
- **The Hiskias plan:** one endorsement unlocks all three papers. Lead the ask with **P3** (most unambiguously cs.CR / "red teaming," memorable hook), show **P2** as the rigorous companion; **don't** lead with P1 (ML-systems flavored + the visible n=3). Frame: *"I have three security/red-team preprints ready — could you endorse me for cs.CR?"* Then submit all three (primary cs.CR; cross-list cs.LG/cs.CL).

## Page length — focused, not monographs

| Paper type | Main body | + refs/appendix | Anchor limits |
|---|---|---|---|
| Empirical / measurement (P3) | 6–9 pp | 10–20 pp | NeurIPS 9pp, ICML 8pp (refs/appendix unlimited) |
| Methodology (P2) | 8–10 pp | 12–25 pp | — |
| Systems (P1) | 11–12 pp | 15–25 pp | USENIX/OSDI 12pp body |
| Workshop (the blog→paper upgrades) | 4–5 pp (short) / 8–9 pp (long) | + unlimited appendix | SoLaR 5pp; Red Teaming GenAI 4–9pp |

Fitting workshops: **IEEE SaTML** (12pp; also Position/SoK), **SoLaR** (5pp), **Red Teaming GenAI** (4–9pp), **TrustNLP** (ACL short/long), **ICLR Trustworthy-AI / Agents-in-the-Wild** workshops.

## Open decisions

1. **Data-release split** — confirm the `.gitignore` change that releases derived data (calibration corpora, figure CSVs, results JSONs, extracted primitives) while keeping `website/` + raw `raw_document` blobs private.

*Resolved:* **(a) P1 N=20 paid run — done** (8/20 vs 0/20, Fisher $p=0.003$; now the measured capstone). **(b) Skill-leak blog→workshop upgrade — done** (4 models + paraphrase judge + liveness guard; paper in `skill_leak/`). **(c) Oversight blog→paper upgrade — not pursued** (needs n≥30 independent reviewers, not available; stays a blog at honest n=1).

## Honesty guardrails (so professors/recruiters see signal, not garbage)

- Every prior-art citation is twice-verified in `references.bib` — no hallucinated IDs.
- Don't overclaim novelty where prior art owns it (P2 gate; the bandit; attestation mechanism).
- Don't publish the two thin findings as *results* — publish them as *method + proof-of-concept*, honest about n.
- Keep the research record current per CLAUDE.md: if the N=20 run happens, write the Fisher result into `adaptive_orchestration_paper.md` / `scheduler_allocation_study.md` and regenerate the figure.
