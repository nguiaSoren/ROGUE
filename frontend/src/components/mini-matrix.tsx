import Link from "next/link";
import type { BreachMatrixResponse, BreachCell } from "@/lib/api";

/**
 * Tiny preview of the breach matrix for the home hero.
 *
 * Renders a compact grid (no labels, just colored cells). Clicking it sends
 * you to /matrix for the real heatmap. Empty cells render as dim outline so
 * the shape of the grid is preserved even when sparse.
 */
export function MiniMatrix({ matrix }: { matrix: BreachMatrixResponse | null }) {
  if (!matrix || matrix.cells.length === 0) {
    return (
      <Link
        href="/matrix"
        className="rogue-card border border-border rounded-lg p-5 bg-card/40 backdrop-blur-sm block group h-full"
      >
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
          /matrix
        </p>
        <p className="text-sm text-muted-foreground mt-2 leading-relaxed">
          {"// no breach data yet — run scripts/reproduce/reproduce_once.py to seed"}
        </p>
      </Link>
    );
  }

  // Aggregate to (family × config) cells, MAX of any_breach_rate.
  const grid: Record<string, Record<string, number>> = {};
  for (const family of matrix.families) {
    grid[family] = {};
    for (const c of matrix.configs) grid[family][c.config_id] = 0;
  }
  for (const cell of matrix.cells as BreachCell[]) {
    const cur = grid[cell.family]?.[cell.deployment_config_id] ?? 0;
    if (cell.any_breach_rate > cur) {
      grid[cell.family][cell.deployment_config_id] = cell.any_breach_rate;
    }
  }

  // Show the top-N families with the most heat so the preview is visually
  // dense. Same logic as /matrix but capped.
  const familyHeat = matrix.families
    .map((f) => ({
      f,
      score: Math.max(0, ...matrix.configs.map((c) => grid[f]?.[c.config_id] ?? 0)),
    }))
    .sort((a, b) => b.score - a.score);
  const topFamilies = familyHeat.slice(0, 8).map((x) => x.f);

  const maxRate = Math.max(...matrix.cells.map((c) => c.any_breach_rate));
  const critCount = matrix.cells.filter((c) => c.any_breach_rate >= 0.7).length;

  return (
    <Link
      href="/matrix"
      className="rogue-card border border-border rounded-lg p-4 bg-card/40 backdrop-blur-sm block group h-full"
    >
      <div className="flex items-baseline justify-between mb-3">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
          breach matrix · {matrix.target_date}
        </p>
        <p className="font-mono text-[10px] text-muted-foreground group-hover:text-rogue-green transition-colors">
          open →
        </p>
      </div>

      <div
        className="grid gap-[2px]"
        style={{
          gridTemplateColumns: `repeat(${matrix.configs.length}, minmax(0, 1fr))`,
        }}
      >
        {topFamilies.flatMap((family, rowIdx) =>
          matrix.configs.map((c, colIdx) => {
            const rate = grid[family]?.[c.config_id] ?? 0;
            const cls = miniCellClass(rate);
            const delay = Math.min((rowIdx + colIdx) * 0.025, 0.6);
            return (
              <div
                key={`${family}-${c.config_id}`}
                className={`aspect-square ${cls} rounded-[2px] animate-rogue-cell-pop`}
                style={{ animationDelay: `${delay}s` }}
                title={`${family} × ${c.config_id}: ${Math.round(rate * 100)}%`}
              />
            );
          }),
        )}
      </div>

      <div className="mt-3 flex items-center justify-between text-[10px] font-mono">
        <span className="text-muted-foreground">
          {topFamilies.length} families × {matrix.configs.length} configs
        </span>
        <span className="text-rogue-red tabular-nums font-bold">
          {Math.round(maxRate * 100)}% peak · {critCount} crit
        </span>
      </div>
    </Link>
  );
}

function miniCellClass(rate: number): string {
  if (rate >= 0.7) return "bg-rogue-red/70 rogue-cell-critical";
  if (rate >= 0.5) return "bg-orange-500/70";
  if (rate >= 0.3) return "bg-yellow-500/60";
  if (rate >= 0.1) return "bg-blue-500/50";
  if (rate > 0) return "bg-card/80";
  return "bg-card/30 border border-border/30";
}
