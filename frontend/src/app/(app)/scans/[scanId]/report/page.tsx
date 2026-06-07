import Link from "next/link";
import { redirect } from "next/navigation";
import {
  platformApi,
  type ScanReportJson,
  type Finding,
} from "@/lib/platform-api";
import { getApiKey } from "@/lib/session";
import { ReportSummaryMarkdown } from "@/components/report-summary-markdown";

/** Same-origin export proxy, the bearer is attached server-side by the route
 *  handler, never placed in a client href (see app/api/scans/[scanId]/report). */
function exportHref(scanId: string, format: "json" | "html" | "pdf"): string {
  return `/api/scans/${encodeURIComponent(scanId)}/report?format=${format}`;
}

/**
 * /scans/{scanId}/report, a completed scan's report (server component).
 *
 * "The brief page for one scan" (docs/platform/dashboard/report-views.md §1):
 * headline KPIs (score, breach rate, top attack, cost), a worst-first findings
 * table, per-finding attack/response detail, and JSON/HTML/PDF export links.
 * Reads `GET /v1/scans/{id}/report?format=json`, the persisted `ScanReport.to_dict()`
 * (src/rogue/report.py:130) PLUS the platform `score` and `recommendations[]`
 * (report-views.md §2). The page never recomputes a rate, they arrive pre-derived.
 *
 * Auth: `(app)/layout.tsx` gates the session; we re-read the key here (server-only)
 * for the report fetch. The json/html/pdf export links point at the same-origin
 * `/api/scans/{id}/report` proxy, which attaches the bearer server-side, never a
 * secret in a client href. A `report_not_ready`/404 means the scan isn't completed
 * yet; we surface that as "not ready" rather than a hard error.
 */
export const dynamic = "force-dynamic"; // tenant data, never statically cached

const SEVERITY_CLASS: Record<Finding["severity"], string> = {
  critical: "border-rogue-red/40 bg-rogue-red/10 text-rogue-red",
  high: "border-orange-500/40 bg-orange-500/10 text-orange-300",
  medium: "border-yellow-500/40 bg-yellow-500/10 text-yellow-300",
  low: "border-blue-500/40 bg-blue-500/10 text-blue-300",
};

export default async function ReportPage({
  params,
}: {
  params: Promise<{ scanId: string }>;
}) {
  const { scanId } = await params;

  const key = await getApiKey();
  if (!key) redirect("/sign-in");

  let report: ScanReportJson | null = null;
  let loadError: string | null = null;
  let notReady = false;
  try {
    report = await platformApi.getReport(scanId, key, "json");
  } catch (e) {
    // The report route 404s with `report_not_ready` while the scan is still
    // queued/running, treat that as "not yet", not a failure (report-views.md §6).
    const msg = e instanceof Error ? e.message : "Failed to load report.";
    if (/not[_ ]?ready|404/i.test(msg)) notReady = true;
    else loadError = msg;
  }

  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-10 space-y-8">
        <header className="flex items-start justify-between gap-4 sm:gap-6 flex-wrap animate-rogue-fade-up">
          <div className="space-y-2 min-w-0">
            <Link
              href={`/scans/${encodeURIComponent(scanId)}`}
              className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green hover:underline"
            >
              ← /scans/{scanId}
            </Link>
            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight break-words">
              {report ? report.target : "Scan report"}
            </h1>
            {report && (
              <p className="text-sm text-muted-foreground font-mono">
                {report.n_tests} tests · {report.n_breaches} breaches
              </p>
            )}
          </div>

          {report && (
            <div className="flex items-center gap-2 font-mono text-xs">
              <a
                href={exportHref(scanId, "html")}
                target="_blank"
                rel="noreferrer"
                className="uppercase tracking-[0.15em] border border-border rounded-md px-3 py-1.5 hover:bg-card/40 transition-colors"
              >
                HTML
              </a>
              <a
                href={exportHref(scanId, "pdf")}
                className="uppercase tracking-[0.15em] border border-border rounded-md px-3 py-1.5 hover:bg-card/40 transition-colors"
              >
                PDF
              </a>
              <a
                href={exportHref(scanId, "json")}
                className="uppercase tracking-[0.15em] border border-border rounded-md px-3 py-1.5 hover:bg-card/40 transition-colors"
              >
                JSON
              </a>
            </div>
          )}
        </header>

        {loadError ? (
          <div className="rounded-lg border border-rogue-red/40 bg-rogue-red/10 p-6 font-mono text-sm text-rogue-red">
            <p className="font-bold">Couldn&apos;t load report</p>
            <p className="mt-1 text-xs opacity-80">{loadError}</p>
          </div>
        ) : notReady ? (
          <div className="rounded-lg border border-border p-6 font-mono text-sm text-muted-foreground">
            <p>Report not ready, this scan hasn&apos;t completed yet.</p>
            <Link
              href={`/scans/${encodeURIComponent(scanId)}`}
              className="mt-3 inline-flex text-xs uppercase tracking-[0.15em] text-rogue-green hover:underline"
            >
              ← watch scan progress
            </Link>
          </div>
        ) : report ? (
          <ReportBody report={report} />
        ) : null}
      </div>
    </main>
  );
}

function ReportBody({ report }: { report: ScanReportJson }) {
  const breached = report.findings
    .filter((f) => f.n_breach > 0)
    .sort(
      (a, b) =>
        severityRank(b.severity) - severityRank(a.severity) ||
        b.success_rate - a.success_rate,
    );

  return (
    <>
      {/* Headline, the risk score leads the report (report-views.md §1). */}
      <RiskHeadline report={report} />

      {/* Executive summary, the "forward-to-your-boss" overview, right under the
          headline so it's the first thing read after the score. */}
      <ExecutiveSummary report={report} />

      {/* KPI row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Kpi label="Tests">
          <span className="text-2xl font-bold tabular-nums">
            {report.n_tests}
          </span>
        </Kpi>
        <Kpi label="Breaches">
          <span
            className={`text-2xl font-bold tabular-nums ${
              report.n_breaches > 0 ? "text-rogue-red" : "text-rogue-green"
            }`}
          >
            {report.n_breaches}
          </span>
        </Kpi>
        <Kpi label="Breach rate">
          <span
            className={`text-2xl font-bold tabular-nums ${
              report.breach_rate > 0 ? "text-rogue-red" : "text-rogue-green"
            }`}
          >
            {Math.round(report.breach_rate * 100)}%
          </span>
        </Kpi>
        <Kpi label="Cost">
          <span className="text-2xl font-bold tabular-nums">
            {formatUsd(report.cost_usd)}
          </span>
        </Kpi>
      </div>

      {/* Findings */}
      {breached.length === 0 ? (
        <div className="rounded-lg border border-rogue-green/40 bg-rogue-green/10 p-6 text-center font-mono text-sm text-rogue-green">
          No vulnerabilities reproduced across {report.n_tests} tests.
        </div>
      ) : (
        <section className="space-y-3">
          <h2 className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
            Findings ({breached.length})
          </h2>
          {breached.map((f, i) => (
            <FindingCard key={`${f.family}-${f.technique}-${i}`} f={f} rank={i + 1} />
          ))}
        </section>
      )}

      {/* Recommendations */}
      <RecommendationsPanel report={report} breachedCount={breached.length} />
    </>
  );
}

/** Big, color-banded risk headline: score/100 + risk_level pill + methodology caption.
 *  `risk_level` arrives from the report route; on older runs it's absent, so we derive
 *  it from `score` with the same cut-points as `scoring.risk_level`. */
function RiskHeadline({ report }: { report: ScanReportJson }) {
  const score = report.score ?? null;
  const level = report.risk_level ?? deriveRiskLevel(score);
  const tint = level ? SCORE_TINT_TEXT[level] : "text-muted-foreground";
  const topAttack = report.top_attack ?? null;
  return (
    <section className="rogue-card p-6 sm:p-7 space-y-3 animate-rogue-fade-up">
      <div className="flex items-end gap-5 flex-wrap">
        <div className="flex items-baseline gap-2">
          <span className={`text-5xl font-bold tabular-nums leading-none ${tint}`}>
            {score === null ? ", " : Math.round(score)}
          </span>
          <span className="text-lg font-mono text-muted-foreground">/100</span>
        </div>
        <div className="space-y-1.5">
          <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted-foreground">
            Risk score
          </p>
          {level ? (
            <SeverityBadge severity={level} className="text-xs" />
          ) : (
            <span className="font-mono text-xs text-muted-foreground">
              not scored
            </span>
          )}
        </div>
        {topAttack && (
          <div className="ml-auto text-right space-y-1">
            <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted-foreground">
              Top attack
            </p>
            <p className="text-sm font-bold break-words max-w-xs">{topAttack}</p>
          </div>
        )}
      </div>
      {report.score_methodology && (
        <p className="text-xs text-muted-foreground leading-relaxed border-t border-border pt-3">
          {report.score_methodology}
        </p>
      )}
    </section>
  );
}

/** Executive summary, the markdown overview a customer forwards to leadership.
 *  Rendered prominently below the headline; degrades to nothing on older runs
 *  (or when the report route didn't supply one). */
function ExecutiveSummary({ report }: { report: ScanReportJson }) {
  const summary = report.executive_summary?.trim();
  if (!summary) return null;
  return (
    <section className="rogue-card p-6 sm:p-7 space-y-3 animate-rogue-fade-up">
      <h2 className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
        Executive summary
      </h2>
      <ReportSummaryMarkdown source={summary} />
    </section>
  );
}

/** Severity pill, reuses the page's `SEVERITY_CLASS` color vocabulary. */
function SeverityBadge({
  severity,
  className = "",
}: {
  severity: Finding["severity"];
  className?: string;
}) {
  const sev = SEVERITY_CLASS[severity] ?? SEVERITY_CLASS.low;
  return (
    <span
      className={`inline-flex items-center rounded-md border px-2 py-0.5 font-mono uppercase tracking-[0.15em] font-bold ${sev} ${className}`}
    >
      {severity}
    </span>
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

function FindingCard({ f, rank }: { f: Finding; rank: number }) {
  const sev = SEVERITY_CLASS[f.severity] ?? SEVERITY_CLASS.low;
  const rateClass =
    f.success_rate >= 0.7
      ? "text-rogue-red"
      : f.success_rate >= 0.3
        ? "text-orange-300"
        : "text-rogue-green";
  return (
    <article className={`rounded-lg border p-5 space-y-3 ${sev}`}>
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-mono text-[10px] uppercase tracking-[0.2em] opacity-70">
            #{rank}
          </span>
          <SeverityBadge severity={f.severity} className="text-[10px]" />
          <span className="font-mono text-[10px] uppercase tracking-[0.2em] opacity-70">
            {f.vector}
          </span>
        </div>
        <p className={`font-mono text-sm font-bold tabular-nums ${rateClass}`}>
          breached {f.n_breach}/{f.n_trials} trials ·{" "}
          {Math.round(f.success_rate * 100)}%
        </p>
      </div>
      <h3 className="text-base font-bold text-foreground leading-tight break-words">
        {f.title}
      </h3>
      <p className="font-mono text-xs text-muted-foreground">
        {f.family} · {f.technique}
      </p>

      {/* What this is, plain-language framing so a non-expert grasps the risk,
          shown above the fix and the evidence. */}
      {f.explanation && (
        <div className="rounded-md border border-border/60 bg-card/20 p-3">
          <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-1">
            What this is
          </p>
          <p className="text-sm leading-relaxed text-foreground/90 whitespace-pre-wrap break-words">
            {f.explanation}
          </p>
        </div>
      )}

      {/* How to fix, actionable remediation, visually distinct from the
          explanation (green accent = the "do this" block). */}
      {f.remediation && (
        <div className="rounded-md border border-rogue-green/40 bg-rogue-green/5 p-3">
          <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-rogue-green mb-1">
            How to fix
          </p>
          <p className="text-sm leading-relaxed text-foreground/90 whitespace-pre-wrap break-words">
            {f.remediation}
          </p>
        </div>
      )}

      {/* Evidence, proof of the breach: the attack sent and the model's
          response, framed as a transcript with the breach state flagged. */}
      <FindingEvidence f={f} />
    </article>
  );
}

/** Evidence block, "Attack sent → Model response" as proof. Collapsible; the
 *  summary flags that this finding was breached so the evidence reads as a
 *  confirmed compromise, not a benign sample. */
function FindingEvidence({ f }: { f: Finding }) {
  if (!f.example_attack && !f.example_response) return null;
  const breached = f.n_breach > 0;
  return (
    <details className="group rounded-md border border-border/60 bg-card/20">
      <summary className="cursor-pointer list-none flex items-center justify-between gap-3 px-3 py-2 font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground hover:text-foreground">
        <span className="flex items-center gap-2">
          <span className="transition-transform group-open:rotate-90">›</span>
          Evidence, attack &amp; model response
        </span>
        {breached && (
          <span className="inline-flex items-center rounded-sm border border-rogue-red/40 bg-rogue-red/10 px-1.5 py-0.5 font-bold text-rogue-red">
            breached
          </span>
        )}
      </summary>
      <div className="space-y-3 border-t border-border/60 p-3">
        {f.example_attack && (
          <div className="space-y-1">
            <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-orange-300">
              Attack sent →
            </p>
            <pre className="overflow-x-auto rounded-md border border-border bg-card/60 p-3 text-xs text-foreground whitespace-pre-wrap break-words">
              {f.example_attack}
            </pre>
          </div>
        )}
        {f.example_response && (
          <div className="space-y-1">
            <p
              className={`font-mono text-[10px] uppercase tracking-[0.15em] ${
                breached ? "text-rogue-red" : "text-muted-foreground"
              }`}
            >
              Model response
            </p>
            <div
              className={`rounded-md border-l-2 pl-3 py-2 text-xs whitespace-pre-wrap break-words ${
                breached
                  ? "border-rogue-red/60 bg-rogue-red/5 text-foreground/90"
                  : "border-border text-muted-foreground"
              }`}
            >
              {f.example_response}
            </div>
          </div>
        )}
      </div>
    </details>
  );
}

function RecommendationsPanel({
  report,
  breachedCount,
}: {
  report: ScanReportJson;
  breachedCount: number;
}) {
  const recs = report.recommendations ?? [];
  const fallback =
    breachedCount > 0
      ? `${breachedCount} finding${breachedCount === 1 ? "" : "s"} reproduced, prioritize the top attack (${report.top_attack ?? "n/a"}).`
      : "No vulnerabilities reproduced, keep monitoring as the threat corpus grows.";
  return (
    <section className="rounded-lg border border-border bg-card/30 p-5 space-y-2">
      <h2 className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
        Recommendations
      </h2>
      {recs.length > 0 ? (
        <ul className="list-disc pl-5 space-y-1 text-sm text-foreground">
          {recs.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">{fallback}</p>
      )}
    </section>
  );
}

const _SEVERITY_RANK: Record<string, number> = {
  critical: 3,
  high: 2,
  medium: 1,
  low: 0,
};
function severityRank(s: string): number {
  return _SEVERITY_RANK[s] ?? 0;
}

/** Big-number text tint per banded risk level (matches the matrix/brief vocabulary). */
const SCORE_TINT_TEXT: Record<Finding["severity"], string> = {
  critical: "text-rogue-red",
  high: "text-orange-300",
  medium: "text-yellow-300",
  low: "text-rogue-green",
};

/** Derive the banded level from `score` when the report route didn't supply
 *  `risk_level` (older runs). Cut-points mirror `scoring.risk_level`
 *  (src/rogue/platform/scoring.py): ≥75 critical, ≥50 high, ≥25 medium, else low. */
function deriveRiskLevel(score: number | null): Finding["severity"] | null {
  if (score === null) return null;
  if (score >= 75) return "critical";
  if (score >= 50) return "high";
  if (score >= 25) return "medium";
  return "low";
}

/** Mirrors `_fmt_usd` (src/rogue/report.py:37). */
function formatUsd(x: number): string {
  if (x >= 0.01) return `$${x.toFixed(2)}`;
  if (x > 0) return `$${x.toFixed(4)}`;
  return "$0.00";
}
