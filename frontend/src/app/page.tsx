import Link from "next/link";
import { api } from "@/lib/api";
import { AugmentationShowcase } from "@/components/augmentation-showcase";
import { CinematicHero } from "@/components/cinematic-hero";
import { HowRogueThinks } from "@/components/how-rogue-thinks";
import { IntroOverlay } from "@/components/intro-overlay";
import { LiveAttackTicker } from "@/components/live-attack-ticker";
import { MiniMatrix } from "@/components/mini-matrix";
import { SourcesMarquee } from "@/components/sources-marquee";
import { Section } from "@/components/marketing/section";
import { CtaRow } from "@/components/marketing/cta-row";
import { WorkflowWalkthrough } from "@/components/marketing/workflow-walkthrough";
import { ReportPreview } from "@/components/marketing/preview/report-preview";
import { McpPreview } from "@/components/marketing/preview/mcp-preview";

// ISR, statically prerendered + revalidated every 5 min, matching /matrix and
// REVALIDATE_SECONDS in lib/api.ts, so visitors get instant loads and new Neon
// data surfaces within the window instead of paying the full round-trip.
// "auto" = ISR on Vercel; the self-host docker build rewrites it to "force-dynamic" (docker/frontend.Dockerfile).
export const dynamic = "auto";
export const revalidate = 1800;

/**
 * Cinematic home, the demo entry. Designed for a 5-second pitch and a
 * 5-minute deep-dive.
 *
 * Reading order:
 *   1. CINEMATIC HERO, rotating-word headline (states the offer), stat trio, CTA.
 *  1b. THREE SURFACES, the v2 breadth (model / human gate / agent memory).
 *   2. SOURCES MARQUEE, 15 sources × 5 BD products.
 *   3. AHA MOMENT, "freshest threats" ticker + mini-matrix side-by-side.
 *   4. WORKFLOW WALKTHROUGH, the concrete end-to-end story (endpoint → report).
 *   5. PRODUCT PREVIEW, a real scored report + a live MCP session (teaser → /product).
 *   6. HOW ROGUE THINKS, 3-step narrative (harvest → reproduce → defend).
 *   7. AUGMENTATION SHOWCASE, the §10.7 results.
 *   8. DEEP-DIVE LINKS, closing CTA.
 *
 * Server component. All data fetched in parallel via Promise.allSettled, 
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
      {/* First-visit auto-play intro, gated by localStorage so it shows
          once per browser. Skip button always visible top-right. */}
      <IntroOverlay />

      <div className="max-w-7xl mx-auto px-6 space-y-20 md:space-y-28 pb-24">
        {/* 1. CINEMATIC HERO ------------------------------------------- */}
        <CinematicHero
          nAttacks={health?.n_primitives ?? attacks?.count ?? null}
          nBreaches={health?.n_breaches ?? null}
          nConfigs={health?.n_configs ?? null}
        />

        {/* 1b. THREE SURFACES, the v2 breadth lands before the narrow
            model demo so visitors see the full standard first. --------- */}
        <Section
          eyebrow="beyond the model"
          title="Three surfaces where a high-stakes agent goes wrong — one engine, every result signed."
          lede="Red-teaming the model is one surface. ROGUE also measures the human who approves a risky action and the skill pool your agents share, and signs every result against a provably-independent answer key."
          className="!px-0 animate-rogue-fade-up"
        >
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <Link
              href="/product#live-scan"
              className="rogue-card border border-border rounded-xl p-5 bg-card/40 backdrop-blur-sm block group transition-colors hover:border-rogue-green/40"
            >
              <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
                the model · offense
              </p>
              <p className="text-lg font-bold mt-1 group-hover:text-rogue-green transition-colors">
                Reproduce real jailbreaks.
              </p>
              <p className="text-sm text-muted-foreground mt-1.5 leading-relaxed">
                Open-web attacks replayed against your exact model, system
                prompt, and tools, ranked worst-first.
              </p>
            </Link>
            <Link
              href="/product#human-gate"
              className="rogue-card border border-border rounded-xl p-5 bg-card/40 backdrop-blur-sm block group transition-colors hover:border-rogue-green/40"
            >
              <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
                the human gate · oversight
              </p>
              <p className="text-lg font-bold mt-1 group-hover:text-rogue-green transition-colors">
                Measure the sign-off.
              </p>
              <p className="text-sm text-muted-foreground mt-1.5 leading-relaxed">
                When a risky action escalates to a person, a false-approve rate
                against an independent key, so &ldquo;a human approved it&rdquo;
                is a measured control, not an assumption.
              </p>
            </Link>
            <Link
              href="/product#skill-pool"
              className="rogue-card border border-border rounded-xl p-5 bg-card/40 backdrop-blur-sm block group transition-colors hover:border-rogue-green/40"
            >
              <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
                the agent&rsquo;s memory · assurance
              </p>
              <p className="text-lg font-bold mt-1 group-hover:text-rogue-green transition-colors">
                Audit the skill pool.
              </p>
              <p className="text-sm text-muted-foreground mt-1.5 leading-relaxed">
                Shared agent skills, checked for leakage, whether they actually
                help, and dangerous combinations, before they spread.
              </p>
            </Link>
          </div>
          <div className="mt-6">
            <Link
              href="/product"
              className="inline-flex items-center gap-1.5 font-mono text-xs uppercase tracking-[0.15em] text-rogue-green transition-opacity hover:opacity-80"
            >
              See all three on the product tour &rarr;
            </Link>
          </div>
        </Section>

        {/* 2. SCRAPER-AGNOSTIC HARVEST ---------------------------------- */}
        <SourcesMarquee bandit={bandit} />

        {/* 4. AHA MOMENT, fresh threats + mini-matrix ----------------- */}
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
                ? "The harvester runs on demand. Nothing new landed in the last 48h, these are the most recent attacks in the threat DB."
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

        {/* 4. WORKFLOW WALKTHROUGH, the concrete end-to-end story
            (connect endpoint → ladder scan → jailbreak → filed ticket).
            Self-headed; sits between the aha moment and the MCP pitch so the
            "how it actually works" answer lands right after "what landed". */}
        <section className="animate-rogue-fade-up">
          <WorkflowWalkthrough />
        </section>

        {/* 5. PRODUCT PREVIEW TEASER, make it concrete: a real scored
            report + the MCP session, side-by-side on desktop, stacked on
            mobile. Two previews max here; the full set lives on /product. */}
        <Section
          eyebrow="see the product"
          title="This is what you get back."
          lede="A scored executive report you can hand to a CISO, and a live MCP session that runs the whole red-team from inside your editor."
          className="!px-0 animate-rogue-fade-up"
        >
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <ReportPreview />
            <McpPreview />
          </div>
          <div className="mt-6">
            <Link
              href="/product"
              className="inline-flex items-center gap-1.5 font-mono text-xs uppercase tracking-[0.15em] text-rogue-green transition-opacity hover:opacity-80"
            >
              Take the full product tour &rarr;
            </Link>
          </div>
        </Section>

        {/* 6. HOW ROGUE THINKS ------------------------------------------ */}
        <HowRogueThinks
          nSources={19}
          nPrimitives={health?.n_primitives ?? null}
          nConfigs={health?.n_configs ?? null}
          nBreaches={health?.n_breaches ?? null}
        />

        {/* 7. AUGMENTATION SHOWCASE ------------------------------------ */}
        <AugmentationShowcase
          bandit={bandit}
          persona={persona}
          escalation={escalation}
          mutation={mutation}
          stubbornness={stubbornness}
        />

        {/* 8. DEEP-DIVE LINKS ------------------------------------------ */}
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
              desc="Newest attacks with the 5-stress-test sidebar. Click any row to see the full payload + breach trail, including the new ▶ play replay."
            />
            <PageLink
              href="/matrix"
              path="/matrix"
              title="Breach Matrix"
              desc={`${
                matrix?.families.length ?? 15
              } attack families × ${
                health?.n_configs ?? matrix?.configs.length ?? 8
              } configs. Click any red cell to see the exact prompt that cracked it, with 95% CIs.`}
            />
            <PageLink
              href="/brief"
              path="/brief"
              title="Threat Brief"
              desc="Today's CISO-readable diff vs yesterday. Markdown + JSON exports. The artifact you'd actually send."
            />
          </div>
        </section>

        {/* 10. CLOSING CTA, conversion close ------------------------- */}
        <section className="rogue-card border border-border rounded-2xl p-8 md:p-12 bg-card/40 backdrop-blur-sm text-center animate-rogue-fade-up">
          <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
            get started
          </p>
          <h2 className="mt-3 text-3xl md:text-4xl font-bold tracking-tight">
            See where your agent goes wrong.
          </h2>
          <p className="mt-3 text-base text-muted-foreground max-w-2xl mx-auto leading-relaxed">
            Watch ROGUE run a scan right now, no signup — the model that can be
            broken, the human sign-off that may be rubber-stamped, the skills that
            can leak — every result a signed, reproducible record. Then read the
            research, or scan your own model — live, no install.
          </p>
          <div className="mt-8 flex flex-col sm:flex-row gap-3 md:gap-4 justify-center items-center">
            <Link
              href="/scan"
              className="inline-flex items-center justify-center rounded-lg px-6 py-3 bg-rogue-green text-black font-mono text-sm font-bold tracking-[0.15em] uppercase transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rogue-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              Scan your model
            </Link>
            <Link
              href="/try"
              className="inline-flex items-center justify-center rounded-lg px-6 py-3 border border-rogue-green/50 text-rogue-green font-mono text-sm font-bold tracking-[0.15em] uppercase transition-colors hover:bg-rogue-green/10"
            >
              Watch the demo
            </Link>
            <CtaRow />
          </div>
          <div className="mt-4 flex flex-col sm:flex-row gap-x-6 gap-y-2 justify-center font-mono text-xs uppercase tracking-[0.15em] text-muted-foreground">
            <Link
              href="/research"
              className="transition-colors hover:text-rogue-green"
            >
              Read the research
            </Link>
          </div>
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
