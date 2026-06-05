"use client";

import { useEffect, useMemo, useState } from "react";
import {
  api,
  type BreachCell,
  type BreachMatrixResponse,
  type StubbornnessStatsResponse,
} from "@/lib/api";
import { MatrixCellDrawer, prefetchAttackDetail } from "@/components/matrix-drawer";
import { ProviderLogo } from "@/components/ui/provider-logo";

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
  // `matrix` (this-run × baseline) is the only quadrant rendered server-side.
  // The other three quadrants of the SCOPE × ATTACKER 2×2 are ~768 KB each, so
  // they're fetched client-side after mount (see effect below) rather than
  // blocking SSR. Until they arrive, the toggles stay hidden and the grid shows
  // the baseline; any quadrant that fails to load degrades back to baseline.
  matrix: BreachMatrixResponse;
  stubbornness: StubbornnessStatsResponse | null;
}) {
  const [thisRunAugmented, setThisRunAugmented] =
    useState<BreachMatrixResponse | null>(null);
  const [allTimeBaseline, setAllTimeBaseline] =
    useState<BreachMatrixResponse | null>(null);
  const [augmented, setAugmented] = useState<BreachMatrixResponse | null>(null);
  // false until the background quadrant load settles. While false we render the
  // SCOPE/ATTACKER toggles optimistically (they belong at the top from the very
  // first paint) and show a "loading" hint if the user flips one before its data
  // lands; once settled, any quadrant that genuinely has no data hides its toggle.
  const [augReady, setAugReady] = useState(false);

  // ?date=YYYY-MM-DD pins a non-default run day. The page is statically rendered
  // for the default (most-data) day, so this override is read client-side from
  // the URL (via window.location, NOT useSearchParams — that would deopt the
  // static page to client-side rendering). It's a debug/power-user param that
  // internal navigation never sets; when present it swaps the this-run baseline
  // grid. The headline stats above the grid reflect the default day — see
  // ROGUE_PLAN.md STATUS "Post-deadline frontend perf — 2026-06-01".
  const [dateMatrix, setDateMatrix] = useState<BreachMatrixResponse | null>(null);
  useEffect(() => {
    const date = new URLSearchParams(window.location.search).get("date");
    // No pinned date (the common path) or it equals the default day → nothing to
    // fetch; leave the default-day baseline in place. (No synchronous reset here:
    // a pinned ?date= should survive an ISR default-day change, and React 19
    // flags setState in the effect body as a cascading-render anti-pattern.)
    if (!date || date === matrix.target_date) return;
    let cancelled = false;
    api
      .breachMatrix(date)
      .then((m) => {
        if (!cancelled) setDateMatrix(m);
      })
      .catch(() => {
        /* fall back to the default-day baseline */
      });
    return () => {
      cancelled = true;
    };
  }, [matrix.target_date]);

  // The effective this-run baseline: the pinned day if ?date= overrode it, else
  // the statically-rendered default day.
  const baseline = dateMatrix ?? matrix;

  // Lazy-load the three heavy quadrants in the background once the grid is up.
  useEffect(() => {
    let cancelled = false;
    void Promise.all([
      api.breachMatrix(baseline.target_date, "thisrun_augmented").catch(() => null),
      api.breachMatrix(undefined, "alltime_baseline").catch(() => null),
      api.breachMatrix(undefined, "augmented").catch(() => null),
    ]).then(([tra, atb, aug]) => {
      if (cancelled) return;
      setThisRunAugmented(tra);
      setAllTimeBaseline(atb);
      setAugmented(aug);
      setAugReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, [baseline.target_date]);

  const [openCell, setOpenCell] = useState<BreachCell | null>(null);
  const [familyFilter, setFamilyFilter] = useState<string | null>(null);
  const [severityFilter, setSeverityFilter] = useState<
    "all" | "critical" | "high" | "any-breach"
  >("all");
  const [configFilter, setConfigFilter] = useState<string | null>(null);
  // Two fully-independent axes (the 2×2):
  //   SCOPE    — this run (one day) vs all-time (every run day merged)
  //   ATTACKER — baseline (raw single-shot) vs + augmentations (persona + PAIR)
  // Default SCOPE to All-time when THIS run is empty / almost-empty — a sparse run
  // day (few or no breaching cells) would otherwise render a near-blank grid.
  // All-time merges every run, so it shows the accumulated matrix; the user can
  // still flip back to This run. Lazy initializer — computed once from the
  // server-passed this-run baseline (`matrix`, before any ?date= override).
  const THIS_RUN_MIN_BREACHING_CELLS = 3;
  const [scope, setScope] = useState<"this-run" | "all-time">(() =>
    matrix.cells.filter((c) => c.any_breach_rate > 0).length <
    THIS_RUN_MIN_BREACHING_CELLS
      ? "all-time"
      : "this-run",
  );
  const [showAugmented, setShowAugmented] = useState(false);

  // Show both toggle groups from the first paint. Before the background load
  // settles we assume the data exists (it does in the deployed corpus); after it
  // settles, hide whichever axis truly has no data.
  const hasAugment = !augReady || Boolean(thisRunAugmented || augmented);
  const hasAllTime = !augReady || Boolean(allTimeBaseline || augmented);
  // True when the selected quadrant needs data that hasn't loaded yet, so the
  // grid is still showing the baseline fallback under an all-time/augmented label.
  const augPending =
    !augReady && (scope === "all-time" || showAugmented);

  // Active dataset = the quadrant for (scope, attacker). Any missing quadrant
  // degrades gracefully back toward the always-present this-run baseline.
  const active = useMemo(() => {
    if (scope === "all-time") {
      return showAugmented
        ? augmented ?? allTimeBaseline ?? baseline
        : allTimeBaseline ?? baseline;
    }
    return showAugmented ? thisRunAugmented ?? baseline : baseline;
  }, [scope, showAugmented, baseline, thisRunAugmented, allTimeBaseline, augmented]);

  // Pre-compute the worst-rate cell per (family × config) so the click
  // handler can yank the canonical primitive for the cell quickly.
  const byKey = useMemo(() => {
    const m = new Map<string, BreachCell>();
    for (const c of active.cells) {
      const key = `${c.family}|${c.deployment_config_id}`;
      const prev = m.get(key);
      // Worst = highest any-breach, tie-broken by full-breach so the most
      // fully-broken primitive headlines the cell (e.g. a 100%/100% beats a
      // 100%/80% at the same any-breach rate).
      if (
        !prev ||
        c.any_breach_rate > prev.any_breach_rate ||
        (c.any_breach_rate === prev.any_breach_rate &&
          c.full_breach_rate > prev.full_breach_rate)
      )
        m.set(key, c);
    }
    return m;
  }, [active.cells]);

  // Family filter selects a single family (click a row label). The severity
  // filter no longer hides families — it DIMS cells below the threshold (see
  // dimThreshold), so ≥50% vs ≥70% look different even when most families breach.
  const visibleFamilies = useMemo(
    () => (familyFilter ? [familyFilter] : active.families),
    [familyFilter, active.families],
  );

  // Config (column) filter — click a column header to show only that deployment.
  const visibleConfigs = useMemo(
    () =>
      configFilter
        ? active.configs.filter((c) => c.config_id === configFilter)
        : active.configs,
    [configFilter, active.configs],
  );

  // Below this any-breach rate a cell is dimmed (−1 = "all" = dim nothing).
  const dimThreshold =
    severityFilter === "critical"
      ? 0.7
      : severityFilter === "high"
        ? 0.5
        : severityFilter === "any-breach"
          ? 0.0001
          : -1;

  // Per-config worst-case rate for the column-header heat indicator. Memoized so
  // it isn't recomputed on every render (e.g. each cell click that opens the drawer).
  const colWorst = useMemo(() => {
    const m: Record<string, number> = {};
    for (const c of active.configs) {
      m[c.config_id] = Math.max(
        0,
        ...active.families.map((f) =>
          byKey.get(`${f}|${c.config_id}`)?.any_breach_rate ?? 0,
        ),
      );
    }
    return m;
  }, [active.configs, active.families, byKey]);

  const stubByConfig = useMemo(() => {
    const m: Record<string, number | null> = {};
    for (const row of stubbornness?.per_config ?? []) {
      m[row.config_id] = row.avg_iters_to_breach;
    }
    return m;
  }, [stubbornness]);

  return (
    <>
      {/* SCOPE × ATTACKER — two fully independent toggles (the 2×2). SCOPE
          swaps the date window (this run's day vs every run merged); ATTACKER
          swaps the technique set (raw single-shot vs persona-wrap + PAIR). */}
      {(hasAllTime || hasAugment) && (
        <section className="flex items-center gap-x-5 gap-y-3 flex-wrap animate-rogue-fade-up">
          {hasAllTime && (
            <div className="inline-flex items-center gap-2">
              <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground">
                scope:
              </span>
              <div className="inline-flex rounded-md border border-border overflow-hidden font-mono text-[10px] uppercase tracking-wider">
                <button
                  type="button"
                  onClick={() => setScope("this-run")}
                  className={`px-3 py-1.5 transition-colors ${
                    scope === "this-run"
                      ? "bg-rogue-green/15 text-rogue-green"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  This run
                </button>
                <button
                  type="button"
                  onClick={() => setScope("all-time")}
                  className={`px-3 py-1.5 border-l border-border transition-colors ${
                    scope === "all-time"
                      ? "bg-rogue-green/15 text-rogue-green"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  All-time
                </button>
              </div>
            </div>
          )}
          {hasAugment && (
            <div className="inline-flex items-center gap-2">
              <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground">
                attacker:
              </span>
              <div className="inline-flex rounded-md border border-border overflow-hidden font-mono text-[10px] uppercase tracking-wider">
                <button
                  type="button"
                  onClick={() => setShowAugmented(false)}
                  className={`px-3 py-1.5 transition-colors ${
                    !showAugmented
                      ? "bg-rogue-green/15 text-rogue-green"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  Baseline
                </button>
                <button
                  type="button"
                  onClick={() => setShowAugmented(true)}
                  className={`px-3 py-1.5 border-l border-border transition-colors ${
                    showAugmented
                      ? "bg-rogue-red/15 text-rogue-red"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  + Augmentations
                </button>
              </div>
            </div>
          )}
          <span className="text-[10px] font-mono text-muted-foreground max-w-md leading-snug">
            {scope === "all-time" ? "every run day merged · " : "this run's day · "}
            {showAugmented
              ? "worst-case across persona-wrap + PAIR refinement — how hot each cell gets once the attacker adapts"
              : "raw harvested prompt, N=5 trials per cell — no adaptation"}
            {augPending && (
              <span className="text-rogue-green animate-pulse"> · loading…</span>
            )}
          </span>
        </section>
      )}

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
        {configFilter && (
          <FilterChip
            label={`config: ${shortConfigName(
              active.configs.find((c) => c.config_id === configFilter)
                ?.config_name ?? configFilter,
            )} ×`}
            active
            onClick={() => setConfigFilter(null)}
          />
        )}
        <span className="ml-auto text-[10px] font-mono text-muted-foreground">
          {visibleFamilies.length} families × {visibleConfigs.length} configs ·{" "}
          click a row, column, or cell
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
              {visibleConfigs.map((c) => {
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
                      <button
                        type="button"
                        onClick={() =>
                          setConfigFilter((cf) =>
                            cf === c.config_id ? null : c.config_id,
                          )
                        }
                        className="text-foreground hover:text-rogue-green transition-colors"
                        title="Click to show only this deployment column"
                      >
                        <span className="inline-flex items-center gap-1.5">
                          <ProviderLogo
                            model={c.config_name}
                            className="text-sm opacity-80"
                          />
                          {shortConfigName(c.config_name)}
                        </span>
                      </button>
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
                {visibleConfigs.map((c, colIdx) => {
                  const cell = byKey.get(`${family}|${c.config_id}`);
                  const rate = cell?.any_breach_rate ?? 0;
                  const dimmed = dimThreshold >= 0 && rate < dimThreshold;
                  const stagger = Math.min((rowIdx + colIdx) * 0.02, 0.6);
                  return (
                    <td key={c.config_id} className="p-0 align-middle">
                      <HeatmapCell
                        rate={rate}
                        delay={stagger}
                        cell={cell}
                        dimmed={dimmed}
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
        date={baseline.target_date}
        scope={scope}
        attacker={showAugmented ? "augmented" : "baseline"}
        onClose={() => setOpenCell(null)}
      />
    </>
  );
}

function HeatmapCell({
  rate,
  delay,
  cell,
  dimmed = false,
  onClick,
}: {
  rate: number;
  delay: number;
  cell: BreachCell | undefined;
  dimmed?: boolean;
  onClick: () => void;
}) {
  if (!cell || rate === 0) {
    return (
      <div
        className={`h-14 flex items-center justify-center text-muted-foreground/40 animate-rogue-cell-pop ${
          dimmed ? "opacity-20" : ""
        }`}
        style={{ animationDelay: `${delay}s` }}
      >
        —
      </div>
    );
  }
  const intensity = Math.round(rate * 100);
  const { bg, text, pulse } = colorFor(rate);
  // When the severity filter dims this cell (below threshold), mute it and drop
  // the pulse so only cells that meet the threshold stand out.
  const pulseClass = dimmed ? "" : pulse;
  return (
    <button
      type="button"
      onClick={onClick}
      // Warm the attack-detail cache on hover/focus so the drawer usually opens
      // straight to content instead of showing "loading primitive…".
      onMouseEnter={() => prefetchAttackDetail(cell.primitive_id)}
      onFocus={() => prefetchAttackDetail(cell.primitive_id)}
      className={`w-full h-14 flex items-center justify-center ${bg} ${text} font-bold tabular-nums border-r border-border/30 transition-all hover:scale-110 hover:z-10 hover:shadow-[0_0_16px_rgba(255,0,60,0.4)] cursor-pointer relative ${pulseClass} animate-rogue-cell-pop ${
        dimmed ? "opacity-20 saturate-50" : ""
      }`}
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
