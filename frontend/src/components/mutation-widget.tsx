import type { MutationStatsResponse } from "@/lib/api";
import { SparkBars } from "@/components/spark";
import { ExplainerHeader } from "@/components/explainer";
import { AUGMENTATION_COPY } from "@/components/augmentation-meta";

/**
 * §10.7 AutoDAN-reframed mutation tile — sidebar widget on /feed.
 *
 * "Pattern-matching score" per config = fraction of (parent → mutated child)
 * pairs where the config DEFENDED the original wording but FAILED on the
 * mutated variant. High score ⇒ the config was pattern-matching the
 * specific surface form rather than understanding the underlying technique.
 *
 * Three states:
 *   1. No mutation rows yet — instructional seed command.
 *   2. Mutations exist but no reproduce sweep covers them — header counts
 *      only.
 *   3. Pairs (parent + child × shared config) exist — per-config score
 *      table.
 */
export function MutationWidget({
  mutation,
}: {
  mutation: MutationStatsResponse | null;
}) {
  const nMutations = mutation?.n_mutation_primitives ?? 0;
  const hasConfigRollup = (mutation?.n_configs_with_pairs ?? 0) > 0;

  return (
    <div className="rogue-card rogue-accent-mutation border border-border rounded-lg p-4 bg-card/40 backdrop-blur-sm space-y-3">
      <ExplainerHeader
        accentTextClass="rogue-accent-mutation-text"
        eyebrow={AUGMENTATION_COPY.mutation.eyebrow}
        shortSubhead={AUGMENTATION_COPY.mutation.shortSubhead}
        whatItIs={AUGMENTATION_COPY.mutation.whatItIs}
        whyItMatters={AUGMENTATION_COPY.mutation.whyItMatters}
      />

      {nMutations === 0 && (
        <p className="text-xs font-mono text-muted-foreground leading-relaxed">
          {
            "// no mutations yet · seed: uv run python scripts/synthesize_mutations.py --limit 15"
          }
        </p>
      )}

      {nMutations > 0 && !hasConfigRollup && (
        <>
          <div className="text-[10px] font-mono text-muted-foreground space-y-0.5">
            <p>
              <span className="text-foreground tabular-nums">
                {nMutations}
              </span>{" "}
              mutation primitives
            </p>
            <p>
              <span className="text-foreground tabular-nums">
                {mutation?.n_parents_mutated ?? 0}
              </span>{" "}
              parents mutated
            </p>
          </div>
          <p className="text-xs font-mono text-muted-foreground leading-relaxed">
            {"// run: uv run python scripts/reproduce_once.py — to fire the mutated variants"}
          </p>
        </>
      )}

      {hasConfigRollup && mutation && (
        <>
          <div>
            <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground mb-2">
              per config · pattern-match %
            </p>
            <SparkBars
              color="#22d3ee"
              max={100}
              data={mutation.per_config.map((row) => ({
                label: shortConfigName(row.config_name),
                value: Math.round((row.pattern_matching_score ?? 0) * 100),
              }))}
            />
          </div>
          <details className="group">
            <summary className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground cursor-pointer hover:text-rogue-green transition-colors list-none flex items-center gap-1">
              <span className="inline-block transition-transform group-open:rotate-90">▸</span>
              per-config breakdown
            </summary>
            <ul className="space-y-1 mt-2">
              {mutation.per_config.map((row) => (
                <MutationConfigRow key={row.config_id} row={row} />
              ))}
            </ul>
          </details>
          <div className="pt-2 border-t border-border space-y-0.5">
            <p className="text-[10px] text-muted-foreground font-mono">
              {mutation.n_mutation_primitives} mutations ·{" "}
              {mutation.n_parents_mutated} parents · evade&lt;
              {mutation.evade_threshold}
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

function MutationConfigRow({
  row,
}: {
  row: MutationStatsResponse["per_config"][number];
}) {
  const score = row.pattern_matching_score;
  // Higher pattern-matching = worse defense ⇒ red. None = no parent-defended
  // cells for this config, so the score is undefined.
  const tint =
    score === null
      ? "text-muted-foreground"
      : score >= 0.5
        ? "text-rogue-red"
        : score >= 0.25
          ? "text-orange-300"
          : "text-rogue-green";
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
          {score === null ? "—" : `${(score * 100).toFixed(0)}%`}
        </span>
      </div>
      <div
        className="text-[10px] text-muted-foreground tabular-nums"
        title="parent-defended cells where mutation slipped through"
      >
        {row.n_parent_defended_child_breached}/{row.n_parent_defended} leaked
        · {row.n_pairs} total pairs
      </div>
    </li>
  );
}
