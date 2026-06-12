# Verified-promotion: do accumulated agent skills actually help? (Surface 3)

*Lab note · ROGUE Surface 3 (agent memory) · build-08 §4 · 2026-06-11. Companion to the leakage note.*

## The claim
A shared agent-skill pool grows by accumulation, and the implicit assumption is that more skills = a more capable agent. Surface 3 refuses to assume it: a skill enters the pool's `active` set ONLY after a measured net-positive effect on a held-out set — net-effect = repairs − regressions, with a bootstrap CI, and the gate admits IFF the repair-fraction CI lower bound clears 0.5 (confidently repairs MORE OFTEN than it regresses). Continuously re-verified (a skill that helped last month can regress as the base model/codebase drifts). Popularity is explicitly NOT a ranking signal.

## First real measurement (2026-06-11)
30 grounded held-out tasks (security/SQL/debug/api/web, expected outcomes from real CWE/OWASP/CrewAI sources); a weak agent (Groq `llama-3.1-8b-instant`) run WITH vs WITHOUT each candidate skill injected; each rollout pair graded by the Anthropic net-effect judge (REPAIR/REGRESSION/NEUTRAL). Of the 4 skills with enough applicable tasks for a CI:

| skill | tasks | repairs | regressions | neutral | net | repair-frac CI | verdict |
|---|---|---|---|---|---|---|---|
| skill-030 | 5 | 0 | 0 | 5 | 0 | [0,0] | REJECT |
| skill-035 (OWASP input-validation) | 6 | 0 | 2 | 4 | -2 | [0,0] | REJECT |
| skill-036 (OWASP output-encoding) | 7 | 1 | 0 | 6 | +1 | [1,1] | **PROMOTE** |
| skill-049 (security hardening) | 12 | 0 | 1 | 11 | -1 | [0,0] | REJECT |

**1 of 4 skills verified net-positive** (skill-036). Injecting a generic harvested skill was overwhelmingly **neutral** (it changed nothing) and occasionally a regression; only skill-036 produced a net repair. The gate blocked 3 of 4 from the `active` pool.

> **Correction (transparency).** A first run reported **0 of 4** — an *artifact*: the Groq rollout client had no retry/backoff, so ~90% of rollout calls rate-limited into error strings, and the judge graded error-vs-error as NEUTRAL (a fake all-neutral result). The labeler's "it's all neutral / short-circuit" instinct caught it. Re-run with the fixed runner: **1 of 4**.

> **Honest caveat (a real limitation, not an artifact).** skill-036 cleared on a **single decisive instance** (1 repair, 0 regressions, 6 neutrals) — the repair-fraction bootstrap CI `[1,1]` is degenerate at n=1 decisive, so a one-off repair clears the gate. This argues for a **minimum-decisive-instances guard** (require ≥3–5 decisive instances before the CI gate can fire) — a refinement on top of the `>0.5` threshold fix.

## Why it matters
This reproduces the SkillProbe result the spec cites (the large majority of accumulated skills do not survive an audit) on our own pool, with numbers: accumulated skills are NOT free wins, and a verified-promotion gate catches the ones that don't earn their place — exactly the assurance the product sells. An assurance gate that rubber-stamped these would be worse than none.

## Two bugs the real run + adversarial verifier caught (both fixed)
1. **Gate threshold:** the obvious implementation bootstrapped the repair-fraction and admitted on `ci_low > 0` — which tests "some repairs", not "repairs more often than regressions". It promoted clearly NET-NEGATIVE skills (4 repairs / 16 regressions). Fixed: gate on `ci_low > 0.5`. (A methods note: a "verified-promotion gate" must test the rate against 0.5, not 0.)
2. **Judge interface:** the gate called the judge as a bare callable; the real `net_effect_judge()` returns a judge object whose `.grade` is async (`.grade_sync` is the blocking wrapper). The callable test stubs hid it — the live default path raised. Fixed: the gate accepts either, preferring `grade_sync`. (The recurring "fakes hide live wiring" lesson, again.)

## Honest caveats
- **n: 4 skills, weak agent, small held-out sets (5–12 tasks).** A stronger agent, better skill↔task matching, or larger held-out sets could promote some skills; 1/4 is this configuration, not a universal claim. The point demonstrated is the GATE (it measures + rejects), not "these specific skills are bad".
- **The net-effect judge is now calibrated (2026-06-12):** SHIP gate at **100% agreement** vs an independently-labeled, deliberately-hard 20-case set (verbose-neutral traps + subtle/false-flag regressions) — `data/calibration/net_effect_report.json`. So the **1-of-4 number is claim-grade** (carries measured judge precision). Caveat: n=20, 0 disagreements → the CI is degenerate at [100%,100%]; a larger set would give an informative interval.
- ⚑ Possibly publishable alongside the leakage finding: a measured verified-promotion gate on a real harvested skill pool, plus the two implementation traps.
