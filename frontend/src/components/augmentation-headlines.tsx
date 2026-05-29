import type {
  EscalationStatsResponse,
  MutationStatsResponse,
  PersonaStatsResponse,
  StubbornnessStatsResponse,
} from "@/lib/api";

/**
 * Home-hero "§10.7 augmentation Δ" headline strip — 4 big numbers that tell
 * the deck claim story before the user scrolls.
 *
 * Each tile picks the *worst* config (highest Δ / lowest stubbornness) so the
 * numbers always tell a "wow, that's bad" story rather than averaging
 * everything into a milquetoast middle.
 *
 * Empty states render a muted "// no data" instead of fake zeros — same
 * convention as the sidebar widgets.
 */
export function AugmentationHeadlines({
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
  // PERSONA: worst-affected config = highest positive Δ.
  const personaDeltas =
    persona?.per_config
      .map((c) => c.max_delta)
      .filter((d): d is number => d !== null) ?? [];
  const personaWorst =
    personaDeltas.length > 0 ? Math.max(...personaDeltas) : null;
  const personaWorstConfig =
    personaWorst !== null
      ? persona?.per_config.find((c) => c.max_delta === personaWorst)
      : null;

  // ESCALATION: highest delta config.
  const escDeltas = escalation?.per_config.map((c) => c.delta) ?? [];
  const escWorst = escDeltas.length > 0 ? Math.max(...escDeltas) : null;
  const escWorstConfig =
    escWorst !== null
      ? escalation?.per_config.find((c) => c.delta === escWorst)
      : null;

  // MUTATION: worst pattern-matching score.
  const mutScores =
    mutation?.per_config
      .map((c) => c.pattern_matching_score)
      .filter((s): s is number => s !== null) ?? [];
  const mutWorst = mutScores.length > 0 ? Math.max(...mutScores) : null;
  const mutWorstConfig =
    mutWorst !== null
      ? mutation?.per_config.find(
          (c) => c.pattern_matching_score === mutWorst,
        )
      : null;

  // STUBBORNNESS: lowest avg-iters-to-breach (most vulnerable).
  const stubVals =
    stubbornness?.per_config
      .map((c) => c.avg_iters_to_breach)
      .filter((v): v is number => v !== null) ?? [];
  const stubMin = stubVals.length > 0 ? Math.min(...stubVals) : null;
  const stubMinConfig =
    stubMin !== null
      ? stubbornness?.per_config.find((c) => c.avg_iters_to_breach === stubMin)
      : null;

  return (
    <section className="space-y-2">
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
        augmentation impact · today
      </p>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <HeadlineTile
          accent="rogue-accent-persona"
          accentText="rogue-accent-persona-text"
          name="Persona wrap"
          big={
            personaWorst !== null
              ? `${personaWorst > 0 ? "+" : ""}${(personaWorst * 100).toFixed(0)}pp`
              : null
          }
          unit="breach-rate Δ"
          context={
            personaWorstConfig
              ? `worst on ${shortName(personaWorstConfig.config_name)}`
              : "no wrapped runs"
          }
          tone={personaWorst !== null && personaWorst > 0 ? "alarm" : "muted"}
        />
        <HeadlineTile
          accent="rogue-accent-escalation"
          accentText="rogue-accent-escalation-text"
          name="Multi-turn escalation"
          big={
            escWorst !== null
              ? `${escWorst > 0 ? "+" : ""}${(escWorst * 100).toFixed(0)}pp`
              : null
          }
          unit="vs single-turn"
          context={
            escWorstConfig
              ? `worst on ${shortName(escWorstConfig.config_name)}`
              : "no escalations"
          }
          tone={escWorst !== null && escWorst > 0 ? "alarm" : "muted"}
        />
        <HeadlineTile
          accent="rogue-accent-mutation"
          accentText="rogue-accent-mutation-text"
          name="Pattern-match leak"
          big={mutWorst !== null ? `${(mutWorst * 100).toFixed(0)}%` : null}
          unit="wording-only defenses"
          context={
            mutWorstConfig
              ? `worst on ${shortName(mutWorstConfig.config_name)}`
              : "no mutations"
          }
          tone={
            mutWorst !== null && mutWorst >= 0.25 ? "alarm" : "muted"
          }
        />
        <HeadlineTile
          accent="rogue-accent-stubbornness"
          accentText="rogue-accent-stubbornness-text"
          name="PAIR breaks @"
          big={stubMin !== null ? `${stubMin.toFixed(2)}` : null}
          unit="iters to crack"
          context={
            stubMinConfig
              ? `easiest: ${shortName(stubMinConfig.config_name)}`
              : "no PAIR runs"
          }
          tone={stubMin !== null && stubMin < 2 ? "alarm" : "muted"}
        />
      </div>
    </section>
  );
}

function HeadlineTile({
  accent,
  accentText,
  name,
  big,
  unit,
  context,
  tone,
}: {
  accent: string;
  accentText: string;
  name: string;
  big: string | null;
  unit: string;
  context: string;
  tone: "alarm" | "muted";
}) {
  const bigClass =
    big === null
      ? "text-muted-foreground"
      : tone === "alarm"
        ? "text-rogue-red"
        : "text-foreground";
  return (
    <div
      className={`rogue-card ${accent} border border-border rounded-lg p-4 bg-card/40 backdrop-blur-sm`}
    >
      <p
        className={`text-[10px] font-mono uppercase tracking-[0.2em] ${accentText}`}
      >
        {name}
      </p>
      <p className={`text-3xl font-bold mt-2 tabular-nums leading-none ${bigClass}`}>
        {big ?? "—"}
      </p>
      <p className="text-[10px] text-muted-foreground mt-1 leading-tight">
        {unit}
      </p>
      <p className="text-[10px] text-muted-foreground/70 mt-1.5 truncate" title={context}>
        {context}
      </p>
    </div>
  );
}

function shortName(name: string): string {
  return name.replace(/^Acme\s*·\s*/, "");
}
