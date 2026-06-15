import { api, BriefJson, API_CONFIGURED } from "@/lib/api";
import { BriefMarkdown } from "@/components/brief-markdown";
import { BriefExecSnapshot } from "@/components/brief-exec-snapshot";
import { BriefDownloads } from "@/components/brief-downloads";

// ISR, statically prerendered + revalidated every 5 min, matching /matrix and
// REVALIDATE_SECONDS in lib/api.ts, so visitors get instant loads and new Neon
// data surfaces within the window instead of paying the full round-trip.
// "auto" = ISR on Vercel; the self-host docker build rewrites it to "force-dynamic" (docker/frontend.Dockerfile).
export const dynamic = "auto";
export const revalidate = 300;

/**
 * Rendered only in preview/local builds where no API base is configured (NEXT_PUBLIC_API_BASE is
 * Production-only), so the build-time brief fetch cannot reach the API. This lets the Vercel
 * preview build succeed instead of failing on a prerender ECONNREFUSED; production always has the
 * API base set and renders the real brief.
 */
function BriefUnavailable() {
  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-20 text-center space-y-3">
        <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-rogue-green">
          daily threat brief
        </p>
        <h1 className="text-3xl font-bold tracking-tight">Threat Brief</h1>
        <p className="text-sm text-muted-foreground max-w-md mx-auto">
          This preview build has no API connection; the live brief renders in production.
        </p>
      </div>
    </main>
  );
}

/**
 * /brief default export — ONE try/catch around the whole render so no prerender-time fetch
 * failure can fail the build. Production (NEXT_PUBLIC_API_BASE set): a real failure rethrows, so
 * Vercel keeps the last-good static brief and never caches a broken one. Preview/local (no API
 * base — the var is Production-scoped, so it's unset in previews): the build-time fetch can't
 * reach the API, so we degrade to a placeholder and the preview build still succeeds.
 */
export default async function BriefPage() {
  try {
    return await renderBrief();
  } catch (err) {
    if (API_CONFIGURED) throw err;
    return <BriefUnavailable />;
  }
}

/**
 * /brief, Threat Brief.
 *
 * Reads like a daily CISO threat brief: a dated masthead with export actions,
 * an at-a-glance KPI snapshot strip (new breaches by severity + net movement),
 * the JSON-driven executive snapshot, then the full long-form markdown report
 * in a branded reading container.
 *
 * We fetch BOTH the JSON and markdown forms in parallel. The JSON feeds the
 * snapshot + KPI strip, the markdown feeds the long-form report below. They
 * come from the same disk artifact so values cannot disagree.
 */
async function renderBrief() {
  // The markdown brief is the critical fetch. Any failure (API mid-restart / cold Neon / no API
  // base in a preview build) propagates to BriefPage's try/catch above, which rethrows in
  // production and degrades in preview. The JSON form (exec snapshot) is non-critical.
  const [briefMarkdown, briefJsonRes] = await Promise.all([
    api.brief(undefined, "markdown"),
    api.brief(undefined, "json").catch(() => null),
  ]);
  const briefJson = (briefJsonRes?.json ?? null) as BriefJson | null;

  // Successful fetch but no markdown payload is an anomaly (the brief is always generable from the
  // matrix) — throw so the wrapper keeps the last-good brief rather than caching an empty one.
  if (!briefMarkdown?.markdown) {
    throw new Error("brief markdown payload empty");
  }

  const summary = briefJson?.summary;

  // KPI strip values: prefer the JSON summary, fall back to scraping the markdown
  // so the strip is still populated on days the JSON form failed to fetch.
  const newCritical = summary?.new_critical ?? extractCount(briefMarkdown.markdown, "CRITICAL");
  const newHigh = summary?.new_high ?? extractCount(briefMarkdown.markdown, "HIGH");
  const newMedium = summary?.new_medium ?? extractCount(briefMarkdown.markdown, "MEDIUM");
  const newLow = summary?.new_low ?? extractCount(briefMarkdown.markdown, "LOW");
  const newlyDefended = summary?.newly_defended ?? 0;
  const newBreaching = newCritical + newHigh + newMedium + newLow;
  const netDelta = summary?.net_delta ?? newBreaching - newlyDefended;

  // One-line masthead summary, the "read it in 3 seconds" headline.
  const headline = buildHeadline({
    newCritical,
    newHigh,
    newBreaching,
    newlyDefended,
  });

  // Human-friendly long date for the masthead (falls back to the raw date).
  const longDate = formatLongDate(briefMarkdown.target_date);

  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-10 space-y-8">
        {/* Masthead */}
        <header className="rogue-card border border-border rounded-xl bg-card/40 backdrop-blur-sm p-6 md:p-8 animate-rogue-fade-up">
          <div className="flex items-start justify-between gap-6 flex-wrap">
            <div className="space-y-3 min-w-0">
              <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-rogue-green flex items-center gap-2">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-rogue-green animate-rogue-pulse-green" />
                daily threat brief
              </p>
              <div className="space-y-1">
                <h1 className="text-3xl sm:text-4xl font-bold tracking-tight">Threat Brief</h1>
                <p className="font-mono text-xs text-muted-foreground uppercase tracking-[0.18em]">
                  {longDate}
                </p>
              </div>
              <p className="text-sm text-foreground/90 leading-relaxed max-w-xl">
                {headline}
              </p>
              <p className="text-xs text-muted-foreground">
                {briefMarkdown.from_disk
                  ? "Daily snapshot · regenerable from the breach matrix on demand."
                  : "Rendered live from today's breach matrix (no disk snapshot yet)."}
              </p>
            </div>
            <BriefDownloads
              date={briefMarkdown.target_date}
              markdown={briefMarkdown.markdown}
              json={briefJson}
            />
          </div>
        </header>

        {/* At-a-glance KPI snapshot strip */}
        <section
          className="space-y-3 animate-rogue-fade-up"
          style={{ animationDelay: "0.1s" }}
        >
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
            at a glance · vs yesterday
          </p>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <KpiCard
              label="Newly breaching"
              value={newBreaching}
              sub="new attacks bypassing guardrails"
              tint={newBreaching > 0 ? "red" : "green"}
              highlight={newBreaching > 0}
            />
            <KpiCard
              label="New CRITICAL"
              value={newCritical}
              sub="highest-severity tier"
              tint={newCritical > 0 ? "red" : "green"}
              highlight={newCritical > 0}
            />
            <KpiCard
              label="Newly defended"
              value={newlyDefended}
              sub="attacks now refused"
              tint="green"
            />
            <KpiCard
              label="Net Δ"
              value={netDelta}
              signed
              sub="movement vs yesterday"
              tint={netDelta > 0 ? "red" : netDelta < 0 ? "green" : "neutral"}
            />
          </div>

          {/* Per-tier breakdown chips */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <TierChip label="CRITICAL" count={newCritical} tint="red" />
            <TierChip label="HIGH" count={newHigh} tint="orange" />
            <TierChip label="MEDIUM" count={newMedium} tint="yellow" />
            <TierChip label="LOW" count={newLow} tint="blue" />
          </div>
        </section>

        {/* Executive snapshot, JSON-driven (net Δ, top-3 attackers, action) */}
        <BriefExecSnapshot json={briefJson} />

        {/* Full long-form report */}
        <section
          className="space-y-3 animate-rogue-fade-up"
          style={{ animationDelay: "0.35s" }}
        >
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
            full report
          </p>
          <article className="border border-border rounded-xl p-6 md:p-10 bg-card/40 backdrop-blur-sm">
            <div className="max-w-prose mx-auto">
              <BriefMarkdown source={briefMarkdown.markdown} />
            </div>
          </article>
        </section>
      </div>
    </main>
  );
}

// ---------------------------------------------------------------------------

function KpiCard({
  label,
  value,
  sub,
  tint,
  signed = false,
  highlight = false,
}: {
  label: string;
  value: number;
  sub: string;
  tint: "red" | "green" | "neutral";
  signed?: boolean;
  highlight?: boolean;
}) {
  const tintClass =
    tint === "red"
      ? "text-rogue-red"
      : tint === "green"
        ? "text-rogue-green"
        : "text-muted-foreground";
  const cardClass = highlight
    ? "rogue-card rogue-card-critical animate-rogue-pulse-critical"
    : "rogue-card";
  const display = signed && value > 0 ? `+${value}` : String(value);
  return (
    <div
      className={`${cardClass} border border-border rounded-lg p-4 bg-card/40 backdrop-blur-sm`}
    >
      <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground">
        {label}
      </p>
      <p className={`text-3xl font-bold mt-2 tabular-nums ${tintClass}`}>{display}</p>
      <p className="text-xs text-muted-foreground mt-1">{sub}</p>
    </div>
  );
}

function TierChip({
  label,
  count,
  tint,
}: {
  label: string;
  count: number;
  tint: "red" | "orange" | "yellow" | "blue";
}) {
  const tintClass = {
    red: "border-rogue-red/40 bg-rogue-red/10 text-rogue-red",
    orange: "border-orange-500/40 bg-orange-500/10 text-orange-300",
    yellow: "border-yellow-500/40 bg-yellow-500/10 text-yellow-300",
    blue: "border-blue-500/40 bg-blue-500/10 text-blue-300",
  }[tint];
  const pulseClass = tint === "red" && count > 0 ? "animate-rogue-pulse-critical" : "";

  return (
    <div className={`rogue-card border rounded-md px-4 py-3 ${tintClass} ${pulseClass} font-mono`}>
      <p className="text-[10px] uppercase tracking-[0.2em] opacity-80">{label}</p>
      <p className="text-2xl font-bold mt-1 tabular-nums">{count}</p>
    </div>
  );
}

/** A one-line CISO-style summary for the masthead. */
function buildHeadline({
  newCritical,
  newHigh,
  newBreaching,
  newlyDefended,
}: {
  newCritical: number;
  newHigh: number;
  newBreaching: number;
  newlyDefended: number;
}): string {
  if (newCritical > 0) {
    return `${newCritical} new CRITICAL attack${newCritical === 1 ? "" : "s"} bypassed guardrails since yesterday, patch system prompts now.`;
  }
  if (newHigh > 0) {
    return `${newHigh} new HIGH-tier attack${newHigh === 1 ? "" : "s"} surfaced, review and prioritize for the next patch window.`;
  }
  if (newBreaching > 0) {
    return `${newBreaching} newly-breaching attack${newBreaching === 1 ? "" : "s"} since yesterday, none critical.`;
  }
  if (newlyDefended > 0) {
    return `No new breaches today, ${newlyDefended} previously-breaching attack${newlyDefended === 1 ? "" : "s"} now defended.`;
  }
  return "Steady state, no critical movers since yesterday. Continue daily polling cadence.";
}

/** "2026-06-05" → "Friday, June 5, 2026"; passes through anything unparseable. */
function formatLongDate(date: string): string {
  const d = new Date(`${date}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return date;
  return d.toLocaleDateString("en-US", {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  });
}

function extractCount(md: string, tier: string): number {
  const re = new RegExp(`\\*\\*(\\d+)\\*\\*\\s+new\\s+${tier}\\s+attacks`, "i");
  const m = md.match(re);
  return m ? Number(m[1]) : 0;
}
