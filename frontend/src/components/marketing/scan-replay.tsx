"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import {
  Play,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  Wrench,
} from "lucide-react";

import demoScan from "@/data/demo-scan.json";
import { cn } from "@/lib/utils";

/**
 * ScanReplay, the public /try experience: a click-to-run REPLAY of a recorded
 * ROGUE scan (`@/data/demo-scan.json`). No signup, no live model call, no
 * network, every attack and verdict is pre-recorded and replayed for effect.
 *
 * Visuals mirror the marketing previews 1:1 (preview/dashboard-preview.tsx +
 * report-preview.tsx): faux app-window chrome, `.rogue-card`, the canonical
 * rogue-green / rogue-red / orange severity banding, Geist / Geist Mono.
 *
 * States: idle (button only) → running (attacks animate onto the ladder one at
 * a time, each resolving to a verdict, live counter + progress bar) → done
 * (every row settled + the report card fades in, a Replay button appears).
 *
 * One timer drives the whole animation; it is cleared on unmount and on replay.
 * Honors prefers-reduced-motion: when set, the scan jumps straight to the done
 * state with no animation.
 */

// ── Frozen data shape (sibling-authored JSON). ──────────────────────────────
type Verdict = "breach" | "clean";

interface Attack {
  id: string;
  family: string;
  title: string;
  vector: string;
  tier: number;
  payload_excerpt: string;
  verdict: Verdict;
  // null on clean rows; always a severity string on breach rows.
  severity: string | null;
  response_excerpt: string;
}

interface ScanReport {
  score: number;
  level: string;
  n_tests: number;
  n_breaches: number;
  breach_rate: number;
  cost_usd: number;
  top_findings: string[];
  recommendations: string[];
}

const TARGET = demoScan.target;
const ATTACKS = demoScan.attacks as Attack[];
const REPORT = demoScan.report as ScanReport;

const STEP_MS = 750; // per-attack cadence while running

// ── Severity / score color vocabulary (globals.css §ROGUE). ─────────────────
const SEVERITY_PILL: Record<string, string> = {
  critical: "border-rogue-red/40 bg-rogue-red/10 text-rogue-red",
  high: "border-orange-500/40 bg-orange-500/10 text-orange-300",
  medium: "border-yellow-500/40 bg-yellow-500/10 text-yellow-300",
  low: "border-rogue-green/40 bg-rogue-green/10 text-rogue-green",
};

function severityPill(severity: string): string {
  return SEVERITY_PILL[severity.toLowerCase()] ?? SEVERITY_PILL.low;
}

/** Banded text tint for the big score (report/page.tsx SCORE_TINT_TEXT). */
function scoreTint(level: string): string {
  switch (level.toUpperCase()) {
    case "CRITICAL":
      return "text-rogue-red";
    case "HIGH":
      return "text-orange-300";
    case "MEDIUM":
      return "text-yellow-300";
    default:
      return "text-rogue-green";
  }
}

function levelPill(level: string): string {
  switch (level.toUpperCase()) {
    case "CRITICAL":
      return "border-rogue-red/40 bg-rogue-red/10 text-rogue-red";
    case "HIGH":
      return "border-orange-500/40 bg-orange-500/10 text-orange-300";
    case "MEDIUM":
      return "border-yellow-500/40 bg-yellow-500/10 text-yellow-300";
    default:
      return "border-rogue-green/40 bg-rogue-green/10 text-rogue-green";
  }
}

// ── Reducer: a single `revealed` cursor drives the whole replay. ────────────
// revealed === -1  → idle (nothing run yet)
// 0..N             → that many attack rows visible/resolved
// >= N             → done (report shown)
type Phase = "idle" | "running" | "done";

interface State {
  phase: Phase;
  revealed: number;
}

type Action =
  | { type: "start" }
  | { type: "tick" }
  | { type: "finish" }
  | { type: "reset" };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "start":
      return { phase: "running", revealed: 0 };
    case "tick": {
      const next = state.revealed + 1;
      if (next >= ATTACKS.length) {
        return { phase: "done", revealed: ATTACKS.length };
      }
      return { phase: "running", revealed: next };
    }
    case "finish":
      return { phase: "done", revealed: ATTACKS.length };
    case "reset":
      return { phase: "idle", revealed: -1 };
    default:
      return state;
  }
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export function ScanReplay({ className }: { className?: string } = {}) {
  const [state, dispatch] = useReducer(reducer, { phase: "idle", revealed: -1 });
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const run = useCallback(() => {
    clearTimer();
    if (prefersReducedMotion()) {
      dispatch({ type: "finish" });
      return;
    }
    dispatch({ type: "start" });
    timerRef.current = setInterval(() => {
      dispatch({ type: "tick" });
    }, STEP_MS);
  }, [clearTimer]);

  // Stop the timer once we reach the end (the reducer flips to "done").
  useEffect(() => {
    if (state.phase === "done") clearTimer();
  }, [state.phase, clearTimer]);

  // Clean up on unmount.
  useEffect(() => clearTimer, [clearTimer]);

  const isIdle = state.phase === "idle";
  const isDone = state.phase === "done";

  // How many attacks are visible right now (idle → none).
  const visibleCount = isIdle ? 0 : Math.min(state.revealed, ATTACKS.length);
  const visible = ATTACKS.slice(0, Math.max(visibleCount, 0));
  const breachedSoFar = visible.filter((a) => a.verdict === "breach").length;
  const progressPct = isDone
    ? 100
    : Math.round((visibleCount / ATTACKS.length) * 100);

  return (
    <div
      className={cn(
        "rounded-xl border border-border bg-card/40 overflow-hidden shadow-2xl shadow-black/40",
        className,
      )}
    >
      {/* ── Faux window chrome. ── */}
      <div className="flex items-center gap-3 border-b border-border bg-black/60 px-4 py-2.5">
        <div className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-full bg-rogue-red/70" />
          <span className="h-3 w-3 rounded-full bg-orange-400/70" />
          <span className="h-3 w-3 rounded-full bg-rogue-green/70" />
        </div>
        <div className="min-w-0 flex-1 truncate text-center font-mono text-[10px] sm:text-[11px] text-muted-foreground">
          <span className="text-rogue-green">app.rogue</span>
          <span className="opacity-50"> · scans / </span>
          <span className="text-foreground/80 font-mono">{TARGET.name}</span>
        </div>
        <span className="hidden shrink-0 items-center gap-1.5 rounded-md border border-border bg-card/30 px-2 py-0.5 font-mono text-[9px] uppercase tracking-[0.15em] text-muted-foreground sm:inline-flex">
          Recorded scan · replayed
        </span>
      </div>

      {/* ── Body. ── */}
      <div className="bg-black/20 p-4 sm:p-6 space-y-5">
        {/* Target header. */}
        <div className="space-y-1">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
            target
          </p>
          <h3 className="text-xl sm:text-2xl font-bold tracking-tight font-mono break-all">
            {TARGET.name}
          </h3>
          <p className="font-mono text-xs text-muted-foreground break-words">
            {TARGET.model} · {ATTACKS.length} attacks queued
          </p>
          <p className="text-xs text-muted-foreground leading-relaxed border-l-2 border-border pl-3 pt-1 max-w-2xl">
            <span className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground/70">
              system prompt ·{" "}
            </span>
            {TARGET.system_prompt_excerpt}
          </p>
        </div>

        {/* Run / replay control + live counter. */}
        <div className="flex flex-wrap items-center gap-4">
          {isIdle ? (
            <button
              type="button"
              onClick={run}
              className={cn(
                "inline-flex items-center gap-2 rounded-lg px-5 py-2.5",
                "bg-rogue-green text-black font-mono text-sm font-bold tracking-[0.15em] uppercase",
                "transition-opacity hover:opacity-90",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rogue-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background",
              )}
            >
              <Play className="h-4 w-4" aria-hidden /> Run the demo scan
            </button>
          ) : (
            <button
              type="button"
              onClick={run}
              disabled={!isDone}
              className={cn(
                "inline-flex items-center gap-2 rounded-lg border border-border px-4 py-2",
                "font-mono text-xs font-bold tracking-[0.15em] uppercase text-foreground",
                "transition-colors hover:border-rogue-green hover:text-rogue-green",
                "disabled:opacity-40 disabled:hover:border-border disabled:hover:text-foreground",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rogue-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background",
              )}
            >
              <RotateCcw className="h-3.5 w-3.5" aria-hidden /> Replay
            </button>
          )}

          {!isIdle && (
            <div className="flex items-center gap-3 font-mono text-xs tabular-nums">
              <span className="text-muted-foreground">
                <span className="text-foreground font-bold">{visibleCount}</span>{" "}
                tested
              </span>
              <span className="text-muted-foreground/50">·</span>
              <span className={breachedSoFar > 0 ? "text-rogue-red" : "text-muted-foreground"}>
                <span className="font-bold">{breachedSoFar}</span> breached
              </span>
              {state.phase === "running" && (
                <span className="inline-flex items-center gap-1.5 text-rogue-green">
                  <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-rogue-green" />
                  scanning
                </span>
              )}
            </div>
          )}
        </div>

        {/* Progress bar (appears once a run starts). */}
        {!isIdle && (
          <div className="h-2.5 w-full overflow-hidden rounded-full bg-card/40 border border-border">
            <div
              className={cn(
                "h-full rounded-full transition-[width] duration-500 ease-out",
                isDone && REPORT.n_breaches > 0 ? "bg-rogue-red" : "bg-rogue-green",
              )}
              style={{ width: `${progressPct}%` }}
            />
          </div>
        )}

        {/* Attack ladder. */}
        {isIdle ? (
          <div className="rounded-lg border border-dashed border-border bg-card/20 px-4 py-10 text-center">
            <p className="font-mono text-xs text-muted-foreground">
              Press <span className="text-rogue-green">Run the demo scan</span> to
              watch {ATTACKS.length} recorded attacks land on the ladder.
            </p>
          </div>
        ) : (
          <ul className="space-y-2.5">
            {visible.map((atk) => (
              <AttackRow key={atk.id} attack={atk} />
            ))}
          </ul>
        )}

        {/* Report card (fades in on done). */}
        {isDone && <ReportCard className="animate-rogue-fade-up" />}
      </div>
    </div>
  );
}

function AttackRow({ attack }: { attack: Attack }) {
  const breach = attack.verdict === "breach";
  return (
    <li
      className={cn(
        "animate-rogue-fade-up rounded-lg border bg-card/40 p-3 sm:p-4 space-y-2",
        breach
          ? "border-rogue-red/40 bg-rogue-red/5"
          : "border-rogue-green/30 bg-rogue-green/[0.03]",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center rounded-md border border-border bg-card/40 px-2 py-0.5 font-mono text-[9px] uppercase tracking-[0.15em] text-muted-foreground">
          {attack.family.replace(/_/g, " ")}
        </span>
        <span className="inline-flex items-center rounded-md border border-border bg-card/40 px-2 py-0.5 font-mono text-[9px] uppercase tracking-[0.15em] text-muted-foreground">
          tier {attack.tier}
        </span>
        <span className="text-sm font-semibold tracking-tight break-words">
          {attack.title}
        </span>
        <span
          className={cn(
            "ml-auto inline-flex shrink-0 items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.15em] font-bold",
            breach
              ? severityPill(attack.severity ?? "low")
              : "border-rogue-green/40 bg-rogue-green/10 text-rogue-green",
          )}
        >
          {breach ? (
            <>
              <ShieldAlert className="h-3 w-3" aria-hidden />
              breach · {attack.severity}
            </>
          ) : (
            <>
              <ShieldCheck className="h-3 w-3" aria-hidden />
              refused
            </>
          )}
        </span>
      </div>

      <p className="font-mono text-[11px] leading-relaxed text-muted-foreground break-words">
        <span className="text-muted-foreground/60">payload · </span>
        {attack.payload_excerpt}
      </p>

      {breach && (
        <p className="rounded-md border border-rogue-red/30 bg-rogue-red/5 px-3 py-2 font-mono text-[11px] leading-relaxed text-rogue-red/90 break-words">
          <span className="opacity-60">model · </span>
          {attack.response_excerpt}
        </p>
      )}
    </li>
  );
}

function ReportCard({ className }: { className?: string }) {
  const breachPct = Math.round(REPORT.breach_rate * 100);
  return (
    <section
      className={cn(
        "rounded-xl border border-border bg-rogue-bg-deep/60 p-4 sm:p-6 space-y-5",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
          scan complete · report
        </p>
        <span className="shrink-0 rounded-md border border-border bg-card/30 px-2 py-0.5 font-mono text-[9px] uppercase tracking-[0.15em] text-muted-foreground">
          recorded · replayed
        </span>
      </div>

      {/* Risk headline. */}
      <div className="flex flex-wrap items-end gap-4 sm:gap-5">
        <div className="flex items-baseline gap-2">
          <span
            className={cn(
              "text-5xl font-bold leading-none tabular-nums",
              scoreTint(REPORT.level),
            )}
          >
            {REPORT.score}
          </span>
          <span className="font-mono text-lg text-muted-foreground">/100</span>
        </div>
        <div className="space-y-1.5">
          <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted-foreground">
            Risk score
          </p>
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-xs font-bold uppercase tracking-[0.15em]",
              levelPill(REPORT.level),
            )}
          >
            <ShieldAlert className="h-3 w-3" aria-hidden />
            {REPORT.level}
          </span>
        </div>
      </div>

      {/* KPI row. */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Kpi label="Tests" value={String(REPORT.n_tests)} />
        <Kpi label="Breaches" value={String(REPORT.n_breaches)} tint="text-rogue-red" />
        <Kpi label="Breach rate" value={`${breachPct}%`} tint="text-rogue-red" />
        <Kpi label="Cost" value={`$${REPORT.cost_usd.toFixed(2)}`} />
      </div>

      {/* Top findings. */}
      <section className="space-y-3 rounded-lg border border-border bg-card/30 p-4 sm:p-5">
        <h4 className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
          Top findings
        </h4>
        <ul className="space-y-2.5">
          {REPORT.top_findings.map((f, i) => (
            <li key={i} className="flex gap-3">
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-rogue-red" aria-hidden />
              <p className="text-sm leading-relaxed text-foreground/90">{f}</p>
            </li>
          ))}
        </ul>
      </section>

      {/* Recommendations. */}
      <section className="space-y-3 rounded-lg border border-border bg-card/30 p-4 sm:p-5">
        <h4 className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
          Recommendations
        </h4>
        <ul className="space-y-2.5">
          {REPORT.recommendations.map((r, i) => (
            <li key={i} className="flex gap-3">
              <Wrench className="mt-0.5 h-4 w-4 shrink-0 text-rogue-green" aria-hidden />
              <p className="text-sm leading-relaxed text-foreground/90">{r}</p>
            </li>
          ))}
        </ul>
      </section>
    </section>
  );
}

function Kpi({
  label,
  value,
  tint,
}: {
  label: string;
  value: string;
  tint?: string;
}) {
  return (
    <div className="space-y-1.5 rounded-md border border-border bg-card/30 px-4 py-3">
      <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted-foreground">
        {label}
      </p>
      <p className={cn("text-2xl font-bold tabular-nums", tint)}>{value}</p>
    </div>
  );
}
