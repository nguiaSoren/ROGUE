import type {
  BanditStatsResponse,
  EscalationStatsResponse,
  MutationStatsResponse,
  PersonaStatsResponse,
  StubbornnessStatsResponse,
} from "@/lib/api";
import { AUGMENTATION_COPY, AUGMENTATION_ACCENTS } from "@/components/augmentation-meta";
import { SparkBars } from "@/components/spark";
import {
  plainifyIters,
  plainifyPP,
  plainifyPattern,
  plainifyYield,
} from "@/lib/plain-numbers";

/**
 * The "5 augmentations" hero section on /.
 *
 * Each augmentation gets a large card with:
 *   - the canonical eyebrow + plain-English headline + body (AUGMENTATION_COPY)
 *   - ONE hero stat extracted from the API response
 *   - a small chart pulled from the same response (or a fallback line)
 *   - a "live" or "no data yet" badge so visitors know if the card is
 *     showing real numbers or just the explanation.
 *
 * Server component, fully data-driven.
 */
export function AugmentationShowcase({
  bandit,
  persona,
  escalation,
  mutation,
  stubbornness,
}: {
  bandit: BanditStatsResponse | null;
  persona: PersonaStatsResponse | null;
  escalation: EscalationStatsResponse | null;
  mutation: MutationStatsResponse | null;
  stubbornness: StubbornnessStatsResponse | null;
}) {
  // --- Hero-stat extraction (one number per stress-test) ---
  const banditHot = bandit?.top_arms?.[0];
  const banditHeroValue = banditHot ? banditHot.mean_yield.toFixed(2) : null;
  const banditHeroUnit = banditHot ? "novel attacks / $" : "no warm arms yet";
  const banditPlain = banditHot ? plainifyYield(banditHot.mean_yield) : null;
  const banditChart =
    bandit?.top_arms.slice(0, 5).map((a) => ({
      label: a.arm_id,
      value: Math.round(a.mean_yield * 100) / 100,
    })) ?? [];

  // PERSONA, worst-case delta + the config that produced it (for plain text)
  const personaWorstRow =
    persona?.per_config
      .filter((c) => c.max_delta !== null)
      .sort((a, b) => (b.max_delta ?? 0) - (a.max_delta ?? 0))[0] ?? null;
  const personaWorst = personaWorstRow?.max_delta ?? null;
  // Logical Appeal (the only persona actually run) lifted breach rate on no
  // config, show the no-lift result honestly, not a confusing negative "Δ".
  const personaLifted = personaWorst !== null && personaWorst > 0.005;
  const personaHeroValue =
    personaWorst === null
      ? null
      : personaLifted
        ? `+${(personaWorst * 100).toFixed(0)}pp`
        : "no lift";
  const personaHeroUnit = personaLifted
    ? "max breach-rate Δ vs unwrapped"
    : "every config resisted the persona wrap";
  const personaPlain =
    personaWorst === null
      ? null
      : personaLifted
        ? plainifyPP(personaWorst, personaWorstRow?.baseline_breach_rate)
        : "Wrapping the attack in a persuasion persona didn't raise breach rate on any config, this model line reacts to intent, not tone.";
  const personaChart =
    persona?.per_config.slice(0, 5).map((c) => ({
      label: shortName(c.config_name),
      value: Math.round(Math.max(0, c.max_delta ?? 0) * 100),
    })) ?? [];

  const escWorstRow =
    escalation?.per_config
      .slice()
      .sort((a, b) => b.delta - a.delta)[0] ?? null;
  const escWorst = escWorstRow?.delta ?? null;
  const escHeroValue =
    escWorst !== null
      ? `${escWorst > 0 ? "+" : ""}${(escWorst * 100).toFixed(0)}pp`
      : null;
  const escPlain =
    escWorst !== null && escWorstRow !== null
      ? plainifyPP(escWorst, escWorstRow.baseline_breach_rate)
      : null;
  const escChart =
    escalation?.per_config.slice(0, 5).map((c) => ({
      label: shortName(c.config_name),
      value: Math.round(Math.max(0, c.delta) * 100),
    })) ?? [];

  const mutWorstRow =
    mutation?.per_config
      .filter((c) => c.pattern_matching_score !== null)
      .sort(
        (a, b) =>
          (b.pattern_matching_score ?? 0) - (a.pattern_matching_score ?? 0),
      )[0] ?? null;
  const mutWorst = mutWorstRow?.pattern_matching_score ?? null;
  const mutHeroValue =
    mutWorst !== null ? `${(mutWorst * 100).toFixed(0)}%` : null;
  const mutPlain = mutWorst !== null ? plainifyPattern(mutWorst) : null;
  const mutChart =
    mutation?.per_config.slice(0, 5).map((c) => ({
      label: shortName(c.config_name),
      value: Math.round((c.pattern_matching_score ?? 0) * 100),
    })) ?? [];

  const stubVals =
    stubbornness?.per_config
      .map((c) => c.avg_iters_to_breach)
      .filter((v): v is number => v !== null) ?? [];
  const stubMin = stubVals.length > 0 ? Math.min(...stubVals) : null;
  const stubHeroValue = stubMin !== null ? stubMin.toFixed(2) : null;
  const stubPlain = stubMin !== null ? plainifyIters(stubMin) : null;
  const stubChart =
    stubbornness?.refinement_type_distribution.slice(0, 5).map((r) => ({
      label: r.refinement_type,
      value: r.n_steps,
    })) ?? [];

  return (
    <section id="stress-tests" className="space-y-6 scroll-mt-24">
      <div className="space-y-2 animate-rogue-fade-up">
        <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
          §10.7 · stress tests
        </p>
        <h2 className="text-3xl md:text-4xl font-bold tracking-tight max-w-3xl">
          ROGUE doesn&apos;t just collect attacks.{" "}
          <span className="text-rogue-green">It evolves them.</span>
        </h2>
        <p className="text-base text-muted-foreground max-w-2xl leading-relaxed">
          Five techniques that turn a single harvested jailbreak into the
          attack a real adversary would actually mount against you. Each runs
          as a controlled A/B against your stack. Each gets a number.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ShowcaseCard
          accent="bandit"
          heroValue={banditHeroValue}
          heroUnit={banditHeroUnit}
          heroPlain={banditPlain}
          chartColor={AUGMENTATION_ACCENTS.bandit.raw}
          chart={banditChart}
          isLive={banditChart.length > 0}
        />
        <ShowcaseCard
          accent="persona"
          heroValue={personaHeroValue}
          heroUnit={personaHeroUnit}
          heroPlain={personaPlain}
          chartColor={AUGMENTATION_ACCENTS.persona.raw}
          chart={personaChart}
          isLive={(persona?.n_cells ?? 0) > 0}
        />
        <ShowcaseCard
          accent="escalation"
          heroValue={escHeroValue}
          heroUnit="lift from turn 1 → turn 3"
          heroPlain={escPlain}
          chartColor={AUGMENTATION_ACCENTS.escalation.raw}
          chart={escChart}
          isLive={(escalation?.n_configs_with_pairs ?? 0) > 0}
        />
        <ShowcaseCard
          accent="mutation"
          heroValue={mutHeroValue}
          heroUnit="of 'defended' attacks leaked on paraphrase"
          heroPlain={mutPlain}
          chartColor={AUGMENTATION_ACCENTS.mutation.raw}
          chart={mutChart}
          isLive={(mutation?.n_configs_with_pairs ?? 0) > 0}
        />
        <ShowcaseCard
          accent="stubbornness"
          heroValue={stubHeroValue}
          heroUnit="iterations to crack the easiest config"
          heroPlain={stubPlain}
          chartColor={AUGMENTATION_ACCENTS.stubbornness.raw}
          chart={stubChart}
          isLive={(stubbornness?.n_breached ?? 0) > 0}
          fullWidth
        />
      </div>
    </section>
  );
}

function ShowcaseCard({
  accent,
  heroValue,
  heroUnit,
  heroPlain,
  chartColor,
  chart,
  isLive,
  fullWidth = false,
}: {
  accent: keyof typeof AUGMENTATION_COPY;
  heroValue: string | null;
  heroUnit: string;
  heroPlain: string | null;
  chartColor: string;
  chart: { label: string; value: number }[];
  isLive: boolean;
  fullWidth?: boolean;
}) {
  const copy = AUGMENTATION_COPY[accent];
  const accentClasses = AUGMENTATION_ACCENTS[accent];
  return (
    <article
      className={`rogue-card ${accentClasses.border} border border-border rounded-xl p-6 md:p-7 bg-card/40 backdrop-blur-sm space-y-5 animate-rogue-fade-up ${
        fullWidth ? "lg:col-span-2" : ""
      }`}
    >
      <header className="space-y-2">
        <div className="flex items-baseline justify-between gap-3 flex-wrap">
          <p
            className={`text-[11px] font-mono uppercase tracking-[0.22em] ${accentClasses.text}`}
          >
            {copy.eyebrow}
          </p>
          <span
            className={`font-mono text-[9px] uppercase tracking-[0.2em] px-2 py-0.5 rounded ${
              isLive
                ? "bg-rogue-green/10 text-rogue-green border border-rogue-green/30"
                : "bg-muted/20 text-muted-foreground border border-border"
            }`}
          >
            {isLive ? "● live" : "○ no data"}
          </span>
        </div>
        <p className="text-lg md:text-xl font-semibold leading-snug">
          {copy.whatItIs}
        </p>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-[180px_1fr] gap-5 items-start">
        {/* Hero stat */}
        <div className="space-y-1">
          <p
            className={`text-4xl md:text-5xl font-bold tabular-nums leading-none ${
              heroValue ? accentClasses.text : "text-muted-foreground"
            }`}
          >
            {heroValue ?? ", "}
          </p>
          <p className="text-[11px] text-muted-foreground leading-snug">
            {heroUnit}
          </p>
          {heroPlain && (
            <p className="text-[11px] text-foreground/80 leading-snug pt-1 border-t border-border/40 mt-2">
              <span className="font-mono uppercase tracking-wider text-[9px] text-muted-foreground/70 block">
                in plain English
              </span>
              {heroPlain}
            </p>
          )}
        </div>

        {/* Mini chart */}
        <div className="min-w-0">
          {chart.length > 0 ? (
            <SparkBars color={chartColor} data={chart} />
          ) : (
            <p className="text-[11px] font-mono text-muted-foreground">
              {`// chart unlocks when the first batch lands`}
            </p>
          )}
        </div>
      </div>

      <p className="text-sm text-muted-foreground leading-relaxed border-t border-border pt-4">
        <span className="font-mono uppercase tracking-wider text-[9px] text-muted-foreground/70 block mb-1">
          why it matters
        </span>
        {copy.whyItMatters}
      </p>
    </article>
  );
}

function shortName(name: string): string {
  return name.replace(/^Acme\s*·\s*/, "");
}
