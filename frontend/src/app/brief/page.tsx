import { api, BriefJson } from "@/lib/api";
import { BriefMarkdown } from "@/components/brief-markdown";
import { BriefExecSnapshot } from "@/components/brief-exec-snapshot";
import { BriefDownloads } from "@/components/brief-downloads";

/**
 * /brief — Threat Brief.
 *
 * Top of the page: an executive-snapshot panel (net Δ vs yesterday, top-3
 * worst new attackers, a "recommended action" line). Then tier chips, then
 * the full markdown brief.
 *
 * We fetch BOTH the JSON and markdown forms in parallel. The JSON feeds the
 * snapshot, the markdown feeds the long-form report below. They come from
 * the same disk artifact so values cannot disagree.
 */
export default async function BriefPage() {
  // The markdown brief is the critical fetch — do NOT swallow its failure. If it
  // throws (API mid-restart / cold Neon), let it propagate so Next + Vercel keep
  // serving the last-good static brief instead of caching a "brief unavailable"
  // page for the full ISR window. The JSON form (exec snapshot) is non-critical.
  const [briefMarkdown, briefJsonRes] = await Promise.all([
    api.brief(undefined, "markdown"),
    api.brief(undefined, "json").catch(() => null),
  ]);
  const briefJson = (briefJsonRes?.json ?? null) as BriefJson | null;

  // Successful fetch but no markdown payload is an anomaly (the brief is always
  // generable from the matrix) — throw so we keep the last-good brief rather
  // than caching an empty one.
  if (!briefMarkdown?.markdown) {
    throw new Error("brief markdown payload empty");
  }

  const summary = briefJson?.summary;

  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-5xl mx-auto px-6 py-10 space-y-8">
        <header className="flex items-start justify-between gap-6 flex-wrap animate-rogue-fade-up">
          <div className="space-y-2">
            <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green flex items-center gap-2">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-rogue-green animate-rogue-pulse-green" />
              /brief · {briefMarkdown.target_date}
            </p>
            <h1 className="text-4xl font-bold tracking-tight">Threat Brief</h1>
            <p className="text-sm text-muted-foreground">
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
        </header>

        {/* Executive snapshot — JSON-driven */}
        <BriefExecSnapshot json={briefJson} />

        {/* Tier chips */}
        <section
          className="grid grid-cols-2 sm:grid-cols-4 gap-2 animate-rogue-fade-up"
          style={{ animationDelay: "0.2s" }}
        >
          <TierChip
            label="CRITICAL"
            count={summary?.new_critical ?? extractCount(briefMarkdown.markdown, "CRITICAL")}
            tint="red"
          />
          <TierChip
            label="HIGH"
            count={summary?.new_high ?? extractCount(briefMarkdown.markdown, "HIGH")}
            tint="orange"
          />
          <TierChip
            label="MEDIUM"
            count={summary?.new_medium ?? extractCount(briefMarkdown.markdown, "MEDIUM")}
            tint="yellow"
          />
          <TierChip
            label="LOW"
            count={summary?.new_low ?? extractCount(briefMarkdown.markdown, "LOW")}
            tint="blue"
          />
        </section>

        <article
          className="border border-border rounded-lg p-6 md:p-8 bg-card/40 backdrop-blur-sm animate-rogue-fade-up"
          style={{ animationDelay: "0.3s" }}
        >
          <BriefMarkdown source={briefMarkdown.markdown} />
        </article>
      </div>
    </main>
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

function extractCount(md: string, tier: string): number {
  const re = new RegExp(`\\*\\*(\\d+)\\*\\*\\s+new\\s+${tier}\\s+attacks`, "i");
  const m = md.match(re);
  return m ? Number(m[1]) : 0;
}
