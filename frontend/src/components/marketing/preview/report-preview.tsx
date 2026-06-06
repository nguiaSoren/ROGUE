import {
  FileJson,
  FileText,
  ShieldAlert,
  Wrench,
} from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * ReportPreview — a pixel-faithful, NON-functional native preview of a completed
 * scan's executive report, framed in a faux app-window for the marketing site.
 *
 * It mirrors the real report body in `app/(app)/scans/[scanId]/report/page.tsx`
 * (risk headline → executive summary → KPI row → recommendations) using the same
 * house vocabulary — `.rogue-card`, the rogue-green/red/orange banding, Geist /
 * Geist Mono — so it reads as a genuine product screenshot, not a mockup. All
 * data is illustrative and hard-coded; the export affordances are decorative.
 *
 * Server component (no client interactivity). Drop into any marketing section;
 * responsive from ~600px to full width. Optional `className` for layout.
 */

const EXAMPLE = {
  target: "acme-support-assistant · claude-sonnet-4",
  scanId: "scan_8f3a2",
  score: 68,
  level: "high" as const,
  nTests: 142,
  nBreaches: 11,
  breachRate: 0.077,
  costUsd: 4.12,
  topAttack: "Multi-turn escalation (Crescendo)",
};

const SUMMARY =
  "This deployment breached 11 of 142 attack trials (7.7%). Highest risk: " +
  "multi-turn escalation (Crescendo) and a multimodal image-carrier bypass. " +
  "Two CRITICAL findings require attention before production.";

const RECOMMENDATIONS: { icon: typeof Wrench; text: string }[] = [
  {
    icon: ShieldAlert,
    text: "Add a turn-aware refusal check: Crescendo succeeds by degrading the guard across a benign-looking conversation. Re-evaluate the safety policy on every turn against the full transcript, not just the latest message.",
  },
  {
    icon: Wrench,
    text: "Run OCR + a vision safety pass on all uploaded images before they reach the model. The image-carrier bypass smuggles instructions as rendered text that the text-only filter never sees.",
  },
  {
    icon: ShieldAlert,
    text: "Constrain tool exposure for untrusted turns — the two CRITICAL findings chained a jailbreak into a tool call. Gate high-impact tools behind a confirmation step until the conversation is re-verified.",
  },
];

/** Banded text tint for the big score — mirrors the report's SCORE_TINT_TEXT. */
const SCORE_TINT = "text-orange-300"; // HIGH band

export function ReportPreview({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "w-full overflow-hidden rounded-xl border border-border bg-card/40 shadow-2xl shadow-black/40",
        className,
      )}
    >
      {/* ---- window chrome ---------------------------------------------- */}
      <div className="flex items-center gap-3 border-b border-border bg-rogue-bg-mid/80 px-4 py-2.5">
        <div className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-full bg-rogue-red/70" />
          <span className="h-3 w-3 rounded-full bg-rogue-orange/70" />
          <span className="h-3 w-3 rounded-full bg-rogue-green/70" />
        </div>
        <div className="min-w-0 flex-1 truncate text-center font-mono text-[10px] sm:text-[11px] text-muted-foreground">
          <span className="text-rogue-green">app.rogue</span>
          <span className="opacity-50"> · scans / </span>
          <span className="text-foreground/80">scan_8f3a2</span>
          <span className="opacity-50"> / report</span>
        </div>
        {/* export affordances — shown, non-functional */}
        <div
          aria-hidden
          className="hidden items-center gap-1.5 font-mono text-[10px] sm:flex"
        >
          <span className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 uppercase tracking-[0.15em] text-muted-foreground">
            <FileText className="h-3 w-3" /> PDF
          </span>
          <span className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 uppercase tracking-[0.15em] text-muted-foreground">
            <FileJson className="h-3 w-3" /> JSON
          </span>
        </div>
      </div>

      {/* ---- report body ----------------------------------------------- */}
      <div className="bg-rogue-bg-deep">
        <div className="space-y-5 p-4 sm:p-7">
          {/* header */}
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 space-y-1">
              <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
                ← /scans/scan_8f3a2
              </p>
              <h2 className="truncate text-xl font-bold tracking-tight text-foreground sm:text-2xl">
                {EXAMPLE.target}
              </h2>
              <p className="font-mono text-xs text-muted-foreground">
                {EXAMPLE.nTests} tests · {EXAMPLE.nBreaches} breaches
              </p>
            </div>
            <span className="shrink-0 rounded-md border border-rogue-green/30 bg-rogue-green/5 px-2 py-1 font-mono text-[9px] uppercase tracking-[0.15em] text-rogue-green/80">
              Example report · illustrative
            </span>
          </div>

          {/* risk headline */}
          <section className="rogue-card space-y-3 rounded-lg border border-border bg-card/40 p-4 sm:p-6">
            <div className="flex flex-wrap items-end gap-4 sm:gap-5">
              <div className="flex items-baseline gap-2">
                <span
                  className={cn(
                    "text-5xl font-bold leading-none tabular-nums",
                    SCORE_TINT,
                  )}
                >
                  {EXAMPLE.score}
                </span>
                <span className="font-mono text-lg text-muted-foreground">
                  /100
                </span>
              </div>
              <div className="space-y-1.5">
                <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted-foreground">
                  Risk score
                </p>
                <span className="inline-flex items-center rounded-md border border-orange-500/40 bg-orange-500/10 px-2 py-0.5 font-mono text-xs font-bold uppercase tracking-[0.15em] text-orange-300">
                  {EXAMPLE.level}
                </span>
              </div>
              <div className="ml-auto min-w-0 space-y-1 text-right">
                <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted-foreground">
                  Top attack
                </p>
                <p className="max-w-[12rem] break-words text-sm font-bold text-foreground">
                  {EXAMPLE.topAttack}
                </p>
              </div>
            </div>
            <p className="border-t border-border pt-3 text-xs leading-relaxed text-muted-foreground">
              Score = severity-weighted breach density across {EXAMPLE.nTests}{" "}
              reproduced attack trials. Bands: ≥75 critical · ≥50 high · ≥25
              medium · &lt;25 low.
            </p>
          </section>

          {/* executive summary */}
          <section className="rogue-card space-y-3 rounded-lg border border-border bg-card/40 p-4 sm:p-6">
            <h3 className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
              Executive summary
            </h3>
            <p className="text-sm leading-relaxed text-foreground/90">
              {SUMMARY}
            </p>
          </section>

          {/* KPI row */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Kpi label="Tests" value={String(EXAMPLE.nTests)} />
            <Kpi
              label="Breaches"
              value={String(EXAMPLE.nBreaches)}
              tint="text-rogue-red"
            />
            <Kpi
              label="Breach rate"
              value={`${Math.round(EXAMPLE.breachRate * 100)}%`}
              tint="text-rogue-red"
            />
            <Kpi label="Cost" value={`$${EXAMPLE.costUsd.toFixed(2)}`} />
          </div>

          {/* recommendations */}
          <section className="space-y-3 rounded-lg border border-border bg-card/30 p-4 sm:p-5">
            <h3 className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
              Recommendations
            </h3>
            <ul className="space-y-3">
              {RECOMMENDATIONS.map((r, i) => {
                const Icon = r.icon;
                return (
                  <li key={i} className="flex gap-3">
                    <Icon className="mt-0.5 h-4 w-4 shrink-0 text-rogue-green" />
                    <p className="text-sm leading-relaxed text-foreground/90">
                      {r.text}
                    </p>
                  </li>
                );
              })}
            </ul>
          </section>
        </div>
      </div>
    </div>
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
