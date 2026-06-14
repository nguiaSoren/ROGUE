/**
 * proof.ts, the SINGLE SOURCE of verified, defensible marketing numbers.
 *
 * Every value below is traceable to a line in README.md or ROGUE_PLAN.md
 * (cited in the inline comment). Marketing pages must import from here rather
 * than hard-coding figures, so a corpus/judge re-measure updates the whole
 * site in one place.
 *
 * EXCLUDED BY DECISION: the headline ASR figures (90% JBB / 93% AdvBench) are
 * v1/v2-judge inflated (the v1 rubric rewarded engagement over harm-transfer,
 * see README judge-calibration). They are deliberately NOT exported here.
 */

// Defensible static citations, every value traces to a line in README.md /
// ROGUE_PLAN.md and is kept in sync with the live corpus (canonical: 15 attack
// families, 459 primitives, 8 deployment configs). These are NOT fetched at
// runtime; they are the verified marketing figures the commercial pages cite.
export const CORPUS = {
  primitives: 459, // canonical live corpus, attack_primitives rows
  harvested: 298, // README.md:25, public HuggingFace dataset
  families: 15, // canonical, OWASP LLM Top 10 + MITRE ATLAS aligned
  sources: 19, // README.md:41, open-web sources
  bdProducts: 5, // README.md:55, Bright Data products
  modelsTested: 6, // README.md:221
  reproductionTrials: 8321, // ROGUE_PLAN.md:2560, reproduction trials run
} as const

export const JUDGE_V3 = {
  humanAgreement: 89.3, // README.md:236, JailbreakBench, v3 recalibrated
  precision: 79.5, // README.md:236, up from 55% (v1)
  recall: 95.5, // README.md:236
  rankOf: 5, // [withheld]
  rank: 3,
} as const

export const SCHEDULER_AB = {
  winnerRankFrom: 22, // ROGUE_PLAN.md:451 (20-goal A/B), median winner-rank, fixed
  winnerRankToJBB: 11, // ROGUE_PLAN.md:451, contextual, JBB
  winnerRankToAdv: 13.5, // ROGUE_PLAN.md:451, contextual, AdvBench
  costFrom: 1.25, // ROGUE_PLAN.md:451, cost per successful breach (fixed)
  costTo: 0.74, // ROGUE_PLAN.md:451, cost per successful breach (contextual)
  costReductionPct: 41, // ROGUE_PLAN.md:451, −41%
  asrFrom: 50, // ROGUE_PLAN.md:451, 10/20
  asrTo: 60, // ROGUE_PLAN.md:451, 12/20
} as const

export const EFFICIENCY = {
  dailyHarvestUsdLow: 0.05, // README.md:90
  dailyHarvestUsdHigh: 0.3, // README.md:90
  judgeCostPerCallUsd: 0.0032, // README.md:242, caching + batch API
} as const

// Surface 2 — the human gate. Signed measurement of a reviewer's false-approve
// rate against an answer key provably independent of what it grades.
// HONEST CAVEAT: a single reviewer (n=1) — directional, not a population.
export const OVERSIGHT = {
  falseApproveRate: 33, // % — signed gate measurement, docs/research/oversight_meaningfulness.md
  ciLow: 20,
  ciHigh: 46, // bootstrap 95% CI [20%, 46%]
  reviewers: 1, // single reviewer — directional only
  source: "docs/research/oversight_meaningfulness.md",
} as const

// Surface 3 — the agent's memory. Signed measurement of canary leakage from a
// scrubbed shared skill pool under an extraction red-team.
// HONEST CAVEAT: weak open model, one standard pack, n=20 canaries.
export const SKILL_POOL = {
  leakageRate: 85, // % — canary recovered from 17 of 20 scrubbed skills (weak model)
  ciLow: 70,
  ciHigh: 100, // Wilson 95% CI [70%, 100%]
  recovered: "17/20",
  source: "docs/research/skill_pool_leakage.md",
} as const

/**
 * The strongest 4 proof points, ready to map directly into <StatCard>.
 * Every number traces to the consts above.
 */
export const PROOF_POINTS: ReadonlyArray<{
  value: string
  label: string
  sublabel: string
}> = [
  {
    value: "459",
    label: "attack primitives",
    sublabel: "15 families · 19 sources",
  },
  {
    value: "89.3%",
    label: "judge–human agreement",
    sublabel: "JailbreakBench, v3 recalibrated",
  },
  {
    value: "−41%",
    label: "cost per successful breach",
    sublabel: "adaptive ladder vs fixed order",
  },
  {
    value: "5",
    label: "Bright Data products",
    sublabel: "continuous open-web harvest",
  },
] as const
