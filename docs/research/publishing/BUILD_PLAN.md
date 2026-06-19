# ROGUE — paper & blog BUILD PLAN (checkboxes)

*Last updated 2026-06-13. Companion to `PUBLICATION_MAP.md` + `references.bib`. Goal: ship 3 arXiv papers + 3 blog posts. **Drafts already exist** internally (`docs/research/*.md`) and **all figures are already rendered** (`docs/research/figs/`) — this plan converts them to publishable form, not from scratch.*

## At a glance — what each output is, where it goes, what's left (plain-language tracker)

**The shape: 4 papers + 1 optional blog; ignore the rest.** arXiv has no deadline and is the priority — never wait on a workshop or a blog to post to arXiv. Blogs are *independent* of the papers (you do **not** post a blog "first").

| Output | What it is | Where it goes | What YOU still do | Status |
|---|---|---|---|---|
| **P1 — Scheduler** | arXiv paper | arXiv **cs.CR** (×cs.LG) | compile on Overleaf → submit | ✅ written, figures done |
| **P2 — Judge calibration** | arXiv paper | arXiv **cs.CR** (×cs.CL) | compile → submit | ✅ written, figures done |
| **P3 — Reproducibility gap** | arXiv paper — *lead the endorsement ask with this* | arXiv **cs.CR** | compile → submit | ✅ written, 4 figures done |
| **Skill-pool leakage** | short workshop paper **+** blog | **arXiv now**; workshop later = a **NeurIPS 2026** workshop; blog = **Hugging Face** | compile `skill_leak/main.tex` → arXiv; *optionally* post `skill_leak/blog.md` on HF | ✅ written (paper + blog) |
| **Oversight meaningfulness** | **blog only** (honest n=1) | **LessWrong / AI Alignment Forum** + personal site | write & post the blog (recommended) | ⚪ draft exists, not posted; paper-upgrade **blocked** (needs n≥5 reviewers) |
| **Coverage-validity (ρ=0.35)** | **not its own output** — a supporting paragraph **inside P3** | (already in P3) | **nothing** | ✅ folded into P3 |
| **Discovery bandit** | **repo doc only** (not a paper/blog) | `docs/research/bandit_for_humans.md` | **nothing** (doc exists + linked) | ✅ documented |
| **Lessons / negative results** | **optional** blog, unwritten | personal site / Substack | optional — **skip-able** | ⚪ not written |

- **The 3 papers all go to one place: arXiv, primary `cs.CR`** (one endorsement covers all of cs.*; cross-list cs.LG/cs.CL per paper). Lead the endorsement ask with **P3**.
- **Post P2 with (or just before) P3:** P3's load-bearing instrument *is* P2 (the judge), so the 89.3–91.0% / κ≥0.80 numbers are only verifiable once P2 is on arXiv. Add P2's arXiv ID to P3's judge footnote when posting.
- **Blogs differ per output:** skill-leak → **Hugging Face**; oversight → **LessWrong / AI Alignment Forum** (+ personal site); the lessons post → **personal site / Substack**. A blog is never a prerequisite for a paper.
- **Workshop status (checked 2026-06-14):** spring/early-summer deadlines have passed — SaTML 2026 (Sep 2025), TrustNLP@ACL 2026 (Mar/Apr 2026), and **SeT-LLM @ KDD 2026** in Jeju, Korea (deadline was **5 Jun 2026** — missed by days). Next open window: **NeurIPS 2026 workshops** (Dec 2026; CFPs open ~Aug–Sep, deadlines ~late Sep), the natural home (Red Teaming GenAI / SoLaR lineage), 4–9pp, non-archival, arXiv-friendly. → **arXiv the skill-leak paper now; aim at a NeurIPS-2026 workshop in the fall. No workshop should delay arXiv.**
- **Oversight — recommended to post:** "meaningful human oversight of AI agents" is an active 2026 topic (EU AI Act Art. 14 + NIST RMF now demand *measurable, provable* oversight). The exact failure you measured — reviewers rubber-stamping outputs they don't fully evaluate (~33% false-approve, n=1) — is the field's named central failure mode. As an honest *method + instrument + PoC* post it's a real portfolio item in a hot area; it just can't be a *paper* without ≥5 reviewers.

---

## Status legend
`[ ]` todo · `[~]` in progress · `[x]` done. Cost tags: **$0**, **$LLM**, **$BD** (Bright Data).

---

## Phase 0 — shared setup (do once, unblocks everything)

- [ ] Pick a LaTeX skeleton — use `usenix`/`IEEEtran` for P1 (systems), `acl`/`neurips` style for P2/P3. arXiv accepts any.
- [x] `references.bib` — twice-verified, drop-in (done 2026-06-13).
- [ ] Decide canonical author block + affiliation line ("independent researcher" is fine).
- [ ] **arXiv account** + trigger endorsement request → get 6-char code (see Phase 5). One endorsement covers all 3 (all cs.* = one domain).
- [ ] Data-release split: `.gitignore` change that **publishes derived data** (`data/calibration/*`, `docs/research/figs/data/`, `data/research/*_results.json`, extracted `AttackPrimitive` JSONs) while **keeping `website/` + raw `raw_document` blobs private**. Add `RESPONSIBLE_RELEASE.md` (neutral-objective framing).
- [ ] `PAPERS.md` at repo root: each paper → modules → repro script → released data slice → figure files.
- [x] Add one-line pointer to the new `publishing/` folder in `docs/research/README.md` (no orphan). *(done 2026-06-14)*

---

## P3 — Reproducibility gap (measurement) · **LEAD PAPER for endorser** · target cs.CR · **$0**

*Draft: `reproducibility_gap_study.md` (results computed). Figures: `repro_gap_F1_funnel.png`, `F2_by_family.png`, `F3_scatter.png` (rendered).*

- [ ] Confirm the 3 figures are paper-resolution; regenerate via `scripts/research/reproducibility_gap_figs.py` if needed.
- [ ] Write abstract — **lead with the C2 null** ("17 sources claim ~100%; 7 reproduce; mean 13.3%") and the PrompTrend contradiction.
- [ ] Related work from `references.bib`: PrompTrend (**198** vulns, *positive* r=0.318 — the contrast), Jailbreak Foundry (paper-arm, gap≈0), StrongREJECT, Do-Anything-Now, JailbreakRadar.
- [ ] Methods: carrier-mechanism reproduction, neutral proxy objective, frozen Llama-8B anchor, v3 consummation judge as instrument.
- [ ] **Framing fixes:** source-gap = "consistent & growing on hard targets," NOT "established" (CIs touch at n_arxiv=79); fix PrompTrend stat to 198; state the proxy + version-drift + survivorship caveats.
- [ ] Fold **coverage-validity** (ρ=0.35, 0 reversals) as the "non-reproductions are adequately tested" support.
- [ ] Ethics/responsible-release paragraph (neutral objective, derived data only).
- [ ] Sign-off → arXiv submit (primary cs.CR; cross-list cs.CL, cs.LG).

---

## P2 — Judge calibration (methodology) · target cs.CR (×cs.CL) · **$0**

*Draft: `judge_calibration_paper.md` (Table 1 fully measured). Figures: `judge_F1_generalization.png`, `judge_F2_refine_to_ship.png`, `judge_F3_type_dependent.png`.*

- [ ] **Reframe the contribution** in abstract + intro: integration + independence-invariant rigor + self-diagnosing harness — NOT the consummation gate itself.
- [ ] Cite **StrongREJECT + The Jailbreak Tax** as the origin of willingness-vs-capability; cite CourtGuard/CompliBench on cross-class; position against both.
- [ ] Table 1 polish (JBB 91.0 / infodisc 97 / action 98.9 / fabrication 96.9 / κ / WildGuard / StrongREJECT).
- [ ] **Flag single-operator κ** explicitly as a limitation.
- [ ] Fold **coverage-validity** in as a section (companion calibration).
- [ ] Methods appendix: the 4-verdict vocab, the BreachType template, the independence lint.
- [ ] Sign-off → arXiv submit (primary cs.CR; cross-list cs.CL).

---

## P1 — Scheduler (systems) · **most novel** · target cs.CR (×cs.LG) · **$0 to post / $LLM to harden**

*Draft: `adaptive_orchestration_paper.md` + `scheduler_allocation_study.md`. Figures: F1–F10 + frozen CSVs in `figs/data/`.*

### Decide the n=3 question FIRST (free gate) — ✅ RESOLVED 2026-06-13
- [x] **Ran the free simulation** (`candidate_quota_ab.py analyze` + a read-only `attack_strategies` count). Result: **78 candidate-state techniques** in pool (22 ever evaluated → ~56 starved/unevaluated), 22 active, 7 needs_implementation.
- [x] **Branch resolved:** pool has **78 ≫ 20** candidates → **NO Bright Data harvest needed**; the $143.25 BD balance stays untouched. Go straight to the N=20 run.
- [x] Cost is **pure LLM** (target panel + batched/cached judge), ~**$30–80** for 20 distinct candidates both arms; bound with `--max-spend`.

### ⚠ PILOT RESULT (2026-06-13, run abq_1781291719, ~$9 actual)
- The `$5` pilot cost **~$9** (`--max-spend` caps escalation *per arm*; the base 96-pair sweep runs uncapped in both arms on top). N=20 will cost **more than $35**.
- Rotation admits only **3 candidates/run** (`cap=3`) → N=20 needs ~7 sweeps (~$60+) or a selection-cap change.
- **The causal contrast did NOT cleanly replicate:** quota=0 ran 3 distinct candidates (2 breached); quota=1 ran 1 (0 breached) — muddy/inverted vs the study's 3/3-vs-0. Likely cause: repertoire grew 7→**22 active**, so ~14 active harvested strategies now crowd candidates out of the ladder. ⚑ The original n=3 result's robustness is in question; a larger-N run risks a muddy/null result that would *weaken* P1.
- **Decision: prefer Option A (post on the existing 3/3 as existence proof). Do NOT scale to N=20 without first diagnosing (free) why the contrast washed out.**

### ⚑ DIAGNOSIS + targeted quota=3 run (2026-06-13, ~$3.57; cumulative ~$12–13)
- **Free rotation-membership diagnosis:** the pilot contrast washed out because the **$5 budget was too small**, NOT because the mechanism is broken. quota=1 eliminated early-stop (65→**0**) exactly as designed, but the budget cap then starved candidates (**105 `not_reached`**). Bottleneck moved from early-stop → budget.
- **Targeted single-arm quota=3 run (`abq_1781294554`, --max-spend 7, $3.57):** early-stop **0**, candidates **reached + evaluated** (15 attempts on 3 distinct), **1 of 3 breached + graduated** (beat voxtral-small). **Mechanism CONFIRMED.**
- **But the 3/3 effect is optimistic** — fresh candidates breach at **~33% (1/3)**, not 100%. ⚑ **The draft's 3/3 headline MUST be tempered** to a measured reach-breach rate, or replaced by the larger-N result below. Do not ship 3/3 as representative (no-stale-artifacts).
- **Costed path to venue-grade N≈20:** raise the per-run candidate selection cap (currently `cap=3`) + ~**$25 more** → ~20 reached candidates, ~6–7 breach vs 0 of 20 starved → Fisher exact p≈0.008. Stronger AND more honest than 3/3.

### ✅ VENUE-GRADE RESULT ACHIEVED (2026-06-13, run abq_1781308343, $14.57; cumulative ~$30)
- **Lever isolated:** distinct-candidates-evaluated is gated by `escalate_candidate_quota` (candidates/ladder) × #EVADE-parents — NOT the selection cap (`CAND_LADDER_CAP`) or budget. Set `CAND_LADDER_CAP=25` + `--single-quota 20` (4 parents × 20 = 80 candidate-slots).
- **Result: 8 of 20 reached candidates breached + graduated (40%) vs 0 of 20 under greedy/starved → Fisher exact p = 0.0033 (two-sided), 0.0016 (one-sided).** 100 candidate attempts. Graduating winners beat llama-3.1-8b, mistral-small (×2), gemini-3.1-flash-lite, + others (8 distinct per DB).
- **⚑ ACTION — update the draft:** replace the optimistic **3/3** headline with **8/20 (40%) graduate-when-reached vs 0/20 starved, p=0.003**. Present the original matched q0-vs-q3 arm (3/3 vs 0/3) as the small-N causal test AND this as the larger-N reach-rate. Honest caveat to state: the "0/20" baseline is the established greedy-starvation result (reachability ~7%), not a fresh randomized arm on these exact 20 — the matched causal arm is the original study's q0/q3.
- Regenerate the affected figure (cost-per-graduation / reachability) with the new numbers; reproduce command: `CAND_LADDER_CAP=25 ... candidate_quota_ab.py run --single-quota 20 --max-spend 22` (run-prefix abq_1781308343).
- **Decision: Option B succeeded — P1 now ships on the N=20 result, not the 3/3 existence proof.**

### Option A — post now (no spend) ← RECOMMENDED per pilot
- [ ] Reframe the 3/3-vs-0/3 capstone explicitly as an **existence demonstration**; foreground the **10,872-trial allocation-bias** result as the powered evidence.

### Option B — harden to venue-grade (**$LLM ~$40–150**)
- [ ] `candidate_quota_ab.py run --limit <N> --max-spend <cap>` for **N≈20** admitted candidates, both arms (quota=0 vs starvation+quota=3), judge **batched (50% off) + cached**.
- [ ] Report "k of 20 vs 0 of 20" with a **Fisher's exact p-value + CI**.
- [ ] Update `adaptive_orchestration_paper.md` / `scheduler_allocation_study.md` with the result; regenerate the affected figure (CLAUDE.md "keep the research record current").

### Write-up (both options)
- [ ] Abstract: allocation-as-capability-growth; reachability telemetry.
- [ ] Related work: AutoRedTeamer, AutoDAN-Turbo, TAP, Rainbow Teaming (all optimize the *opposite*); name the differentiator (non-evaluation as the bottleneck).
- [ ] Figures F1–F10 to paper resolution.
- [ ] Sign-off → arXiv submit (primary cs.CR; cross-list cs.LG).

---

## Blog 1 — Oversight meaningfulness · LessWrong→AF + personal site · **$0**

*Draft material: `oversight_meaningfulness.md`. Upgradeable to SoLaR 5pp.*

- [ ] **Top-up (optional, makes it a paper):** send `oversight_review.html` to **5+ reviewers** → each exports decisions → `run_gate_measurement.py --mode decisions` → pooled false-approve rate + CI over reviewers.
- [ ] Write the post: frame as **method + instrument + PoC**; independence-invariant + CI-gated staged autonomy; honest about n.
- [ ] Cite (link) DeepMind 2510.26518, Redwood AI-control, the "Complexities of Testing" + "Quest for Effectiveness" oversight papers.
- [ ] **Make a LessWrong account**, post there; ask an AF member to promote (can't self-post to AF).
- [ ] Mirror canonical copy on personal site.
- [ ] (If top-up done) → 5pp SoLaR submission from the same text.

---

## Blog 2 — Skill-pool leakage · Hugging Face community blog + personal site · **$5–20 $LLM to upgrade**

*Draft material: `skill_pool_leakage.md`. Upgradeable to Red Teaming GenAI / SaTML.*

- [ ] **Top-up (optional, makes it a paper):** `run_leakage_redteam.py` against **3–4 targets incl. one aligned model** + add the **paraphrase-recovery judge** (batched). Produces a leakage-vs-model-strength curve.
- [ ] Write the post: **construct-first** (cross-user canary leak from distilled shared skills; scrubbing ≠ containment); keep the 10%→85% rate-limit-artifact correction as a methods-honesty sidebar.
- [ ] Cite MEXTRA, ADAM, AgentLeak, SkillProbe, Trace2Skill; state the residual novelty (construct unoccupied as of 2026-06).
- [ ] **Make a Hugging Face account**, publish a community blog article; canonical copy on personal site; optional Substack mirror.
- [ ] (If top-up done) → 4–9pp workshop submission.

---

## Blog 3 — "Engineering lessons & negative results" (merged) · personal site/Substack · **$0**

*Merge: `bandit_for_humans.md` (discovery bandit) + grammar-efficacy null + payload-embedding negative + measured-remediation.*

- [ ] One honest post: "what didn't work + what we learned building a continuous red-team."
- [ ] Sections: the yield-bandit (README-level), the grammar null, the payload-embedding negative (silhouette≈0), the remediation that didn't hold (RA06).
- [ ] Publish on personal site + Substack mirror.

---

## Phase 5 — accounts & submission mechanics

- [ ] **arXiv:** register → from account, "endorsement" → request endorsement in cs.CR → arXiv emits a 6-char code → send to endorser (lead with P3) → once endorsed, persists for all cs.* submissions.
- [ ] **LessWrong:** register (lessworng.com); post Blog 1; request AF promotion.
- [ ] **Hugging Face:** register (huggingface.co); Blog 2 via "community → new blog article."
- [ ] **Personal site / Substack:** stand up the portfolio hub (canonical copies + links to arXiv + AF + HF).
- [ ] Cross-link everything (each paper → repo `PAPERS.md`; each blog → arXiv where applicable).

---

## Cost ledger (refine P1 via the free sim)

| Item | Budget | Est. | Gating |
|---|---|---|---|
| P1 free sim | — | $0 | run first |
| P1 harvest (only if <20 candidates) | BD | $0–40 | from $143.25 |
| P1 N=20 reproduction (both arms) | LLM | $40–150 | judge batched 50%+cached |
| P2, P3 | — | $0 | data collected |
| Oversight n≥5 | — | $0 | recruit 5 clickers |
| Skill-leak 3–4 models + paraphrase judge | LLM | $5–20 | cheap targets |

**Free-to-ship today:** P2, P3, all 3 blogs (base form), oversight top-up. **Paid, optional:** P1 N=20 ($LLM), skill-leak top-up ($LLM).

---

## Session log — 2026-06-13

- **P1 hardened (paid, ~$30 cumulative):** N=20 causal result landed — **8/20 graduate-when-reached vs 0/20 starved, Fisher p=0.0033**, cost-per-graduation fell to $1.44. Drafts updated: `adaptive_orchestration_paper.md` (abstract pt 4, §5 causal, §6 stopping rule) + `scheduler_allocation_study.md` (new §5.3b). `metrics.json` gained the `growth_k20` run; **F4 regenerated** (now 3 real points: $8.37 → $7.01 → $1.44). The 3/3 → 8/20 (40%) correction is in; honest baseline caveat stated (0/20 = established starvation, matched arm = original q0/q3).
- **P3 arXiv package WRITTEN** → `p3_reproducibility_gap/` (`main.tex` ~8pp, `references.bib` 9 twice-verified cites, `fig-funnel.png` + `fig-scatter.png` wired, `README.md` with build steps). Lead with the C2 null + the PrompTrend contradiction; AI-tell word-scan clean; LaTeX lints clean (no local `pdflatex` — build on Overleaf). Remaining: compile + eyeball, optional Fig 3, endorsement, submit.
- **P1 arXiv package WRITTEN** → `p1_scheduler/` (`main.tex` ~12pp = full 7-finding systems paper incl. the 8/20 N=20 result + cross-tier §6b tables; `references.bib` 6 twice-verified cites incl. Crescendo arXiv:2404.01833 + PyRIT arXiv:2410.02828, both verified this session; 3 figures: reachability, allocation-bias, cost-per-grad). Lints clean (braces 257/257, begin/end 12/12, no bare %, no AI-tell words, all 6 cite keys resolve). Honest framing baked in (3/3 = existence proof, 40% = measured tail rate, grammar A/B = underpowered null).
- **Convention:** each publishable paper = its own self-contained folder under `publishing/` with `main.tex` + figures + `references.bib` + `README.md` (build on Overleaf; no local TeX here).
- **P1 workshop cut WRITTEN** → `p1_scheduler/main_workshop.tex` (~6pp, the allocation spine only — reachability → 8/20 causal rate → economic inversion; drops grammar A/B, planner, allocation-bias detail, cross-tier §6b, growth loop). Lint clean.
- **P2 arXiv package WRITTEN** → `p2_judge_calibration/` (`main.tex` ~9–10pp, Table 1 across 6 calibrated instances, 3 figures, `references.bib` 8 twice-verified cites incl. JailbreakBench 2404.01318 + WildGuard 2406.18495 + Llama Guard 2312.06674, verified this session). Caught + fixed 3 figure↔caption mismatches by reading every PNG; all 3 figures referenced; lint clean. Honest "rigor not a new mechanism" positioning preserved.
- **Skill-leak top-up RUNNING** (bg `bdgrlz6ac`, ~$2–5): 4 Groq models weak→aligned + paraphrase judge. Model 1 reproduced the 85% baseline (17/20, 0 control FP). Curve in progress.
- **Skill-leak curve DONE (valid, liveness-guarded) + packaged** → `skill_leak/`: `main.tex` (~4–5pp workshop: Red Teaming GenAI / SaTML / SoLaR), `blog.md` (HF community), `references.bib` (6 twice-verified), `fig-curve.{pdf,png}` (4-model curve, alignment-not-size). Real numbers (85/100/65/35) match the source log; AI-tell clean; the liveness-guard / fake-0% story written up as a methods contribution; qwen inline-CoT caveat footnoted. Recorded in `docs/research/skill_pool_leakage.md`.
- **Next:** oversight top-up (Soren's call on Prolific n≥30 vs friends n=5–10); P2/P3 teasers when Soren generates them on claude.ai (briefs delivered); compile all packages on Overleaf.
