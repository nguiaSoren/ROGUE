import type {
  EscalationStatsResponse,
  MutationStatsResponse,
  PersonaStatsResponse,
  StubbornnessStatsResponse,
} from "@/lib/api";

/**
 * Top-of-feed "augmentation A/B at a glance" KPI strip.
 *
 * Surfaces the §10.7 disciplined-sweep headline numbers — 4 tiles, one per
 * augmentation — color-matched to the sidebar widgets so the visual link
 * is immediate. Each tile shows:
 *   - the augmentation name (color-accented label)
 *   - a single primary metric (breach rate or avg-iters)
 *   - a one-line "what this means" subtitle
 *
 * Empty states are handled inline — when an augmentation has no data
 * yet, the tile renders a muted "// no data" placeholder rather than a
 * fake number.
 */
export function AugmentationStrip({
  persona,
  escalation,
  mutation,
  stubbornness,
}: {
  persona: PersonaStatsResponse | null;
  escalation: EscalationStatsResponse | null;
  mutation: MutationStatsResponse | null;
  stubbornness: StubbornnessStatsResponse | null;
}) {
  // PERSONA: max Δ across configs vs unwrapped baseline. Logical Appeal (the
  // only persona run) lifted no config, so show the no-lift result honestly.
  const personaMaxDelta = persona?.per_config
    .map((c) => c.max_delta)
    .filter((d): d is number => d !== null)
    .reduce((a, b) => Math.max(a, b), -Infinity);
  const personaHasData =
    personaMaxDelta !== undefined && personaMaxDelta !== -Infinity;
  const personaLifted = personaHasData && personaMaxDelta > 0.005;
  const personaMetric = !personaHasData
    ? null
    : personaLifted
      ? `+${(personaMaxDelta * 100).toFixed(0)}pp`
      : "no lift";

  // ESCALATION: max Δ across configs (escalated breach rate − parent baseline).
  const escDeltas = escalation?.per_config.map((c) => c.delta) ?? [];
  const escMaxDelta = escDeltas.length > 0 ? Math.max(...escDeltas) : null;
  const escalationMetric =
    escMaxDelta !== null
      ? `${escMaxDelta > 0 ? "+" : ""}${(escMaxDelta * 100).toFixed(0)}pp`
      : null;

  // MUTATION: max pattern-matching score (higher = config matches surface, not intent).
  const mutScores = mutation?.per_config
    .map((c) => c.pattern_matching_score)
    .filter((s): s is number => s !== null) ?? [];
  const mutMaxScore = mutScores.length > 0 ? Math.max(...mutScores) : null;
  const mutationMetric =
    mutMaxScore !== null ? `${(mutMaxScore * 100).toFixed(0)}%` : null;

  // STUBBORNNESS: min avg-iters-to-breach across configs (lower = more vulnerable).
  const stubAvgs = stubbornness?.per_config
    .map((c) => c.avg_iters_to_breach)
    .filter((v): v is number => v !== null) ?? [];
  const stubMinIters = stubAvgs.length > 0 ? Math.min(...stubAvgs) : null;
  const stubbornnessMetric =
    stubMinIters !== null ? `${stubMinIters.toFixed(2)} iters` : null;

  return (
    <section className="space-y-2 animate-rogue-fade-up" style={{ animationDelay: "0.15s" }}>
      <div className="flex items-baseline justify-between">
        <h2 className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
          stress-test A/B · §10.7
        </h2>
        <p className="font-mono text-[10px] text-muted-foreground">
          best lift per technique
        </p>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StripTile
          accent="rogue-accent-persona"
          accentText="rogue-accent-persona-text"
          name="Persona wrap"
          metric={personaMetric}
          unit={
            !personaHasData
              ? "no wrapped runs yet"
              : personaLifted
                ? "Δ vs baseline"
                : "every config resisted"
          }
          tooltip="Max breach-rate Δ across configs (PAP-style persuasion wrap vs unwrapped). Negative/zero = the wrap didn't raise breaches."
        />
        <StripTile
          accent="rogue-accent-escalation"
          accentText="rogue-accent-escalation-text"
          name="Multi-turn escalation"
          metric={escalationMetric}
          unit={escalationMetric ? "Δ vs single-turn" : "no escalations yet"}
          tooltip="Crescendo-style 3-turn arc breach rate vs the single-turn parent"
        />
        <StripTile
          accent="rogue-accent-mutation"
          accentText="rogue-accent-mutation-text"
          name="Pattern-match audit"
          metric={mutationMetric}
          unit={mutationMetric ? "wording-leak rate" : "no mutations yet"}
          tooltip="Fraction of parent-defended cells where the mutated variant slipped through (higher = pattern matching)"
        />
        <StripTile
          accent="rogue-accent-stubbornness"
          accentText="rogue-accent-stubbornness-text"
          name="PAIR stubbornness"
          metric={stubbornnessMetric}
          unit={stubbornnessMetric ? "min iters to breach" : "no PAIR runs yet"}
          tooltip="Average iterations PAIR needed to crack the easiest config (lower = vulnerable)"
        />
      </div>
    </section>
  );
}

function StripTile({
  accent,
  accentText,
  name,
  metric,
  unit,
  tooltip,
}: {
  accent: string;
  accentText: string;
  name: string;
  metric: string | null;
  unit: string;
  tooltip: string;
}) {
  return (
    <div
      title={tooltip}
      className={`rogue-card ${accent} border border-border rounded-lg p-3 bg-card/40 backdrop-blur-sm`}
    >
      <p className={`text-[10px] font-mono uppercase tracking-[0.2em] ${accentText}`}>
        {name}
      </p>
      <p className="text-2xl font-bold mt-1.5 tabular-nums">
        {metric ?? <span className="text-muted-foreground text-base font-normal">—</span>}
      </p>
      <p className="text-[10px] text-muted-foreground mt-0.5 leading-tight">
        {unit}
      </p>
    </div>
  );
}
