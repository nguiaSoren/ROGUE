import { ShieldAlert, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * DashboardPreview — a marketing, screenshot-style recreation of the auth-gated
 * scan dashboard (the `/scans/{id}` detail + report + a `/scans` list snippet).
 *
 * This is NOT the real dashboard and pulls no live data: every number is static,
 * illustrative example data (the real screens are behind sign-in, so we can't
 * screenshot them). It's a server component — pure markup, no hooks — wrapped in a
 * faux app-window frame so it reads as a product shot. Visuals mirror the live
 * components 1:1 where it matters:
 *   - risk headline + /100 + banded pill  → scans/[scanId]/report/page.tsx RiskHeadline
 *   - KPI row (tests/breaches/rate/cost)  → report/page.tsx Kpi
 *   - progress bar + readouts             → components/scan-progress.tsx
 *   - score/status badges + scan rows     → components/score-badge.tsx, scans/page.tsx
 * Color vocabulary is the canonical one (globals.css §ROGUE): rogue-green for OK,
 * rogue-red for breach/critical, orange for HIGH.
 */

// ── Example data — illustrative only, not a real scan. ───────────────────────
const EXAMPLE = {
  scanId: "scan_8f3a2",
  target: "claude-haiku-4.5",
  pack: "owasp-llm-top10",
  score: 68,
  level: "HIGH" as const,
  nTests: 142,
  nBreaches: 11,
  breachRatePct: 7.7,
  costUsd: 0.84,
  progressPct: 100,
  nCompleted: 142,
  topAttack: "Crescendo",
};

const RECENT_SCANS: ReadonlyArray<{
  scanId: string;
  target: string;
  status: "completed" | "running" | "failed";
  breaches: number;
  score: number | null;
}> = [
  { scanId: "scan_8f3a2", target: "claude-haiku-4.5", status: "completed", breaches: 11, score: 68 },
  { scanId: "scan_7c1d9", target: "gpt-4o-mini", status: "completed", breaches: 4, score: 41 },
  { scanId: "scan_6b0a4", target: "llama-3.3-70b", status: "running", breaches: 2, score: null },
];

// Banded text tint for the big score number (report/page.tsx SCORE_TINT_TEXT).
const SCORE_TINT_TEXT = {
  CRITICAL: "text-rogue-red",
  HIGH: "text-orange-300",
  MEDIUM: "text-yellow-300",
  LOW: "text-rogue-green",
} as const;

// Pill tints — the shared severity vocabulary (score-badge.tsx TINT_CLASS).
const PILL = {
  red: "border-rogue-red/40 bg-rogue-red/10 text-rogue-red",
  orange: "border-orange-500/40 bg-orange-500/10 text-orange-300",
  green: "border-rogue-green/40 bg-rogue-green/10 text-rogue-green",
  muted: "border-border bg-card/30 text-muted-foreground",
} as const;

function scoreTint(score: number | null) {
  if (score === null) return PILL.muted;
  if (score >= 70) return PILL.red;
  if (score >= 40) return PILL.orange;
  return PILL.green;
}

export function DashboardPreview({ className }: { className?: string } = {}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-border bg-card/40 backdrop-blur-sm overflow-hidden shadow-2xl",
        className,
      )}
    >
      {/* ── Faux window chrome — darker than the body so it reads as a frame. ── */}
      <div className="flex items-center gap-3 border-b border-border bg-black/60 px-4 py-2.5">
        <div className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-full bg-rogue-red/70" />
          <span className="h-3 w-3 rounded-full bg-orange-400/70" />
          <span className="h-3 w-3 rounded-full bg-rogue-green/70" />
        </div>
        <div className="flex-1 truncate text-center font-mono text-[11px] text-muted-foreground">
          app.rogue · scans / {EXAMPLE.scanId}
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card/30 px-2 py-0.5 font-mono text-[9px] uppercase tracking-[0.15em] text-muted-foreground">
          Example scan · illustrative
        </span>
      </div>

      {/* ── Dashboard body. ── */}
      <div className="bg-black/20 p-5 sm:p-6 space-y-5">
        {/* Header row. */}
        <div className="space-y-1">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
            /scans/{EXAMPLE.scanId}
          </p>
          <h2 className="text-2xl font-bold tracking-tight font-mono break-all">
            {EXAMPLE.target}
          </h2>
          <p className="font-mono text-xs text-muted-foreground">
            {EXAMPLE.target} · {EXAMPLE.pack} pack · {EXAMPLE.nTests} tests planned
          </p>
        </div>

        {/* Risk headline — the score leads. */}
        <section className="rounded-xl border border-border bg-card/40 backdrop-blur-sm p-5 space-y-3">
          <div className="flex items-end gap-5 flex-wrap">
            <div className="flex items-baseline gap-2">
              <span
                className={cn(
                  "text-5xl font-bold tabular-nums leading-none",
                  SCORE_TINT_TEXT[EXAMPLE.level],
                )}
              >
                {EXAMPLE.score}
              </span>
              <span className="text-lg font-mono text-muted-foreground">/100</span>
            </div>
            <div className="space-y-1.5">
              <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted-foreground">
                Risk score
              </p>
              <span
                className={cn(
                  "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-xs uppercase tracking-[0.15em] font-bold",
                  PILL.orange,
                )}
              >
                <ShieldAlert className="h-3 w-3" aria-hidden />
                {EXAMPLE.level}
              </span>
            </div>
            <div className="ml-auto text-right space-y-1">
              <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted-foreground">
                Top attack
              </p>
              <p className="text-sm font-bold break-words max-w-xs">
                {EXAMPLE.topAttack}
              </p>
            </div>
          </div>
          <p className="text-xs text-muted-foreground leading-relaxed border-t border-border pt-3">
            Score weights reproduced breaches by severity and attack diversity across the
            run; higher means more exploitable.
          </p>
        </section>

        {/* KPI row. */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Kpi label="Tests">
            <span className="text-2xl font-bold tabular-nums">{EXAMPLE.nTests}</span>
          </Kpi>
          <Kpi label="Breaches">
            <span className="text-2xl font-bold tabular-nums text-rogue-red">
              {EXAMPLE.nBreaches}
            </span>
          </Kpi>
          <Kpi label="Breach rate">
            <span className="text-2xl font-bold tabular-nums text-rogue-red">
              {EXAMPLE.breachRatePct}%
            </span>
          </Kpi>
          <Kpi label="Cost">
            <span className="text-2xl font-bold tabular-nums">
              ${EXAMPLE.costUsd.toFixed(2)}
            </span>
          </Kpi>
        </div>

        {/* Scan-status / progress card. */}
        <section className="rounded-xl border border-border bg-card/40 backdrop-blur-sm p-5 space-y-4">
          <div className="flex items-center gap-3">
            <span
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.15em]",
                PILL.green,
              )}
            >
              completed
            </span>
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground font-mono">
              risk
              <span
                className={cn(
                  "inline-flex items-center rounded-md border px-2 py-0.5 font-mono text-xs font-bold tabular-nums",
                  scoreTint(EXAMPLE.score),
                )}
              >
                {EXAMPLE.score}
              </span>
            </span>
          </div>

          <div className="space-y-2">
            <div className="h-3 w-full overflow-hidden rounded-full bg-card/40 border border-border">
              <div
                className="h-full rounded-full bg-rogue-green"
                style={{ width: `${EXAMPLE.progressPct}%` }}
              />
            </div>
            <div className="flex items-center justify-between gap-4 flex-wrap font-mono text-xs text-muted-foreground tabular-nums">
              <span className="text-foreground font-bold">{EXAMPLE.progressPct}%</span>
              <span>
                {EXAMPLE.nCompleted}/{EXAMPLE.nTests} tests complete
              </span>
              <span>
                Top attack: <span className="text-foreground">{EXAMPLE.topAttack}</span>
              </span>
            </div>
          </div>

          <div className="flex items-center gap-6 flex-wrap font-mono text-xs">
            <span className="text-rogue-red">{EXAMPLE.nBreaches} breaches found</span>
            <span className="text-muted-foreground">
              ~${EXAMPLE.costUsd.toFixed(2)} spent
              <span className="opacity-60"> (estimate)</span>
            </span>
          </div>

          <span className="inline-flex items-center gap-2 font-mono text-xs uppercase tracking-[0.15em] text-rogue-green border border-rogue-green/40 rounded-md px-3 py-1.5">
            View report <ArrowRight className="h-3.5 w-3.5" aria-hidden />
          </span>
        </section>

        {/* Recent scans list. */}
        <section className="space-y-2">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
            Recent scans
          </p>
          <div className="overflow-hidden rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
                  <th className="px-4 py-2.5 font-medium">Target</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 font-medium text-right">Breaches</th>
                  <th className="px-4 py-2.5 font-medium text-right">Score</th>
                </tr>
              </thead>
              <tbody>
                {RECENT_SCANS.map((s) => (
                  <tr
                    key={s.scanId}
                    className="border-b border-border/50 last:border-0"
                  >
                    <td className="px-4 py-2.5 font-mono text-xs text-rogue-green">
                      {s.target}
                    </td>
                    <td className="px-4 py-2.5">
                      <span
                        className={cn(
                          "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.15em]",
                          s.status === "failed"
                            ? PILL.red
                            : s.status === "running"
                              ? PILL.green
                              : PILL.green,
                        )}
                      >
                        {s.status === "running" && (
                          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-rogue-green" />
                        )}
                        {s.status}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums font-mono text-xs">
                      <span
                        className={
                          s.breaches > 0 ? "text-rogue-red" : "text-muted-foreground"
                        }
                      >
                        {s.breaches}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <span
                        className={cn(
                          "inline-flex items-center rounded-md border px-2 py-0.5 font-mono text-xs font-bold tabular-nums",
                          scoreTint(s.score),
                        )}
                      >
                        {s.score ?? "—"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}

function Kpi({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-border bg-card/30 px-4 py-3 space-y-1.5">
      <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted-foreground">
        {label}
      </p>
      <div className="leading-tight">{children}</div>
    </div>
  );
}
