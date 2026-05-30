import Link from "next/link";
import { api } from "@/lib/api";
import { MatrixHeatmap } from "@/components/matrix-heatmap";
import { Term } from "@/components/glossary";
import { plainifyRate } from "@/lib/plain-numbers";

/**
 * /matrix — Breach Matrix heatmap.
 *
 * Server-rendered shell: fetches the matrix + stubbornness data in parallel,
 * computes top-level headline stats (worst cell, critical-cell count, worst
 * attacker across the whole matrix), then hands the grid off to the client
 * `MatrixHeatmap` for cell-click → side-drawer interaction.
 *
 * Column headers carry the §10.7 PAIR avg-iters-to-breach so the matrix
 * and the augmentation A/B story stay tied together visually.
 */
export default async function MatrixPage({
  searchParams,
}: {
  searchParams: Promise<{ date?: string }>;
}) {
  // ?date=YYYY-MM-DD pins a specific run day (e.g. a fresh harvest's reproduce
  // that isn't the default "most-data" day). Omitted → the API's default.
  const { date } = await searchParams;

  // The SCOPE × ATTACKER 2×2 needs all four quadrant datasets. Only the
  // top-left (this-run × baseline) is required; the other three degrade to null
  // and the heatmap falls back to baseline if a quadrant is unavailable.
  let matrix: Awaited<ReturnType<typeof api.breachMatrix>> | null = null;
  let thisRunAugmented: Awaited<ReturnType<typeof api.breachMatrix>> | null = null;
  let allTimeBaseline: Awaited<ReturnType<typeof api.breachMatrix>> | null = null;
  let augmented: Awaited<ReturnType<typeof api.breachMatrix>> | null = null;
  let stubbornness: Awaited<ReturnType<typeof api.stubbornnessStats>> | null = null;
  let error: string | null = null;
  try {
    [matrix, thisRunAugmented, allTimeBaseline, augmented, stubbornness] =
      await Promise.all([
        api.breachMatrix(date), // this-run × baseline
        api.breachMatrix(date, "thisrun_augmented").catch(() => null), // this-run × augmented
        api.breachMatrix(undefined, "alltime_baseline").catch(() => null), // all-time × baseline
        api.breachMatrix(undefined, "augmented").catch(() => null), // all-time × augmented
        api.stubbornnessStats().catch(() => null),
      ]);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  if (error || !matrix) {
    return (
      <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
        <div className="max-w-7xl mx-auto px-6 py-10 space-y-4">
          <h1 className="text-4xl font-bold tracking-tight">Breach Matrix</h1>
          <div className="border border-rogue-red/40 rounded-lg p-6 font-mono text-sm text-rogue-red bg-rogue-red/5">
            {`// matrix unavailable: ${error ?? "no data"}`}
          </div>
        </div>
      </main>
    );
  }

  // Headline-driving stats.
  const allRates = matrix.cells.map((c) => c.any_breach_rate);
  const maxRate = allRates.length ? Math.max(...allRates) : 0;
  const criticalCellCount = matrix.cells.filter((c) => c.any_breach_rate >= 0.7).length;

  // Worst attacker today: highest single-cell any-breach rate, tie-broken by
  // full-breach (matches the grid cell's worst-offending pick, so the headline
  // and the cell drawer agree on which primitive is "worst").
  const worstCell = matrix.cells.reduce<typeof matrix.cells[number] | null>(
    (acc, c) => {
      if (acc === null) return c;
      if (c.any_breach_rate > acc.any_breach_rate) return c;
      if (
        c.any_breach_rate === acc.any_breach_rate &&
        c.full_breach_rate > acc.full_breach_rate
      )
        return c;
      return acc;
    },
    null,
  );

  // Featured attack: Pliny's (elder_plinius) X jailbreak. It ties several other
  // attacks at 100%/100%, so the matrix-wide "worst" pick is arbitrary among the
  // ties — pin Pliny as the headline when it's present in the current view
  // (the label stays honest since it genuinely ties for worst). Falls back to
  // the computed worst cell on any day Pliny isn't in the matrix.
  const FEATURED_PRIMITIVE_ID = "01KSWGSAY2ZJ7E7WEPB1QX7N55";
  const featuredCell = matrix.cells
    .filter((c) => c.primitive_id === FEATURED_PRIMITIVE_ID)
    .reduce<typeof matrix.cells[number] | null>((acc, c) => {
      if (acc === null) return c;
      if (c.any_breach_rate > acc.any_breach_rate) return c;
      if (
        c.any_breach_rate === acc.any_breach_rate &&
        c.full_breach_rate > acc.full_breach_rate
      )
        return c;
      return acc;
    }, null);
  const headlineCell = featuredCell ?? worstCell;

  // Most-vulnerable config: column with the highest worst-rate across families.
  const configWorstScore: Record<string, number> = {};
  for (const c of matrix.cells) {
    const prev = configWorstScore[c.deployment_config_id] ?? 0;
    if (c.any_breach_rate > prev)
      configWorstScore[c.deployment_config_id] = c.any_breach_rate;
  }
  const mostVulnConfig = Object.entries(configWorstScore).sort(
    ([, a], [, b]) => b - a,
  )[0];
  const mostVulnConfigName = mostVulnConfig
    ? matrix.configs.find((c) => c.config_id === mostVulnConfig[0])?.config_name ??
      mostVulnConfig[0]
    : null;

  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-7xl mx-auto px-6 py-10 space-y-8">
        {/* Header */}
        <header className="flex items-start justify-between gap-6 flex-wrap animate-rogue-fade-up">
          <div className="space-y-2">
            <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
              /matrix · {matrix.target_date}
            </p>
            <h1 className="text-4xl font-bold tracking-tight">Breach Matrix</h1>
            <p className="text-sm text-muted-foreground max-w-xl leading-relaxed">
              Max any-breach rate per attack{" "}
              <Term name="family">family</Term> ×{" "}
              <Term name="deployment config">deployment config</Term>.{" "}
              <span className="text-foreground">{matrix.n_primitives} attacks</span> tested
              against <span className="text-foreground">{matrix.configs.length} configs</span>{" "}
              ({matrix.n_cells} cells total). Click any red cell to see the prompt that
              breached it.
            </p>
          </div>

          {/* Stat capsules */}
          <div className="flex items-center gap-3 flex-wrap">
            <StatCapsule
              label="Worst cell"
              value={`${Math.round(maxRate * 100)}%`}
              plain={plainifyRate(maxRate)}
              tint={maxRate >= 0.7 ? "red" : maxRate >= 0.3 ? "orange" : "green"}
            />
            <StatCapsule
              label="Critical cells"
              value={String(criticalCellCount)}
              plain={
                criticalCellCount === 0
                  ? "nothing in red zone"
                  : `${criticalCellCount} cells breach 70%+ of the time`
              }
              tint={criticalCellCount > 0 ? "red" : "green"}
            />
          </div>
        </header>

        {/* Worst-attacker callout — links to the full (family × config) breakdown */}
        {headlineCell && headlineCell.any_breach_rate > 0 && (
          <Link
            href={`/matrix/cell?family=${encodeURIComponent(headlineCell.family)}&config=${encodeURIComponent(headlineCell.deployment_config_id)}&date=${matrix.target_date}`}
            className="group block rogue-card rogue-card-critical border border-rogue-red/40 rounded-lg p-5 bg-rogue-red/5 animate-rogue-fade-up transition-colors hover:bg-rogue-red/10 hover:border-rogue-red/60"
            style={{ animationDelay: "0.05s" }}
          >
            <div className="flex items-baseline justify-between gap-4 flex-wrap">
              <div className="space-y-1 min-w-0 flex-1">
                <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-rogue-red flex items-center gap-2">
                  worst attacker today
                  <span className="text-muted-foreground normal-case tracking-normal opacity-0 group-hover:opacity-100 transition-opacity">
                    — see full breakdown →
                  </span>
                </p>
                <p className="text-lg font-bold leading-tight truncate" title={headlineCell.title}>
                  {headlineCell.title}
                </p>
                <p className="text-xs font-mono text-muted-foreground">
                  {headlineCell.family} · {headlineCell.vector} · breached{" "}
                  <span className="text-foreground">{headlineCell.config_name}</span> at{" "}
                  <span className="text-rogue-red tabular-nums">
                    {Math.round(headlineCell.any_breach_rate * 100)}%
                  </span>{" "}
                  (n={headlineCell.n_trials})
                </p>
              </div>
              <div className="text-right">
                <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground">
                  most-vulnerable config
                </p>
                <p className="text-sm font-mono mt-0.5">
                  {mostVulnConfigName ?? "—"}
                </p>
              </div>
            </div>
          </Link>
        )}

        {/* Interactive heatmap (client component) */}
        <MatrixHeatmap
          matrix={matrix}
          thisRunAugmented={thisRunAugmented}
          allTimeBaseline={allTimeBaseline}
          augmented={augmented}
          stubbornness={stubbornness}
        />

        <Legend />

        <section
          className="text-xs text-muted-foreground font-mono space-y-1 animate-rogue-fade-up"
          style={{ animationDelay: "0.3s" }}
        >
          <p>
            {
              "// cells aggregate MAX(any_breach_rate) across all "
            }
            <Term name="primitive">primitives</Term>
            {" in ("}
            <Term name="family">family</Term>
            {" × config)"}
          </p>
          <p>
            {"// each "}
            <Term name="primitive">primitive</Term>
            {" ran N=5 trials per cell; rates carry 95% bootstrap "}
            <Term name="CI">CIs</Term>
            {" in the cell drawer"}
          </p>
        </section>
      </div>
    </main>
  );
}

// --------------------------------------------------------------------------

function StatCapsule({
  label,
  value,
  plain,
  tint,
}: {
  label: string;
  value: string;
  plain?: string;
  tint: "green" | "orange" | "red";
}) {
  const tintClass =
    tint === "red"
      ? "text-rogue-red border-rogue-red/40 bg-rogue-red/10"
      : tint === "orange"
        ? "text-orange-300 border-orange-500/40 bg-orange-500/10"
        : "text-rogue-green border-rogue-green/40 bg-rogue-green/10";
  return (
    <div className={`px-3 py-2 border rounded-md ${tintClass} font-mono max-w-[220px]`}>
      <p className="text-[9px] uppercase tracking-[0.2em] opacity-70">{label}</p>
      <p className="text-lg font-bold tabular-nums leading-tight">{value}</p>
      {plain && (
        <p className="text-[9px] opacity-80 leading-snug mt-1 normal-case font-sans">
          {plain}
        </p>
      )}
    </div>
  );
}

function Legend() {
  return (
    <section
      className="flex items-center gap-4 text-xs font-mono flex-wrap animate-rogue-fade-up"
      style={{ animationDelay: "0.2s" }}
    >
      <span className="text-muted-foreground uppercase tracking-[0.2em] text-[10px]">
        Heat scale:
      </span>
      <LegendChip color="bg-card/30 border-border" label="< 10%" />
      <LegendChip color="bg-blue-500/20 border-blue-500/40" label="10–30%" />
      <LegendChip color="bg-yellow-500/30 border-yellow-500/50" label="30–50%" />
      <LegendChip color="bg-orange-500/40 border-orange-500/60" label="50–70%" />
      <LegendChip
        color="bg-rogue-red/30 border-rogue-red/60 rogue-cell-critical"
        label="70–100% · breached"
      />
    </section>
  );
}

function LegendChip({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-2">
      <span className={`inline-block w-4 h-4 ${color} border rounded`} />
      <span className="text-muted-foreground">{label}</span>
    </span>
  );
}
