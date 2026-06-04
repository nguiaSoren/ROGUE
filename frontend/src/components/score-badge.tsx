import type { ScanStatus } from "@/lib/platform-api";

/**
 * Severity-tinted badges for the product (`/scans`) pages — the same color
 * vocabulary the matrix/brief pages use (frontend/src/app/globals.css:141),
 * no new tokens.
 *
 * - `ScoreBadge` bands the 0–100 headline `score`: ≥70 red, ≥40 orange, <40 green
 *   (docs/platform/dashboard/report-views.md §4). Null score → a muted "—".
 * - `StatusBadge` tints a `ScanStatus`: running/queued = green/neutral, completed
 *   = green, failed = red, canceled = muted.
 *
 * SCAFFOLD NOTE: the canonical score band cut-points are Team-E/Team-F's
 * (docs/platform/benchmark/scoring-and-trends.md). They are inlined here to match
 * report-views.md §4; when that module exports them, import rather than re-copy.
 */

type Tint = "green" | "orange" | "red" | "muted";

const TINT_CLASS: Record<Tint, string> = {
  red: "border-rogue-red/40 bg-rogue-red/10 text-rogue-red",
  orange: "border-orange-500/40 bg-orange-500/10 text-orange-300",
  green: "border-rogue-green/40 bg-rogue-green/10 text-rogue-green",
  muted: "border-border bg-card/30 text-muted-foreground",
};

function scoreTint(score: number): Tint {
  if (score >= 70) return "red";
  if (score >= 40) return "orange";
  return "green";
}

export function ScoreBadge({
  score,
  className = "",
}: {
  score: number | null | undefined;
  className?: string;
}) {
  if (score === null || score === undefined) {
    return (
      <span
        className={`inline-flex items-center rounded-md border px-2 py-0.5 font-mono text-xs tabular-nums ${TINT_CLASS.muted} ${className}`}
        title="No score yet (scan not completed)"
      >
        —
      </span>
    );
  }
  const tint = scoreTint(score);
  return (
    <span
      className={`inline-flex items-center rounded-md border px-2 py-0.5 font-mono text-xs font-bold tabular-nums ${TINT_CLASS[tint]} ${className}`}
      title={`Risk score ${Math.round(score)}/100`}
    >
      {Math.round(score)}
    </span>
  );
}

const STATUS_TINT: Record<ScanStatus, Tint> = {
  queued: "muted",
  running: "green",
  completed: "green",
  failed: "red",
  canceled: "muted",
};

export function StatusBadge({
  status,
  className = "",
}: {
  status: ScanStatus;
  className?: string;
}) {
  const tint = STATUS_TINT[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.15em] ${TINT_CLASS[tint]} ${className}`}
    >
      {status === "running" && (
        <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-rogue-green" />
      )}
      {status}
    </span>
  );
}
