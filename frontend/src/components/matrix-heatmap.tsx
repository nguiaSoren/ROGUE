"use client";

import { useMemo, useState } from "react";
import type { BreachCell, BreachMatrixResponse, StubbornnessStatsResponse } from "@/lib/api";
import { MatrixCellDrawer } from "@/components/matrix-drawer";

/**
 * Interactive breach heatmap. Renders the (family × config) grid, with each
 * cell clickable → opens the drawer with the worst primitive for that cell.
 *
 * The aggregation logic (max any_breach_rate per (family × config)) is the
 * same as the server version was — only the rendering is moved client-side
 * so cell clicks can pop the drawer without a navigation round-trip.
 */
export function MatrixHeatmap({
  matrix,
  stubbornness,
}: {
  matrix: BreachMatrixResponse;
  stubbornness: StubbornnessStatsResponse | null;
}) {
  const [openCell, setOpenCell] = useState<BreachCell | null>(null);
  const [familyFilter, setFamilyFilter] = useState<string | null>(null);
  const [severityFilter, setSeverityFilter] = useState<
    "all" | "critical" | "high" | "any-breach"
  >("all");

  // Pre-compute the worst-rate cell per (family × config) so the click
  // handler can yank the canonical primitive for the cell quickly.
  const byKey = useMemo(() => {
    const m = new Map<string, BreachCell>();
    for (const c of matrix.cells) {
      const key = `${c.family}|${c.deployment_config_id}`;
      const prev = m.get(key);
      if (!prev || c.any_breach_rate > prev.any_breach_rate) m.set(key, c);
    }
    return m;
  }, [matrix.cells]);

  // Filter families.
  const visibleFamilies = useMemo(() => {
    if (familyFilter) return [familyFilter];
    if (severityFilter === "all") return matrix.families;
    if (severityFilter === "critical") {
      return matrix.families.filter((f) =>
        matrix.configs.some((c) => {
          const cell = byKey.get(`${f}|${c.config_id}`);
          return cell && cell.any_breach_rate >= 0.7;
        }),
      );
    }
    if (severityFilter === "high") {
      return matrix.families.filter((f) =>
        matrix.configs.some((c) => {
          const cell = byKey.get(`${f}|${c.config_id}`);
          return cell && cell.any_breach_rate >= 0.5;
        }),
      );
    }
    // any-breach
    return matrix.families.filter((f) =>
      matrix.configs.some((c) => {
        const cell = byKey.get(`${f}|${c.config_id}`);
        return cell && cell.any_breach_rate > 0;
      }),
    );
  }, [familyFilter, severityFilter, matrix.families, matrix.configs, byKey]);

  // Per-config worst-case rate for the column-header heat indicator. Memoized so
  // it isn't recomputed on every render (e.g. each cell click that opens the drawer).
  const colWorst = useMemo(() => {
    const m: Record<string, number> = {};
    for (const c of matrix.configs) {
      m[c.config_id] = Math.max(
        0,
        ...matrix.families.map((f) =>
          byKey.get(`${f}|${c.config_id}`)?.any_breach_rate ?? 0,
        ),
      );
    }
    return m;
  }, [matrix.configs, matrix.families, byKey]);

  const stubByConfig = useMemo(() => {
    const m: Record<string, number | null> = {};
    for (const row of stubbornness?.per_config ?? []) {
      m[row.config_id] = row.avg_iters_to_breach;
    }
    return m;
  }, [stubbornness]);

  return (
    <>
      {/* Filter bar */}
      <section className="flex items-center gap-2 flex-wrap animate-rogue-fade-up">
        <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground mr-2">
          filter:
        </span>
        <FilterChip
          label="all"
          active={severityFilter === "all" && !familyFilter}
          onClick={() => {
            setSeverityFilter("all");
            setFamilyFilter(null);
          }}
        />
        <FilterChip
          label="any breach"
          active={severityFilter === "any-breach" && !familyFilter}
          onClick={() => {
            setSeverityFilter("any-breach");
            setFamilyFilter(null);
          }}
        />
        <FilterChip
          label="≥50%"
          active={severityFilter === "high" && !familyFilter}
          tint="orange"
          onClick={() => {
            setSeverityFilter("high");
            setFamilyFilter(null);
          }}
        />
        <FilterChip
          label="≥70% (critical)"
          active={severityFilter === "critical" && !familyFilter}
          tint="red"
          onClick={() => {
            setSeverityFilter("critical");
            setFamilyFilter(null);
          }}
        />
        {familyFilter && (
          <FilterChip
            label={`family: ${familyFilter} ×`}
            active
            onClick={() => setFamilyFilter(null)}
          />
        )}
        <span className="ml-auto text-[10px] font-mono text-muted-foreground">
          {visibleFamilies.length}/{matrix.families.length} families ·{" "}
          click any cell for breach detail
        </span>
      </section>

      {/* Heatmap */}
      <section
        className="overflow-x-auto border border-border rounded-lg bg-card/40 backdrop-blur-sm animate-rogue-fade-up"
        style={{ animationDelay: "0.1s" }}
      >
        <table className="w-full font-mono text-xs border-collapse">
          <thead>
            <tr className="border-b border-border bg-background/60">
              <th className="text-left p-3 sticky left-0 bg-background/95 backdrop-blur-sm font-semibold tracking-[0.15em] uppercase text-[10px] z-10 border-r border-border min-w-[180px]">
                Attack family
              </th>
              {matrix.configs.map((c) => {
                const worst = colWorst[c.config_id] ?? 0;
                const headerTint =
                  worst >= 0.7
                    ? "text-rogue-red"
                    : worst >= 0.3
                      ? "text-orange-300"
                      : "text-muted-foreground";
                const stubIters = stubByConfig[c.config_id];
                return (
                  <th
                    key={c.config_id}
                    className="text-center p-3 font-semibold tracking-[0.15em] uppercase text-[10px] whitespace-nowrap"
                    title={c.config_id}
                  >
                    <div className="flex flex-col items-center gap-1">
                      <span className="text-foreground">
                        {shortConfigName(c.config_name)}
                      </span>
                      <span
                        className={`text-[9px] tabular-nums ${headerTint}`}
                      >
                        worst {Math.round(worst * 100)}%
                      </span>
                      {stubIters !== undefined && stubIters !== null && (
                        <span
                          className="text-[9px] tabular-nums rogue-accent-stubbornness-text"
                          title="§10.7 PAIR avg iterations to breach — lower = more vulnerable to iterative refinement"
                        >
                          PAIR {stubIters.toFixed(2)} iters
                        </span>
                      )}
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {visibleFamilies.map((family, rowIdx) => (
              <tr key={family} className="border-b border-border/50 last:border-b-0 group">
                <td className="p-3 sticky left-0 bg-background/95 backdrop-blur-sm font-mono text-[11px] whitespace-nowrap border-r border-border z-10 group-hover:text-rogue-green transition-colors">
                  <button
                    type="button"
                    onClick={() =>
                      setFamilyFilter((f) => (f === family ? null : family))
                    }
                    className="text-left hover:text-rogue-green transition-colors"
                  >
                    {family}
                  </button>
                </td>
                {matrix.configs.map((c, colIdx) => {
                  const cell = byKey.get(`${family}|${c.config_id}`);
                  const rate = cell?.any_breach_rate ?? 0;
                  const stagger = Math.min((rowIdx + colIdx) * 0.02, 0.6);
                  return (
                    <td key={c.config_id} className="p-0 align-middle">
                      <HeatmapCell
                        rate={rate}
                        delay={stagger}
                        cell={cell}
                        onClick={() => cell && setOpenCell(cell)}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <MatrixCellDrawer
        open={openCell !== null}
        cell={openCell}
        onClose={() => setOpenCell(null)}
      />
    </>
  );
}

function HeatmapCell({
  rate,
  delay,
  cell,
  onClick,
}: {
  rate: number;
  delay: number;
  cell: BreachCell | undefined;
  onClick: () => void;
}) {
  if (!cell || rate === 0) {
    return (
      <div
        className="h-14 flex items-center justify-center text-muted-foreground/40 animate-rogue-cell-pop"
        style={{ animationDelay: `${delay}s` }}
      >
        —
      </div>
    );
  }
  const intensity = Math.round(rate * 100);
  const { bg, text, pulse } = colorFor(rate);
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full h-14 flex items-center justify-center ${bg} ${text} font-bold tabular-nums border-r border-border/30 transition-all hover:scale-110 hover:z-10 hover:shadow-[0_0_16px_rgba(255,0,60,0.4)] cursor-pointer relative ${pulse} animate-rogue-cell-pop`}
      style={{ animationDelay: `${delay}s` }}
      title={`${cell.title} on ${cell.config_name} — ${intensity}% any-breach (n=${cell.n_trials}) · click to inspect`}
    >
      {intensity}%
    </button>
  );
}

function colorFor(rate: number): { bg: string; text: string; pulse: string } {
  if (rate >= 0.7)
    return {
      bg: "bg-rogue-red/30",
      text: "text-red-100",
      pulse: "rogue-cell-critical",
    };
  if (rate >= 0.5) return { bg: "bg-orange-500/40", text: "text-orange-100", pulse: "" };
  if (rate >= 0.3) return { bg: "bg-yellow-500/30", text: "text-yellow-100", pulse: "" };
  if (rate >= 0.1) return { bg: "bg-blue-500/20", text: "text-blue-100", pulse: "" };
  return { bg: "bg-card/30", text: "text-muted-foreground", pulse: "" };
}

function FilterChip({
  label,
  active,
  tint,
  onClick,
}: {
  label: string;
  active: boolean;
  tint?: "red" | "orange";
  onClick: () => void;
}) {
  const tintClass =
    tint === "red"
      ? active
        ? "border-rogue-red text-rogue-red bg-rogue-red/15"
        : "border-border text-muted-foreground hover:border-rogue-red hover:text-rogue-red"
      : tint === "orange"
        ? active
          ? "border-orange-500 text-orange-300 bg-orange-500/15"
          : "border-border text-muted-foreground hover:border-orange-500 hover:text-orange-300"
        : active
          ? "border-rogue-green text-rogue-green bg-rogue-green/15"
          : "border-border text-muted-foreground hover:border-rogue-green hover:text-rogue-green";
  return (
    <button
      type="button"
      onClick={onClick}
      className={`text-[10px] font-mono uppercase tracking-wider px-2.5 py-1 border rounded-md transition-colors ${tintClass}`}
    >
      {label}
    </button>
  );
}

function shortConfigName(name: string): string {
  return name.replace(/^Acme\s*·\s*/, "");
}
