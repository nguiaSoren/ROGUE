import type { BanditStatsResponse } from "@/lib/api";
import { Term } from "@/components/glossary";
import { PausedOffscreen } from "@/components/paused-offscreen";
import { SourceLogo } from "@/components/ui/source-logo";
import { plainifyYield } from "@/lib/plain-numbers";

/**
 * "Powered by Bright Data" spotlight + horizontal marquee of the
 * open-web sources (15 fire; the strip below shows representative examples).
 * The spotlight surfaces ROGUE's two BD-aligned
 * differentiators that the BD CEO outreach made explicit:
 *
 *   1. Cost-effectiveness, the §11.6 ε-greedy bandit measures bytes-of-
 *      novel-intel per dollar of BD spend and self-tunes its query mix.
 *   2. Reliability + breadth, ROGUE uses all 5 BD products with documented
 *      fallback paths (Scraping Browser → SERP, MCP → Unlocker, etc.).
 *
 * The marquee below pauses on hover so demo viewers can read entries.
 *
 * Server component, pure CSS animation.
 */
const SOURCES: { name: string; via: string; tint: string }[] = [
  { name: "Reddit · r/ChatGPTJailbreak", via: "Web Scraper API", tint: "#ff6b6b" },
  { name: "X · @elder_plinius", via: "Web Scraper API", tint: "#22d3ee" },
  { name: "GitHub · L1B3RT4S", via: "SERP + Unlocker", tint: "#a78bfa" },
  { name: "GitHub · CL4R1T4S", via: "SERP + Unlocker", tint: "#a78bfa" },
  { name: "HuggingFace · discussions", via: "MCP", tint: "#fbbf24" },
  { name: "arXiv · cs.CR new", via: "Unlocker", tint: "#00ff88" },
  { name: "Reddit · r/LocalLLaMA", via: "Web Scraper API", tint: "#ff6b6b" },
  { name: "Reddit · r/PromptEngineering", via: "Web Scraper API", tint: "#ff6b6b" },
  { name: "X · @AISafetyMemes", via: "Web Scraper API", tint: "#22d3ee" },
  { name: "GitHub · awesome-llm-jailbreak", via: "SERP", tint: "#a78bfa" },
  { name: "LeakHub mirrors", via: "Unlocker", tint: "#f87171" },
  { name: "Promptfoo Discord (mirror)", via: "SERP + Unlocker", tint: "#22d3ee" },
  { name: "jailbreakchat", via: "Unlocker", tint: "#f87171" },
  { name: "X · @karpathy reply threads", via: "Web Scraper API", tint: "#22d3ee" },
  { name: "ArXiv · cs.AI new", via: "Unlocker", tint: "#00ff88" },
  { name: "GitHub · llm-attacks", via: "SERP", tint: "#a78bfa" },
  { name: "Reddit · r/Anthropic", via: "Web Scraper API", tint: "#ff6b6b" },
  { name: "HF · LLM-Attacks dataset discussions", via: "MCP", tint: "#fbbf24" },
  { name: "X · breakages-channel", via: "Web Scraper API", tint: "#22d3ee" },
];

export function SourcesMarquee({
  bandit,
}: {
  bandit?: BanditStatsResponse | null;
}) {
  // Duplicate the list so the marquee can loop seamlessly with translateX(-50%).
  const doubled = [...SOURCES, ...SOURCES];

  // The bandit is the cost-optimization story, full hero treatment.
  const hotArm = bandit?.top_arms?.[0];
  const coldArm = bandit?.bottom_arms?.[0];
  const hotYield = hotArm ? hotArm.mean_yield.toFixed(2) : null;
  const yieldRatio =
    hotArm && coldArm && coldArm.mean_yield > 0
      ? (hotArm.mean_yield / coldArm.mean_yield).toFixed(1)
      : null;
  const plainBandit = hotArm
    ? plainifyYield(hotArm.mean_yield)
    : "bandit warming up, first pulls in progress";

  return (
    <section className="space-y-6">
      {/* Spotlight hero --------------------------------------------------- */}
      <div className="space-y-2 animate-rogue-fade-up">
        <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
          powered by Bright Data
        </p>
        <h2 className="text-3xl md:text-4xl font-bold tracking-tight max-w-3xl">
          Five products. Fifteen sources.{" "}
          <span className="text-rogue-green">One self-tuning budget.</span>
        </h2>
        <p className="text-base text-muted-foreground max-w-2xl leading-relaxed">
          Most red-team tools scrape one platform and hope it stays free.
          ROGUE fans out across the entire Bright Data product line and lets
          a bandit decide where to spend the next dollar, automatically.
        </p>
      </div>

      {/* BANDIT HERO CALLOUT --------------------------------------------- */}
      {/* The literal cost-optimization mechanism, called out as THE       */}
      {/* moment of the BD section.                                        */}
      <div className="rogue-card rogue-accent-bandit border border-border rounded-xl p-6 md:p-8 bg-card/40 backdrop-blur-sm rogue-scan-line space-y-5 animate-rogue-fade-up">
        <div className="flex items-baseline justify-between gap-4 flex-wrap">
          <div>
            <p className="font-mono text-[10px] uppercase tracking-[0.22em] rogue-accent-bandit-text">
              cost-effectiveness · live
            </p>
            <h3 className="text-2xl md:text-3xl font-bold tracking-tight mt-2 max-w-2xl">
              Every Bright Data dollar gets routed to the queries currently
              finding the most novel attacks.
            </h3>
          </div>
          {yieldRatio && (
            <span className="font-mono text-[10px] uppercase tracking-[0.18em] px-3 py-1.5 rounded-md bg-rogue-green/10 border border-rogue-green/40 text-rogue-green">
              hot arm = <span className="font-bold">{yieldRatio}×</span>{" "}
              cold arm
            </span>
          )}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-[260px_1fr] gap-6 items-start">
          {/* The hero number */}
          <div className="space-y-1 min-w-0">
            <p className="text-5xl sm:text-6xl md:text-7xl font-bold tabular-nums leading-none text-rogue-green">
              {hotYield ?? ", "}
            </p>
            <p className="text-[11px] font-mono uppercase tracking-[0.18em] text-foreground mt-2">
              novel attacks per $1 BD spend
            </p>
            <p className="text-[11px] text-muted-foreground leading-snug">
              from the hot arm {hotArm ? `· ${hotArm.arm_id.slice(0, 24)}${
                hotArm.arm_id.length > 24 ? "…" : ""
              }` : ""}
            </p>
            <p className="text-[11px] text-foreground/80 leading-snug pt-2 border-t border-border/40 mt-3">
              <span className="font-mono uppercase tracking-wider text-[9px] text-muted-foreground/70 block">
                in plain English
              </span>
              {plainBandit}
            </p>
          </div>

          {/* How it works, the BD CEO answer */}
          <div className="space-y-3 text-sm leading-relaxed">
            <p>
              <span className="font-semibold text-foreground">
                The mechanism:
              </span>{" "}
              an <Term name="ε-greedy">ε-greedy</Term>{" "}
              <Term name="bandit">bandit</Term> tracks 36 candidate{" "}
              <Term name="SERP">SERP</Term> queries. Every harvest, it
              picks the 10 with the highest yield (novel attacks per $ of
              BD spend) and explores 1 random arm to stay honest.
            </p>
            <p className="text-muted-foreground">
              <span className="font-semibold text-foreground">
                Why it matters to BD:
              </span>{" "}
              you stop paying for queries that no longer surface anything
              new. Hot arms get 90% of pulls; dead arms quietly retire.
              Your BD spend gets sharper every day, no manual tuning.
            </p>
            {bandit && (
              <p className="text-[11px] font-mono text-muted-foreground pt-2 border-t border-border/40">
                {bandit.n_arms} arms · {bandit.n_warm_arms ?? 0} warm ·
                seeded{" "}
                {bandit.seeded_from_corpus_at
                  ? bandit.seeded_from_corpus_at.slice(0, 10)
                  : ", "}
                {" · live pulls since "}
                {bandit.last_live_pulled_at
                  ? bandit.last_live_pulled_at.slice(0, 10)
                  : ", "}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* 3 supporting metric tiles (bandit dropped, it's the hero now) -- */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 animate-rogue-fade-up">
        <MetricTile
          value="5 / 5"
          unit="Bright Data products in use"
          sub={
            <>
              <Term name="MCP">MCP</Term> · <Term name="SERP">SERP</Term> ·
              Unlocker · Scraping Browser · Web Scraper
            </>
          }
          tint="green"
        />
        <MetricTile
          value="15"
          unit="open-web sources fanned out"
          sub={
            <span className="inline-flex flex-wrap items-center gap-x-1 gap-y-0.5">
              <SourceLogo source="Reddit" className="text-foreground/60" />Reddit ·{" "}
              <SourceLogo source="X" className="text-foreground/60" />X ·{" "}
              <SourceLogo source="GitHub" className="text-foreground/60" />GitHub ·{" "}
              <SourceLogo source="HuggingFace" className="text-foreground/60" />HuggingFace ·{" "}
              <SourceLogo source="arXiv" className="text-foreground/60" />arXiv · leaks
            </span>
          }
          tint="green"
        />
        <MetricTile
          value="2-tier"
          unit="reliability with explicit fallbacks"
          sub="Scraping Browser → SERP · MCP → Unlocker · per-plugin error isolation"
          tint="green"
        />
      </div>

      {/* Sources marquee, single visual representation of the source     */}
      {/* roster; the per-product card grid was removed as it duplicated  */}
      {/* the "via X" labels in the marquee chips below.                  */}
      <div className="space-y-2">
        <div className="flex items-baseline justify-between">
          <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
            live source roster · color-coded by Bright Data product
          </p>
          <p className="hidden sm:block font-mono text-[10px] text-muted-foreground">
            hover to pause
          </p>
        </div>
        <div className="relative overflow-hidden border-y border-border py-4 rogue-marquee-pause">
          <div className="absolute inset-y-0 left-0 w-24 bg-gradient-to-r from-[var(--rogue-bg-deep)] to-transparent z-10 pointer-events-none" />
          <div className="absolute inset-y-0 right-0 w-24 bg-gradient-to-l from-[var(--rogue-bg-deep)] to-transparent z-10 pointer-events-none" />

          <PausedOffscreen className="rogue-marquee flex gap-3 w-max">
            {doubled.map((s, i) => (
              <div
                key={`${s.name}-${i}`}
                className="shrink-0 px-4 py-2 rounded-md border border-border bg-card/30 backdrop-blur-sm font-mono text-xs flex items-center gap-2"
              >
                <span
                  className="inline-block w-1.5 h-1.5 rounded-full"
                  style={{ background: s.tint, boxShadow: `0 0 6px ${s.tint}` }}
                />
                <SourceLogo source={s.name} className="text-foreground/70 text-sm" />
                <span className="text-foreground">{s.name}</span>
                <span className="text-muted-foreground">· {s.via}</span>
              </div>
            ))}
          </PausedOffscreen>
        </div>
      </div>
    </section>
  );
}

function MetricTile({
  value,
  unit,
  sub,
  tint,
}: {
  value: string;
  unit: string;
  sub: React.ReactNode;
  tint: "green" | "red";
}) {
  const tintClass = tint === "green" ? "text-rogue-green" : "text-rogue-red";
  return (
    <div className="rogue-card border border-border rounded-lg p-4 bg-card/40 backdrop-blur-sm">
      <p
        className={`text-3xl md:text-4xl font-bold tabular-nums leading-none ${tintClass}`}
      >
        {value}
      </p>
      <p className="text-[11px] font-mono uppercase tracking-[0.18em] text-foreground mt-2">
        {unit}
      </p>
      <p className="text-[10px] text-muted-foreground mt-1 leading-snug">
        {sub}
      </p>
    </div>
  );
}
