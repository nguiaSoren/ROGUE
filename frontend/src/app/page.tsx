import Link from "next/link";
import { api } from "@/lib/api";
import { AugmentationLab } from "@/components/augmentation-lab";
import { AugmentationShowcase } from "@/components/augmentation-showcase";
import { CinematicHero } from "@/components/cinematic-hero";
import { HowRogueThinks } from "@/components/how-rogue-thinks";
import { IntroOverlay } from "@/components/intro-overlay";
import { LiveAttackTicker } from "@/components/live-attack-ticker";
import { McpConnect } from "@/components/mcp-connect";
import { MiniMatrix } from "@/components/mini-matrix";
import { SourcesMarquee } from "@/components/sources-marquee";

/**
 * Cinematic home — the demo entry. Designed for a 5-second pitch and a
 * 5-minute deep-dive.
 *
 * Reading order:
 *   1. CINEMATIC HERO — rotating-word headline, hero stat trio, one CTA.
 *   2. AHA MOMENT — "freshest threats" ticker + mini-matrix side-by-side.
 *   3. HOW ROGUE THINKS — 3-step narrative (harvest → reproduce → defend).
 *   4. AUGMENTATION SHOWCASE — 5 hero-stat cards (the §10.7 results).
 *   5. AUGMENTATION LAB — interactive: pick a config, toggle augmentations,
 *      watch the estimated breach rate stack.
 *   6. SOURCES MARQUEE — 19 sources × 5 BD products.
 *   7. DEEP-DIVE LINKS — /feed /matrix /brief.
 *
 * Server component. All data fetched in parallel via Promise.allSettled —
 * the page renders even if a backend endpoint is offline.
 */
export default async function Home() {
  const [
    healthResult,
    stubbornnessResult,
    personaResult,
    escalationResult,
    mutationResult,
    attacksResult,
    matrixResult,
    banditResult,
  ] = await Promise.allSettled([
    api.health(),
    api.stubbornnessStats(),
    api.personaStats(),
    api.escalationStats(),
    api.mutationStats(),
    api.attacks({ since_days: 2, limit: 8 }),
    api.breachMatrix(),
    api.banditStats(),
  ]);

  const health = healthResult.status === "fulfilled" ? healthResult.value : null;
  const stubbornness =
    stubbornnessResult.status === "fulfilled"
      ? stubbornnessResult.value
      : null;
  const persona = personaResult.status === "fulfilled" ? personaResult.value : null;
  const escalation =
    escalationResult.status === "fulfilled" ? escalationResult.value : null;
  const mutation =
    mutationResult.status === "fulfilled" ? mutationResult.value : null;
  const attacks = attacksResult.status === "fulfilled" ? attacksResult.value : null;
  const matrix = matrixResult.status === "fulfilled" ? matrixResult.value : null;
  const bandit = banditResult.status === "fulfilled" ? banditResult.value : null;

  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      {/* First-visit auto-play intro — gated by localStorage so it shows
          once per browser. Skip button always visible top-right. */}
      <IntroOverlay />

      <div className="max-w-7xl mx-auto px-6 space-y-20 md:space-y-28 pb-24">
        {/* 1. CINEMATIC HERO ------------------------------------------- */}
        <CinematicHero
          nAttacks={health?.n_primitives ?? attacks?.count ?? null}
          nBreaches={health?.n_breaches ?? null}
          nConfigs={health?.n_configs ?? null}
        />

        {/* 2. BRIGHT DATA SPOTLIGHT — first thing after the hero ------- */}
        <SourcesMarquee bandit={bandit} />

        {/* 3. AHA MOMENT — fresh threats + mini-matrix ----------------- */}
        <section
          className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-6 animate-rogue-fade-up"
        >
          <div className="space-y-2">
            <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green flex items-center gap-2">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-rogue-green animate-rogue-pulse-green" />
              {attacks?.stale ? "latest harvest · threat DB" : "freshest threats · last 48h"}
            </p>
            <h2 className="text-2xl md:text-3xl font-bold tracking-tight">
              {attacks?.stale ? "The most recent attacks we've captured." : "What landed since yesterday."}
            </h2>
            <p className="text-sm text-muted-foreground max-w-xl">
              {attacks?.stale
                ? "The harvester runs on demand. Nothing new landed in the last 48h — these are the most recent attacks in the threat DB."
                : "The harvester runs continuously. Every row below is an attack someone published on the open web in the last 2 days."}
            </p>
            <div className="pt-2">
              <LiveAttackTicker initialAttacks={attacks?.attacks ?? []} />
            </div>
          </div>
          <div className="space-y-2">
            <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
              your stack · at a glance
            </p>
            <MiniMatrix matrix={matrix} />
          </div>
        </section>

        {/* 4. HOW ROGUE THINKS ------------------------------------------ */}
        <HowRogueThinks
          nSources={19}
          nPrimitives={health?.n_primitives ?? null}
          nConfigs={health?.n_configs ?? null}
          nBreaches={health?.n_breaches ?? null}
        />

        {/* 5. AUGMENTATION SHOWCASE ------------------------------------ */}
        <AugmentationShowcase
          bandit={bandit}
          persona={persona}
          escalation={escalation}
          mutation={mutation}
          stubbornness={stubbornness}
        />

        {/* 6. AUGMENTATION LAB — interactive --------------------------- */}
        <AugmentationLab
          persona={persona}
          escalation={escalation}
          mutation={mutation}
          stubbornness={stubbornness}
        />

        {/* 7. DEEP-DIVE LINKS ------------------------------------------ */}
        <section className="space-y-4 animate-rogue-fade-up">
          <div className="space-y-1">
            <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
              go deeper
            </p>
            <h2 className="text-2xl md:text-3xl font-bold tracking-tight">
              Three views on the same truth.
            </h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <PageLink
              href="/feed"
              path="/feed"
              title="Live Feed"
              desc="Newest attacks with the 5-stress-test sidebar. Click any row to see the full payload + breach trail — including the new ▶ play replay."
            />
            <PageLink
              href="/matrix"
              path="/matrix"
              title="Breach Matrix"
              desc="14 attack families × 5 configs. Click any red cell to see the exact prompt that cracked it, with 95% CIs."
            />
            <PageLink
              href="/brief"
              path="/brief"
              title="Threat Brief"
              desc="Today's CISO-readable diff vs yesterday. Markdown + JSON exports. The artifact you'd actually send."
            />
          </div>
        </section>

        {/* 8. CONNECT VIA MCP ----------------------------------------- */}
        <section className="space-y-4 animate-rogue-fade-up">
          <div className="space-y-1">
            <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
              query it yourself
            </p>
            <h2 className="text-2xl md:text-3xl font-bold tracking-tight">
              Connect ROGUE to your IDE.
            </h2>
            <p className="text-sm text-muted-foreground max-w-2xl leading-relaxed">
              ROGUE is also a live MCP server — ask Claude Desktop, Cursor, or
              Windsurf about the threat DB directly. One click connects it.
            </p>
          </div>
          <McpConnect />
        </section>
      </div>
    </main>
  );
}

// --------------------------------------------------------------------------

function PageLink({
  href,
  path,
  title,
  desc,
}: {
  href: string;
  path: string;
  title: string;
  desc: string;
}) {
  return (
    <Link
      href={href}
      className="rogue-card border border-border rounded-xl p-5 bg-card/40 backdrop-blur-sm block group"
    >
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
        {path}
      </p>
      <p className="text-lg font-bold mt-1 group-hover:text-rogue-green transition-colors">
        {title}
      </p>
      <p className="text-sm text-muted-foreground mt-1.5 leading-relaxed">
        {desc}
      </p>
    </Link>
  );
}
