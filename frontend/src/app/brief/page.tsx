import { api, BriefJson } from "@/lib/api";
import { BriefMarkdown } from "@/components/brief-markdown";
import { BriefExecSnapshot } from "@/components/brief-exec-snapshot";

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
  const [markdownResult, jsonResult] = await Promise.allSettled([
    api.brief(undefined, "markdown"),
    api.brief(undefined, "json"),
  ]);

  const briefMarkdown =
    markdownResult.status === "fulfilled" ? markdownResult.value : null;
  const briefJsonRes = jsonResult.status === "fulfilled" ? jsonResult.value : null;
  const briefJson = (briefJsonRes?.json ?? null) as BriefJson | null;

  if (!briefMarkdown?.markdown) {
    return (
      <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
        <div className="max-w-4xl mx-auto px-6 py-10 space-y-4">
          <h1 className="text-4xl font-bold tracking-tight">Threat Brief</h1>
          <div className="border border-rogue-red/40 rounded-lg p-6 font-mono text-sm text-rogue-red bg-rogue-red/5">
            {`// brief unavailable: ${
              markdownResult.status === "rejected"
                ? String(markdownResult.reason)
                : "no markdown payload"
            }`}
          </div>
        </div>
      </main>
    );
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
          <div className="flex items-center gap-2 font-mono text-xs">
            <a
              href={`http://localhost:8000/api/brief?date=${briefMarkdown.target_date}&format=markdown`}
              className="px-3 py-1.5 border border-border rounded-md hover:border-rogue-green hover:text-rogue-green transition-colors"
              download
            >
              ↓ .md
            </a>
            <a
              href={`http://localhost:8000/api/brief?date=${briefMarkdown.target_date}&format=json`}
              className="px-3 py-1.5 border border-border rounded-md hover:border-rogue-green hover:text-rogue-green transition-colors"
              download
            >
              ↓ .json
            </a>
          </div>
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
