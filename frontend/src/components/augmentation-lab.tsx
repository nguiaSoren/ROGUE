"use client";

import { useMemo, useState } from "react";
import type {
  EscalationStatsResponse,
  MutationStatsResponse,
  PersonaStatsResponse,
  StubbornnessStatsResponse,
} from "@/lib/api";
import { AUGMENTATION_ACCENTS } from "@/components/augmentation-meta";
import { ProviderLogo } from "@/components/ui/provider-logo";
import { plainifyRate } from "@/lib/plain-numbers";

/**
 * Interactive "play with it" lab.
 *
 * Pick a deployment config, toggle the three augmentation techniques (persona
 * wrap / multi-turn escalation / wording mutation), and watch the estimated
 * breach rate animate from baseline → augmented.
 *
 * The math: for the chosen config, baseline = stubbornness.n_breached /
 * n_pair_cells (if non-null) OR the persona baseline_breach_rate.
 * Each enabled toggle ADDS its observed config-specific Δ (capped at 100%).
 * This is an upper-bound estimate, not a perfect simulation — clearly
 * labeled as "estimated".
 */
export function AugmentationLab({
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
  // Pool of configs that exist in at least one augmentation's per_config table.
  const configs = useMemo(() => {
    const m = new Map<
      string,
      { config_id: string; config_name: string; target_model: string }
    >();
    persona?.per_config.forEach((c) =>
      m.set(c.config_id, {
        config_id: c.config_id,
        config_name: c.config_name,
        target_model: c.target_model,
      }),
    );
    escalation?.per_config.forEach((c) =>
      m.set(c.config_id, {
        config_id: c.config_id,
        config_name: c.config_name,
        target_model: c.target_model,
      }),
    );
    mutation?.per_config.forEach((c) =>
      m.set(c.config_id, {
        config_id: c.config_id,
        config_name: c.config_name,
        target_model: c.target_model,
      }),
    );
    stubbornness?.per_config.forEach((c) =>
      m.set(c.config_id, {
        config_id: c.config_id,
        config_name: c.config_name,
        target_model: c.target_model,
      }),
    );
    return Array.from(m.values());
  }, [persona, escalation, mutation, stubbornness]);

  const [selectedConfigId, setSelectedConfigId] = useState<string | null>(
    configs[0]?.config_id ?? null,
  );
  const [personaOn, setPersonaOn] = useState(false);
  const [escalationOn, setEscalationOn] = useState(false);
  const [mutationOn, setMutationOn] = useState(false);
  const [pairOn, setPairOn] = useState(false);

  const computed = useMemo(() => {
    if (!selectedConfigId) {
      return { baseline: 0, augmented: 0, ingredients: [] as Ingredient[] };
    }
    const personaRow = persona?.per_config.find(
      (c) => c.config_id === selectedConfigId,
    );
    const escRow = escalation?.per_config.find(
      (c) => c.config_id === selectedConfigId,
    );
    const mutRow = mutation?.per_config.find(
      (c) => c.config_id === selectedConfigId,
    );
    const stubRow = stubbornness?.per_config.find(
      (c) => c.config_id === selectedConfigId,
    );

    // Best baseline source, in order of preference.
    let baseline = 0;
    if (personaRow) baseline = personaRow.baseline_breach_rate;
    else if (escRow) baseline = escRow.baseline_breach_rate;
    else if (
      stubRow &&
      stubRow.n_pair_cells > 0 &&
      stubRow.never_breach_rate !== null
    ) {
      baseline = 1 - stubRow.never_breach_rate;
    }

    let augmented = baseline;
    const ingredients: Ingredient[] = [];

    if (personaOn) {
      const d = personaRow?.max_delta ?? 0;
      const contribution = Math.max(0, d);
      augmented += contribution;
      ingredients.push({
        key: "persona",
        label: "Persona wrap",
        delta: contribution,
        accent: AUGMENTATION_ACCENTS.persona.raw,
      });
    }
    if (escalationOn) {
      const d = escRow?.delta ?? 0;
      const contribution = Math.max(0, d);
      augmented += contribution;
      ingredients.push({
        key: "escalation",
        label: "Multi-turn escalation",
        delta: contribution,
        accent: AUGMENTATION_ACCENTS.escalation.raw,
      });
    }
    if (mutationOn) {
      const d = mutRow?.pattern_matching_score ?? 0;
      const contribution = Math.max(0, d) * 0.5; // half-weight: not directly comparable
      augmented += contribution;
      ingredients.push({
        key: "mutation",
        label: "Wording mutation",
        delta: contribution,
        accent: AUGMENTATION_ACCENTS.mutation.raw,
      });
    }
    if (pairOn) {
      // PAIR eventually breaches (1 - never_breach_rate) of the cells it ran
      // on; credit the extra beyond baseline. Different denominator than the
      // single-shot baseline, so this is an upper bound — same as the rest.
      const eventual =
        stubRow && stubRow.never_breach_rate !== null
          ? 1 - stubRow.never_breach_rate
          : null;
      const contribution = eventual !== null ? Math.max(0, eventual - baseline) : 0;
      augmented += contribution;
      ingredients.push({
        key: "pair",
        label: "PAIR refinement",
        delta: contribution,
        accent: AUGMENTATION_ACCENTS.stubbornness.raw,
      });
    }
    augmented = Math.min(1, augmented);
    return { baseline, augmented, ingredients };
  }, [
    selectedConfigId,
    personaOn,
    escalationOn,
    mutationOn,
    pairOn,
    persona,
    escalation,
    mutation,
    stubbornness,
  ]);

  const hasAnyData = configs.length > 0;

  if (!hasAnyData) {
    return (
      <section className="rogue-card border border-border rounded-xl p-6 bg-card/40 backdrop-blur-sm">
        <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green mb-2">
          stress-test lab
        </p>
        <p className="text-base text-muted-foreground">
          {`// the interactive lab unlocks once at least one stress-test
          A/B has data. Run scripts/reproduce_once.py to seed.`}
        </p>
      </section>
    );
  }

  return (
    <section className="space-y-6">
      <div className="space-y-2 animate-rogue-fade-up">
        <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
          stress-test lab · interactive
        </p>
        <h2 className="text-3xl md:text-4xl font-bold tracking-tight max-w-3xl">
          Pick a config. Toggle attacks.{" "}
          <span className="text-rogue-red">Watch it bend.</span>
        </h2>
        <p className="text-base text-muted-foreground max-w-2xl leading-relaxed">
          Each toggle adds the observed Δ for the selected config. Bars use
          real numbers from your sweep. The combined estimate is an
          upper bound — stress tests don&apos;t perfectly stack — but it&apos;s
          directionally honest.
        </p>
      </div>

      <div className="rogue-card border border-border rounded-xl p-6 md:p-8 bg-card/40 backdrop-blur-sm space-y-6">
        {/* Config picker */}
        <div className="space-y-2">
          <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground">
            target deployment
          </p>
          <div className="flex flex-wrap gap-2">
            {configs.map((c) => {
              const active = c.config_id === selectedConfigId;
              return (
                <button
                  key={c.config_id}
                  type="button"
                  onClick={() => setSelectedConfigId(c.config_id)}
                  className={`px-3 py-1.5 rounded-md font-mono text-xs border transition-all ${
                    active
                      ? "bg-rogue-green/10 border-rogue-green/60 text-rogue-green shadow-[0_0_16px_var(--rogue-green-dim)]"
                      : "border-border text-muted-foreground hover:border-rogue-green/40 hover:text-foreground"
                  }`}
                >
                  <span className="inline-flex items-center gap-1.5">
                    <ProviderLogo model={c.target_model} className="text-xs opacity-80" />
                    {c.config_name.replace(/^Acme\s*·\s*/, "")}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Toggles */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <ToggleTile
            label="Persona wrap"
            sub="PAP persuasion"
            on={personaOn}
            onChange={setPersonaOn}
            accent={AUGMENTATION_ACCENTS.persona}
            title="Persona wrap: re-frame the attack as a persuasive persona (e.g. 'as a safety researcher…') and retry — tests whether the model reacts to tone instead of intent."
          />
          <ToggleTile
            label="Multi-turn"
            sub="Crescendo escalation"
            on={escalationOn}
            onChange={setEscalationOn}
            accent={AUGMENTATION_ACCENTS.escalation}
            title="Multi-turn escalation: instead of asking once, warm up over 3 turns and slip the payload in at the end — each turn looks innocent on its own."
          />
          <ToggleTile
            label="Mutation"
            sub="AutoDAN paraphrase"
            on={mutationOn}
            onChange={setMutationOn}
            accent={AUGMENTATION_ACCENTS.mutation}
            title="Mutation: reword a blocked attack into an identical-meaning paraphrase and retry — tests whether the model's filter is keyword-matching, not understanding."
          />
          <ToggleTile
            label="PAIR refine"
            sub="iterative attacker"
            on={pairOn}
            onChange={setPairOn}
            accent={AUGMENTATION_ACCENTS.stubbornness}
            title="PAIR: a second LLM plays attacker, reading each refusal and refining the prompt over several iterations until it breaks through or gives up."
          />
        </div>

        {/* Animated bar */}
        <div className="space-y-3">
          <div className="flex items-baseline justify-between text-xs font-mono">
            <span className="text-muted-foreground uppercase tracking-[0.2em] text-[10px]">
              estimated breach rate
            </span>
            <span className="text-muted-foreground">
              baseline{" "}
              <span className="text-foreground tabular-nums">
                {Math.round(computed.baseline * 100)}%
              </span>
              {computed.augmented > computed.baseline + 0.001 && (
                <>
                  {" "}
                  →{" "}
                  <span className="tabular-nums text-rogue-red">
                    {Math.round(computed.augmented * 100)}%
                  </span>
                </>
              )}
            </span>
          </div>
          <BreachBar
            baseline={computed.baseline}
            augmented={computed.augmented}
            ingredients={computed.ingredients}
          />
          {/* Plain-English translation of the augmented rate */}
          <p className="text-xs text-foreground/80 leading-relaxed">
            <span className="font-mono uppercase tracking-wider text-[9px] text-muted-foreground/70 mr-2">
              in plain English →
            </span>
            {plainifyRate(computed.augmented)}
            {computed.augmented > computed.baseline + 0.005 &&
              ` (up from ${plainifyRate(computed.baseline)})`}
          </p>
          {computed.ingredients.length > 0 && (
            <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] font-mono">
              {computed.ingredients.map((i) => (
                <li
                  key={i.key}
                  className="flex items-center gap-1.5 text-muted-foreground"
                >
                  <span
                    className="inline-block w-2 h-2 rounded-sm"
                    style={{ background: i.accent }}
                  />
                  {i.label}{" "}
                  <span className="text-foreground tabular-nums">
                    +{Math.round(i.delta * 100)}pp
                  </span>
                </li>
              ))}
            </ul>
          )}
          {computed.ingredients.length === 0 && (
            <p className="text-[10px] font-mono text-muted-foreground/80">
              {"// no stress tests selected — toggle one above to start stacking"}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

type Ingredient = {
  key: string;
  label: string;
  delta: number;
  accent: string;
};

function ToggleTile({
  label,
  sub,
  on,
  onChange,
  accent,
  title,
}: {
  label: string;
  sub: string;
  on: boolean;
  onChange: (v: boolean) => void;
  accent: { raw: string; glow: string };
  title?: string;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={() => onChange(!on)}
      className={`text-left rounded-lg p-4 border transition-all flex items-start justify-between gap-3 ${
        on
          ? "bg-card/60 border-transparent rogue-glow-soft"
          : "bg-card/30 border-border hover:border-foreground/40"
      }`}
      style={
        on
          ? ({
              borderColor: accent.raw,
              "--rogue-glow": accent.glow,
            } as React.CSSProperties)
          : undefined
      }
    >
      <div>
        <p
          className="font-mono text-xs uppercase tracking-[0.18em]"
          style={{ color: on ? accent.raw : undefined }}
        >
          {label}
        </p>
        <p className="text-[11px] text-muted-foreground mt-1">{sub}</p>
      </div>
      <span
        className="shrink-0 w-9 h-5 rounded-full border relative transition-colors"
        style={{
          background: on ? accent.raw : "transparent",
          borderColor: on ? accent.raw : "var(--border)",
        }}
        aria-hidden
      >
        <span
          className="absolute top-0.5 w-4 h-4 rounded-full bg-background transition-all"
          style={{ left: on ? "calc(100% - 18px)" : "2px" }}
        />
      </span>
    </button>
  );
}

function BreachBar({
  baseline,
  augmented,
  ingredients,
}: {
  baseline: number;
  augmented: number;
  ingredients: Ingredient[];
}) {
  const baselinePct = Math.round(baseline * 100);
  const augmentedPct = Math.round(augmented * 100);

  // Build stacked segments: baseline + each ingredient.
  const segments: { color: string; pct: number; label: string }[] = [];
  if (baselinePct > 0) {
    segments.push({
      color: "rgba(255,255,255,0.35)",
      pct: baselinePct,
      label: "baseline",
    });
  }
  let acc = baselinePct;
  for (const i of ingredients) {
    const w = Math.min(100 - acc, Math.round(i.delta * 100));
    if (w > 0) {
      segments.push({ color: i.accent, pct: w, label: i.label });
      acc += w;
    }
  }

  return (
    <div className="space-y-1">
      <div className="relative w-full h-8 rounded-md overflow-hidden bg-card/60 border border-border">
        <div className="flex h-full">
          {segments.map((s, idx) => (
            <div
              key={`${s.label}-${idx}`}
              className="rogue-bar-fill h-full"
              style={
                {
                  "--rogue-from": "0%",
                  "--rogue-to": `${s.pct}%`,
                  width: `${s.pct}%`,
                  background: s.color,
                  boxShadow: `inset 0 0 12px ${s.color}66`,
                } as React.CSSProperties
              }
              title={`${s.label}: ${s.pct}%`}
            />
          ))}
        </div>
        {/* Pct label overlaid */}
        <span
          className={`absolute inset-y-0 right-2 flex items-center font-mono text-xs tabular-nums ${
            augmentedPct >= 70 ? "text-rogue-red" : "text-foreground"
          }`}
        >
          {augmentedPct}%
        </span>
      </div>
    </div>
  );
}
