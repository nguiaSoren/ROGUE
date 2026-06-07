import type { StubbornnessStatsResponse } from "@/lib/api";
import { SparkBars } from "@/components/spark";
import { ExplainerHeader } from "@/components/explainer";
import { AUGMENTATION_COPY } from "@/components/augmentation-meta";

/**
 * §10.7 full PAIR build, per-config "stubbornness" tile on /feed.
 *
 * Stubbornness = average iters-to-breach over PAIR cells that breached.
 * Lower = the config gave up quickly under iterative refinement;
 * higher = the config held out across multiple iterations.
 *
 * Also shows the refinement-type distribution, which attacker strategies
 * the LLM picked most often across all PAIR steps. Useful for the deck
 * claim "X% of breaches came from roleplaying-style refinements."
 *
 * Three states:
 *   1. No PAIR rows yet, instructional stub with seed command.
 *   2. PAIR rows but none breached, header counts only.
 *   3. Breaches recorded, per-config avg-iters + refinement-type chart.
 */
export function StubbornnessWidget({
  stubbornness,
}: {
  stubbornness: StubbornnessStatsResponse | null;
}) {
  const nPair = stubbornness?.n_pair_cells ?? 0;
  const nBreached = stubbornness?.n_breached ?? 0;
  const hasBreaches = nBreached > 0;

  return (
    <div className="rogue-card rogue-accent-stubbornness border border-border rounded-lg p-4 bg-card/40 backdrop-blur-sm space-y-3">
      <ExplainerHeader
        accentTextClass="rogue-accent-stubbornness-text"
        eyebrow={AUGMENTATION_COPY.stubbornness.eyebrow}
        shortSubhead={AUGMENTATION_COPY.stubbornness.shortSubhead}
        whatItIs={AUGMENTATION_COPY.stubbornness.whatItIs}
        whyItMatters={AUGMENTATION_COPY.stubbornness.whyItMatters}
      />

      {nPair === 0 && (
        <p className="text-xs font-mono text-muted-foreground leading-relaxed">
          {
            "// no PAIR runs yet · seed: uv run python scripts/reproduce/reproduce_once.py --pair-max-iters 3"
          }
        </p>
      )}

      {nPair > 0 && !hasBreaches && (
        <>
          <div className="text-[10px] font-mono text-muted-foreground space-y-0.5">
            <p>
              <span className="text-foreground tabular-nums">{nPair}</span>{" "}
              PAIR cells (none breached)
            </p>
            <p>
              <span className="text-foreground tabular-nums">
                {stubbornness?.n_refinement_steps ?? 0}
              </span>{" "}
              refinement steps fired
            </p>
          </div>
          <p className="text-xs font-mono text-muted-foreground leading-relaxed">
            {"// configs robust against single-iter refinement, try --pair-max-iters 5+"}
          </p>
        </>
      )}

      {hasBreaches && stubbornness && (
        <>
          <div>
            <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground mb-2">
              per config · avg iters
            </p>
            <ul className="space-y-1">
              {stubbornness.per_config.map((row) => (
                <StubbornnessConfigRow key={row.config_id} row={row} />
              ))}
            </ul>
          </div>
          {stubbornness.refinement_type_distribution.length > 0 && (
            <div>
              <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground mb-2">
                refinement strategies fired
              </p>
              <SparkBars
                color="#f87171"
                data={stubbornness.refinement_type_distribution
                  .slice(0, 5)
                  .map((row) => ({
                    label: row.refinement_type,
                    value: row.n_steps,
                  }))}
              />
            </div>
          )}
          <div className="pt-2 border-t border-border space-y-0.5">
            <p className="text-[10px] text-muted-foreground font-mono">
              {nPair} cells · {nBreached} breached ·{" "}
              {stubbornness.n_refinement_steps} steps
            </p>
          </div>
        </>
      )}
    </div>
  );
}

function StubbornnessConfigRow({
  row,
}: {
  row: StubbornnessStatsResponse["per_config"][number];
}) {
  const avgIters = row.avg_iters_to_breach;
  // Higher iters = more robust = green; lower iters = vulnerable = red.
  // null = no breaches yet for this config = neutral.
  const tint =
    avgIters === null
      ? "text-muted-foreground"
      : avgIters >= 2
        ? "text-rogue-green"
        : avgIters >= 1
          ? "text-orange-300"
          : "text-rogue-red";
  return (
    <li className="flex flex-col gap-0.5 text-xs font-mono">
      <div className="flex items-center justify-between gap-2">
        <span
          className="truncate text-foreground flex-1 min-w-0"
          title={`${row.config_name} · ${row.target_model}`}
        >
          {row.config_name}
        </span>
        <span className={`tabular-nums whitespace-nowrap ${tint}`}>
          {avgIters === null
            ? ", "
            : `${avgIters.toFixed(1)} iters`}
        </span>
      </div>
      <div className="text-[10px] text-muted-foreground tabular-nums">
        {row.n_breached}/{row.n_pair_cells} breached · $
        {row.total_attacker_cost_usd.toFixed(3)}
      </div>
    </li>
  );
}
