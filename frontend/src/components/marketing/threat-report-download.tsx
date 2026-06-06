import Link from "next/link";

import { cn } from "@/lib/utils";

/**
 * Threat-intel CTA block. Server component — no interactivity.
 *
 * Points at the two real artifacts ROGUE produces: the daily threat-brief page
 * (`/brief`) and a static sample scan report (`/sample-report.html`). Deliberately
 * not a gated PDF — these are the genuine outputs, so the CTA is honest.
 */
export function ThreatReportDownload({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "rogue-card border border-border rounded-xl p-6 bg-card/40",
        className,
      )}
    >
      <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-rogue-green">
        threat intel
      </p>
      <h2 className="mt-3 text-2xl font-bold tracking-tight">
        Download the latest threat brief
      </h2>
      <p className="mt-3 text-sm text-muted-foreground leading-relaxed">
        See what ROGUE found this cycle — new jailbreaks reproduced against real
        deployments, plus a full sample scan report.
      </p>

      <div className="mt-6 flex flex-col gap-3 sm:flex-row">
        <Link
          href="/brief"
          className={cn(
            "inline-flex items-center justify-center rounded-lg px-6 py-2.5",
            "bg-rogue-green text-[#050508] font-mono text-sm font-bold tracking-[0.15em] uppercase",
            "transition-opacity hover:opacity-90",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rogue-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background",
          )}
        >
          Read the threat brief
        </Link>
        <a
          href="/sample-report.html"
          target="_blank"
          rel="noopener noreferrer"
          className={cn(
            "inline-flex items-center justify-center rounded-lg border border-border px-6 py-2.5",
            "font-mono text-sm font-semibold tracking-[0.15em] uppercase text-foreground",
            "transition-colors hover:border-rogue-green hover:text-rogue-green",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rogue-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background",
          )}
        >
          See a sample scan report
        </a>
      </div>
    </div>
  );
}
