"use client";

/**
 * Pure-SVG mini bar chart — used in stubbornness widget for the
 * refinement-type histogram. No recharts dependency (faster, simpler).
 *
 * Renders horizontal bars labelled left, value-aligned right. Each bar grows
 * with a CSS transition so the chart "fills in" on first paint.
 */
export function SparkBars({
  data,
  color = "var(--rogue-green)",
  max,
}: {
  data: { label: string; value: number }[];
  color?: string;
  max?: number;
}) {
  if (!data || data.length === 0) return null;
  const peak = max ?? Math.max(...data.map((d) => d.value), 1);
  return (
    <ul className="space-y-1">
      {data.map((d) => {
        const pct = (d.value / peak) * 100;
        return (
          <li key={d.label} className="text-[11px] font-mono flex items-center gap-2">
            <span className="text-foreground truncate flex-1 min-w-0" title={d.label}>
              {d.label}
            </span>
            <span className="flex-1 h-1.5 bg-card/60 rounded-sm overflow-hidden relative">
              <span
                className="absolute inset-y-0 left-0 rounded-sm transition-all duration-700 ease-out"
                style={{
                  width: `${pct}%`,
                  background: color,
                  boxShadow: `0 0 6px ${color}88`,
                }}
              />
            </span>
            <span className="tabular-nums text-muted-foreground w-6 text-right">
              {d.value}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
