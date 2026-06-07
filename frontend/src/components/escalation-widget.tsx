import type { EscalationStatsResponse } from "@/lib/api";
import { SparkBars } from "@/components/spark";
import { ExplainerHeader } from "@/components/explainer";
import { AUGMENTATION_COPY } from "@/components/augmentation-meta";
import { ProviderLogo } from "@/components/ui/provider-logo";

/**
 * §10.7 Multi-turn escalation A/B tile — sidebar widget on /feed.
 *
 * Per-config "escalation-vulnerability score" = breach-rate delta between
 * the synthesized 3-turn Crescendo-style escalation and the harvested
 * single-turn parent. Positive delta = the escalation worked (the deck
 * claim — "watch this single-turn primitive fail at turn 1, escalated
 * 3-turn version breach at turn 3").
 *
 * Renders three states:
 *   1. No synthesized primitives yet — instructional stub with seed cmd.
 *   2. Synthesized rows exist but no reproduce sweep has run them yet —
 *      header counts only, no per-config rollup.
 *   3. Pairs (parent breach data + child breach data) exist — per-config
 *      Δ table.
 */
export function EscalationWidget({
  escalation,
}: {
  escalation: EscalationStatsResponse | null;
}) {
  const nSynthesized = escalation?.n_synthesized_primitives ?? 0;
  const hasConfigRollup = (escalation?.n_configs_with_pairs ?? 0) > 0;

  return (
    <div className="rogue-card rogue-accent-escalation border border-border rounded-lg p-4 bg-card/40 backdrop-blur-sm space-y-3">
      <ExplainerHeader
        accentTextClass="rogue-accent-escalation-text"
        eyebrow={AUGMENTATION_COPY.escalation.eyebrow}
        shortSubhead={AUGMENTATION_COPY.escalation.shortSubhead}
        whatItIs={AUGMENTATION_COPY.escalation.whatItIs}
        whyItMatters={AUGMENTATION_COPY.escalation.whyItMatters}
      />

      {nSynthesized === 0 && (
        <p className="text-xs font-mono text-muted-foreground leading-relaxed">
          {
            "// no escalations yet · seed: uv run python scripts/reproduce/synthesize_escalations.py --limit 45"
          }
        </p>
      )}

      {nSynthesized > 0 && !hasConfigRollup && (
        <>
          <div className="text-[10px] font-mono text-muted-foreground space-y-0.5">
            <p>
              <span className="text-foreground tabular-nums">
                {nSynthesized}
              </span>{" "}
              synthesized primitives
            </p>
            <p>
              <span className="text-foreground tabular-nums">
                {escalation?.n_parents_escalated ?? 0}
              </span>{" "}
              parents escalated
            </p>
          </div>
          <p className="text-xs font-mono text-muted-foreground leading-relaxed">
            {"// run: uv run python scripts/reproduce/reproduce_once.py — to fire the synthesized variants against the panel"}
          </p>
        </>
      )}

      {hasConfigRollup && escalation && (
        <>
          <div>
            <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground mb-2">
              per config · escalation Δ
            </p>
            <SparkBars
              color="#fbbf24"
              data={escalation.per_config.map((row) => ({
                label: shortConfigName(row.config_name),
                value: Math.round(Math.max(0, row.delta) * 100),
              }))}
            />
          </div>
          <details className="group">
            <summary className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground cursor-pointer hover:text-rogue-green transition-colors list-none flex items-center gap-1">
              <span className="inline-block transition-transform group-open:rotate-90">▸</span>
              parent → escalated breakdown
            </summary>
            <ul className="space-y-1 mt-2">
              {escalation.per_config.map((row) => (
                <EscalationConfigRow key={row.config_id} row={row} />
              ))}
            </ul>
          </details>
          <div className="pt-2 border-t border-border space-y-0.5">
            <p className="text-[10px] text-muted-foreground font-mono">
              {escalation.n_synthesized_primitives} synthesized ·{" "}
              {escalation.n_parents_escalated} parents · min_trials=
              {escalation.min_trials}
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

function EscalationConfigRow({
  row,
}: {
  row: EscalationStatsResponse["per_config"][number];
}) {
  const tint =
    row.delta > 0
      ? "text-rogue-red"
      : row.delta < 0
        ? "text-rogue-green"
        : "text-muted-foreground";
  const baselinePct = (row.baseline_breach_rate * 100).toFixed(0);
  const escalatedPct = (row.escalated_breach_rate * 100).toFixed(0);
  return (
    <li className="flex flex-col gap-0.5 text-xs font-mono">
      <div className="flex items-center justify-between gap-2">
        <span
          className="truncate text-foreground flex-1 min-w-0"
          title={`${row.config_name} · ${row.target_model}`}
        >
          <span className="inline-flex items-center gap-1.5">
            <ProviderLogo model={row.target_model} className="text-xs opacity-70" />
            {row.config_name}
          </span>
        </span>
        <span className={`tabular-nums whitespace-nowrap ${tint}`}>
          {row.delta > 0 ? "+" : ""}
          {(row.delta * 100).toFixed(0)}pp
        </span>
      </div>
      <div
        className="text-[10px] text-muted-foreground tabular-nums"
        title={`single-turn parent vs 3-turn escalation`}
      >
        {baselinePct}% → {escalatedPct}% · {row.child_n_trials}t child
      </div>
    </li>
  );
}
