"use client";

import { Area, AreaChart, ResponsiveContainer, Tooltip } from "recharts";

/**
 * Tiny inline area sparkline — recharts wrapped to ~24px tall with no axes,
 * no grid, no legend. Used inside augmentation widgets to give each one a
 * visual pulse of its own data shape.
 */
export function SparkArea({
  data,
  color = "var(--rogue-green)",
  height = 28,
  fillOpacity = 0.25,
}: {
  data: { x: number | string; y: number }[];
  color?: string;
  height?: number;
  fillOpacity?: number;
}) {
  if (!data || data.length === 0) return <div style={{ height }} />;
  return (
    <div style={{ width: "100%", height }} className="pointer-events-none">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id={`spark-grad-${color}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={fillOpacity} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <Tooltip content={() => null} />
          <Area
            type="monotone"
            dataKey="y"
            stroke={color}
            strokeWidth={1.5}
            fill={`url(#spark-grad-${color})`}
            isAnimationActive={false}
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

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
