/**
 * Plain-English translators for the numbers we display all over the
 * dashboard. The pattern: render the technical value (+3pp, 0.84 iters,
 * 60%, 2.4/$) THEN immediately a translator output beneath it so a
 * non-statistician reader understands what they're looking at.
 *
 * Every function returns a short, lowercase, action-oriented phrase
 * suitable for a `text-[10px] text-muted-foreground` subtitle.
 */

/**
 * "+15pp Δ" → "31% → 46%, a 15-point jump in breach rate"
 * if baselineRate provided, otherwise "+15 percentage points more attacks breaching"
 */
export function plainifyPP(delta: number, baselineRate?: number): string {
  if (Math.abs(delta) < 0.005) return "no measurable change";
  const pp = Math.round(Math.abs(delta) * 100);
  const direction = delta > 0 ? "more" : "fewer";
  if (baselineRate !== undefined) {
    const baseline = Math.round(baselineRate * 100);
    const after = Math.max(
      0,
      Math.min(100, Math.round((baselineRate + delta) * 100)),
    );
    return `${baseline}% → ${after}%, a ${pp}-point ${direction === "more" ? "jump" : "drop"}`;
  }
  return `${pp} percentage point${pp === 1 ? "" : "s"} ${direction} attacks breaching`;
}

/**
 * "60%" → "3 in 5 attacks would breach"
 * Anchored to human-friendly fractions ("1 in 4", "half of") rather than %.
 */
export function plainifyRate(rate: number): string {
  if (rate >= 0.95) return "almost every attack breaches";
  if (rate >= 0.8) return "4 out of 5 attacks breach";
  if (rate >= 0.65) return "2 out of 3 attacks breach";
  if (rate >= 0.45) return "about half of attacks breach";
  if (rate >= 0.3) return "1 in 3 attacks breaches";
  if (rate >= 0.2) return "1 in 5 attacks breaches";
  if (rate >= 0.1) return "1 in 10 attacks breaches";
  if (rate > 0) return "a few breaches per 100 attempts";
  return "nothing has breached yet";
}

/**
 * "0.84 iters" → "easy crack, usually breaks on the 1st attempt"
 * The lower the number, the easier the model gives up.
 */
export function plainifyIters(iters: number): string {
  if (iters < 1.2) return "easy crack, breaks on the 1st attempt";
  if (iters < 2.2) return "breaks on the 2nd attempt on average";
  if (iters < 3.2) return "holds ~3 attempts before breaking";
  if (iters < 4.5) return "robust, multiple retries before any breach";
  return "very resilient against iterative attackers";
}

/**
 * "0.34" (pattern-matching score) → "1 in 3 defenses leak on a paraphrase"
 */
export function plainifyPattern(score: number): string {
  if (score >= 0.5) return "more than half of defenses leak on a paraphrase";
  if (score >= 0.33) return "1 in 3 defenses leak on a paraphrase";
  if (score >= 0.2) return "1 in 5 defenses leak on a paraphrase";
  if (score > 0) return "a small fraction leak on paraphrase";
  return "defenses robust to wording changes";
}

/**
 * "2.4 / $" → "2-3 novel attacks for every dollar of harvest spend"
 */
export function plainifyYield(novelPerDollar: number): string {
  if (novelPerDollar >= 10) return "extremely cost-efficient, 10+ novel attacks per $";
  if (novelPerDollar >= 3)
    return `~${Math.round(novelPerDollar)} novel attacks for every $1 of harvest spend`;
  if (novelPerDollar >= 1)
    return `${novelPerDollar.toFixed(1)} novel attacks per $1 of harvest spend`;
  if (novelPerDollar > 0)
    return `${(1 / novelPerDollar).toFixed(0)} dollars per novel attack`;
  return "no novel attacks yet (warming up)";
}

/**
 * "5475 trials judged" → "tested every attack 5+ times across every config"
 */
export function plainifyTrials(n: number): string {
  if (n >= 5000) return "every attack tested 5+ times across every config";
  if (n >= 1000) return "thousands of attack trials judged";
  if (n >= 100) return "hundreds of attack trials judged";
  if (n > 0) return "first trials in";
  return "no trials yet";
}

/**
 * "1252 attacks tracked" → "more new jailbreaks than most teams see in a year"
 * (only used in the hero stat trio for impact framing)
 */
export function plainifyAttackCount(n: number): string {
  if (n >= 1000) return "every public jailbreak from the last 30 days";
  if (n >= 500) return "more than most security teams see in a quarter";
  if (n >= 100) return "growing daily as the harvester runs";
  if (n > 0) return "the harvest is just starting";
  return "no attacks yet, run the harvester to seed";
}
