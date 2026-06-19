import type { PersonaStatsResponse } from "@/lib/api";
import { SparkBars } from "@/components/spark";
import { ExplainerHeader } from "@/components/explainer";
import { AUGMENTATION_COPY } from "@/components/augmentation-meta";
import { ProviderLogo } from "@/components/ui/provider-logo";

/**
 * §10.7 Persona augmentation A/B tile, sidebar widget on /feed.
 *
 * Shows per-config "persona-susceptibility score" = max breach-rate delta
 * across PAP persuasion techniques tried against that config. Positive
 * delta means the persona wrap raised breach rate vs the unwrapped
 * baseline (the deck claim, "vulnerable to social-engineering layers").
 *
 * Renders three states:
 *   1. No persona data yet (fresh DB or pre-§10.7 sweep), instructional
 *      stub with the command to seed it.
 *   2. Baselines exist but no wrapped runs, same stub, different copy.
 *   3. Wrapped runs exist, per-config table + top-3 (technique × config)
 *      cells by delta.
 */
export function PersonaWidget({
  persona,
}: {
  persona: PersonaStatsResponse | null;
}) {
  const hasBaselines = (persona?.n_configs_with_baseline ?? 0) > 0;
  const hasWrapped = (persona?.n_cells ?? 0) > 0;

  return (
    <div className="rogue-card rogue-accent-persona border border-border rounded-lg p-4 bg-card/40 backdrop-blur-sm space-y-3">
      <ExplainerHeader
        accentTextClass="rogue-accent-persona-text"
        eyebrow={AUGMENTATION_COPY.persona.eyebrow}
        shortSubhead={AUGMENTATION_COPY.persona.shortSubhead}
        whatItIs={AUGMENTATION_COPY.persona.whatItIs}
        whyItMatters={AUGMENTATION_COPY.persona.whyItMatters}
      />

      {!hasBaselines && (
        <p className="text-xs font-mono text-muted-foreground">
          {"// no breach rows yet. Run: uv run python scripts/reproduce/reproduce_once.py"}
        </p>
      )}

      {hasBaselines && !hasWrapped && (
        <p className="text-xs font-mono text-muted-foreground leading-relaxed">
          {
            "// baseline ready · no wrapped runs yet · seed: uv run python scripts/reproduce/reproduce_once.py --persona 'Logical Appeal' --primitive-limit 50"
          }
        </p>
      )}

      {hasWrapped && persona && (
        <>
          <div>
            <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground mb-2">
              per config · max Δ
            </p>
            <SparkBars
              color="#a78bfa"
              data={persona.per_config.map((c) => ({
                label: shortConfigName(c.config_name),
                value: Math.round(Math.max(0, c.max_delta ?? 0) * 100),
              }))}
            />
          </div>
          {persona.cells.length > 0 && (
            <div>
              <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground mb-1.5">
                top 3 (config × technique)
              </p>
              <ul className="space-y-1">
                {persona.cells.slice(0, 3).map((cell, i) => (
                  <TopCellRow key={`${cell.config_id}-${cell.persona_used}-${i}`} cell={cell} />
                ))}
              </ul>
            </div>
          )}
          <div className="pt-2 border-t border-border space-y-0.5">
            <p className="text-[10px] text-muted-foreground font-mono">
              {persona.n_cells} (config × technique) cells · min_trials={persona.min_trials}
            </p>
          </div>
        </>
      )}
    </div>
  );
}

function shortConfigName(name: string): string {
  return name.replace(/^Acme\s*·\s*/, "");
}

function TopCellRow({
  cell,
}: {
  cell: PersonaStatsResponse["cells"][number];
}) {
  const tint = cell.delta > 0 ? "text-rogue-red" : "text-muted-foreground";
  // Strip the `__refused` suffix for display, but mark it visually.
  const displayName = cell.is_refusal_fallback
    ? cell.persona_used.replace(/__refused$/, "")
    : cell.persona_used;
  return (
    <li className="flex flex-col gap-0.5 text-xs font-mono">
      <div className="flex items-center justify-between gap-2">
        <span
          className="truncate text-foreground flex-1 min-w-0"
          title={`${cell.config_name} · ${cell.persona_used}`}
        >
          {displayName}
          {cell.is_refusal_fallback && (
            <span className="text-rogue-red ml-1">⊘</span>
          )}
        </span>
        <span className={`tabular-nums whitespace-nowrap ${tint}`}>
          {cell.delta > 0 ? "+" : ""}
          {(cell.delta * 100).toFixed(0)}pp
        </span>
      </div>
      <div className="text-[10px] text-muted-foreground truncate" title={cell.config_name}>
        on{" "}
        <span className="inline-flex items-center gap-1.5">
          <ProviderLogo model={cell.config_name} className="text-[10px] opacity-70" />
          {cell.config_name}
        </span>{" "}
        · {cell.n_wrapped_trials}t
      </div>
    </li>
  );
}
