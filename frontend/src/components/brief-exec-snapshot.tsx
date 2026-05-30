import Link from "next/link";
import type { BriefJson, BreachedPrimitiveBrief } from "@/lib/api";

/**
 * Brief executive-snapshot panel.
 *
 * The "show me the punchline in 3 seconds" view at the top of /brief. Pulls
 * data from the JSON form of the brief (same disk artifact as the markdown
 * — guaranteed to be consistent).
 *
 * Renders:
 *   1. Net-delta vs yesterday — large signed number with tint.
 *   2. The top-3 worst new attackers (max_any_breach_rate) in a row of cards.
 *   3. A "what to do today" line — recommended action based on whether the
 *      brief has CRITICALs (patch now), newly_defended (note the wins), or
 *      neither (steady state).
 */
export function BriefExecSnapshot({ json }: { json: BriefJson | null }) {
  if (!json) return null;
  const { summary } = json;

  // Top 3 worst new attackers across all tiers.
  const allNew: BreachedPrimitiveBrief[] = [
    ...json.new_critical,
    ...json.new_high,
    ...json.new_medium,
    ...json.new_low,
  ];
  const top3 = [...allNew]
    .sort((a, b) => b.max_any_breach_rate - a.max_any_breach_rate)
    .slice(0, 3);

  const recommendation = pickRecommendation(summary);

  const deltaTint =
    summary.net_delta > 0
      ? "text-rogue-red"
      : summary.net_delta < 0
        ? "text-rogue-green"
        : "text-muted-foreground";
  const deltaSign = summary.net_delta > 0 ? "+" : "";

  return (
    <section className="space-y-3 animate-rogue-fade-up" style={{ animationDelay: "0.15s" }}>
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
        executive snapshot
      </p>
      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-4">
        {/* Net-delta capsule */}
        <div className="rogue-card border border-border rounded-lg p-5 bg-card/40 backdrop-blur-sm space-y-2">
          <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground">
            net Δ vs yesterday
          </p>
          <p className={`text-5xl font-bold tabular-nums leading-none ${deltaTint}`}>
            {deltaSign}
            {summary.net_delta}
          </p>
          <p className="text-xs font-mono text-muted-foreground">
            today{" "}
            <span className="text-foreground tabular-nums">
              {summary.total_today}
            </span>{" "}
            · yesterday{" "}
            <span className="text-foreground tabular-nums">
              {summary.total_yesterday}
            </span>
          </p>
          {summary.newly_defended > 0 && (
            <p className="text-[11px] font-mono text-rogue-green pt-1 border-t border-border">
              ↓ {summary.newly_defended} newly defended
            </p>
          )}
        </div>

        {/* Top-3 worst attackers */}
        <div className="space-y-2">
          <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground">
            worst new attackers today
          </p>
          {top3.length === 0 ? (
            <div className="border border-border rounded-lg p-4 bg-card/40 text-xs font-mono text-muted-foreground">
              {"// no new attackers today — steady state"}
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              {top3.map((p) => (
                <TopAttackerCard key={p.primitive_id} primitive={p} />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Recommended action */}
      <div
        className={`rounded-lg border px-4 py-3 font-mono text-xs ${recommendation.tint}`}
      >
        <span className="uppercase tracking-[0.2em] opacity-80 mr-2">
          recommended action:
        </span>
        <span>{recommendation.text}</span>
      </div>
    </section>
  );
}

function TopAttackerCard({
  primitive,
}: {
  primitive: BreachedPrimitiveBrief;
}) {
  const rate = primitive.max_any_breach_rate;
  const tint =
    rate >= 0.7
      ? "text-rogue-red"
      : rate >= 0.5
        ? "text-orange-300"
        : "text-yellow-300";
  const tierTint =
    {
      critical: "border-rogue-red/40 bg-rogue-red/5",
      high: "border-orange-500/40 bg-orange-500/5",
      medium: "border-yellow-500/40 bg-yellow-500/5",
      low: "border-blue-500/40 bg-blue-500/5",
    }[primitive.severity_tier.toLowerCase()] ?? "border-border";

  // The config behind max_any_breach_rate — the worst-hit (family × config)
  // cell. Clicking the card drills into that cell on /matrix/cell, the same
  // breakdown the matrix grid opens.
  const worstConfig = [...primitive.breached_configs].sort(
    (a, b) => b.any_breach_rate - a.any_breach_rate,
  )[0];
  const href = worstConfig
    ? `/matrix/cell?family=${encodeURIComponent(
        primitive.family,
      )}&config=${encodeURIComponent(worstConfig.config_id)}`
    : null;

  const body = (
    <>
      <div className="flex items-baseline justify-between gap-2">
        <p className={`text-2xl font-bold tabular-nums leading-none ${tint}`}>
          {Math.round(rate * 100)}%
        </p>
        <span className="text-[9px] font-mono uppercase tracking-wider text-muted-foreground">
          {primitive.severity_tier}
        </span>
      </div>
      <p className="text-xs leading-tight mt-2 line-clamp-2" title={primitive.title}>
        {primitive.title}
      </p>
      <p className="text-[10px] font-mono text-muted-foreground mt-1 truncate">
        {primitive.family} · {primitive.breached_configs.length} configs hit
      </p>
    </>
  );

  // Non-clickable fallback when there's no breached config to drill into.
  if (!href) {
    return (
      <div
        className={`rogue-card border rounded-md p-3 bg-card/40 backdrop-blur-sm ${tierTint}`}
      >
        {body}
      </div>
    );
  }

  return (
    <Link
      href={href}
      title={`View ${primitive.family} × ${worstConfig.config_name} cell breakdown`}
      className={`group rogue-card border rounded-md p-3 bg-card/40 backdrop-blur-sm block transition-colors hover:bg-card/70 hover:border-foreground/30 focus:outline-none focus-visible:ring-1 focus-visible:ring-foreground/40 ${tierTint}`}
    >
      {body}
      <p className="text-[9px] font-mono uppercase tracking-[0.18em] text-muted-foreground mt-2 pt-2 border-t border-border/50 opacity-70 group-hover:opacity-100 group-hover:text-foreground transition">
        view cell →
      </p>
    </Link>
  );
}

function pickRecommendation(summary: BriefJson["summary"]): {
  text: string;
  tint: string;
} {
  if (summary.new_critical > 0) {
    return {
      text: `Patch system prompts now — ${summary.new_critical} new CRITICAL attack${summary.new_critical === 1 ? "" : "s"} bypass guardrails today.`,
      tint: "border-rogue-red/40 bg-rogue-red/10 text-rogue-red",
    };
  }
  if (summary.new_high > 0) {
    return {
      text: `Review high-tier additions (${summary.new_high}) and prioritize for next patch window.`,
      tint: "border-orange-500/40 bg-orange-500/10 text-orange-300",
    };
  }
  if (summary.newly_defended > 0) {
    return {
      text: `${summary.newly_defended} attacks now defended — consider re-running the panel to confirm regression.`,
      tint: "border-rogue-green/40 bg-rogue-green/10 text-rogue-green",
    };
  }
  return {
    text: "Steady state — no critical movers today. Continue daily polling cadence.",
    tint: "border-border bg-card/40 text-muted-foreground",
  };
}
