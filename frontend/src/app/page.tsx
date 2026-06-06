import Link from "next/link";
import {
  Boxes,
  ShieldAlert,
  Swords,
  Gauge,
  ScrollText,
} from "lucide-react";
import { api } from "@/lib/api";
import { AugmentationLab } from "@/components/augmentation-lab";
import { AugmentationShowcase } from "@/components/augmentation-showcase";
import { CinematicHero } from "@/components/cinematic-hero";
import { HowRogueThinks } from "@/components/how-rogue-thinks";
import { IntroOverlay } from "@/components/intro-overlay";
import { LiveAttackTicker } from "@/components/live-attack-ticker";
import { McpConnect } from "@/components/mcp-connect";
import { MiniMatrix } from "@/components/mini-matrix";
import { ProductPitch } from "@/components/product-pitch";
import { SourcesMarquee } from "@/components/sources-marquee";
import { Section } from "@/components/marketing/section";
import { StatCard } from "@/components/marketing/stat-card";
import { CtaRow } from "@/components/marketing/cta-row";
import { WorkflowWalkthrough } from "@/components/marketing/workflow-walkthrough";
import { ReportPreview } from "@/components/marketing/preview/report-preview";
import { McpPreview } from "@/components/marketing/preview/mcp-preview";
import { EarlyAccessSection } from "@/components/marketing/early-access-section";
import { NewsletterSignup } from "@/components/marketing/newsletter-signup";
import { ThreatReportDownload } from "@/components/marketing/threat-report-download";
import { PROOF_POINTS } from "@/lib/proof";

/**
 * Cinematic home — the demo entry. Designed for a 5-second pitch and a
 * 5-minute deep-dive.
 *
 * Reading order:
 *   1. CINEMATIC HERO — rotating-word headline, hero stat trio, one CTA.
 *   2. PRODUCT PITCH — the offer: point ROGUE at an endpoint → scored report.
 *   3. SOURCES MARQUEE — 19 sources × 5 BD products.
 *   4. AHA MOMENT — "freshest threats" ticker + mini-matrix side-by-side.
 *   5. HOW ROGUE THINKS — 3-step narrative (harvest → reproduce → defend).
 *   6. AUGMENTATION SHOWCASE — 5 hero-stat cards (the §10.7 results).
 *   7. AUGMENTATION LAB — interactive: pick a config, toggle augmentations,
 *      watch the estimated breach rate stack.
 *   8. DEEP-DIVE LINKS — /feed /matrix /brief.
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

        {/* 2. PRODUCT PITCH — what you actually buy (give us an endpoint
            → get a security report). Placed right after the hero so the
            offer reads before the supporting threat-intel proof. -------- */}
        <ProductPitch
          nAttacks={health?.n_primitives ?? attacks?.count ?? null}
        />

        {/* 3. BRIGHT DATA SPOTLIGHT ------------------------------------ */}
        <SourcesMarquee bandit={bandit} />

        {/* 4. AHA MOMENT — fresh threats + mini-matrix ----------------- */}
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

        {/* 4b. BUILT FOR — one engine, five teams --------------------- */}
        <Section
          eyebrow="built for"
          title="One engine, five teams."
          lede="Point ROGUE at an endpoint and every team that touches an LLM gets the answer they need from the same scored report."
          className="!px-0 animate-rogue-fade-up"
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            <PersonaCard
              icon={<Boxes className="w-5 h-5" />}
              title="AI Product Teams"
              benefit="Ship features knowing your assistant won't be talked into off-script behavior in prod."
            />
            <PersonaCard
              icon={<ShieldAlert className="w-5 h-5" />}
              title="Security Teams"
              benefit="Continuous open-web red-team coverage without standing up an offensive crew."
            />
            <PersonaCard
              icon={<Swords className="w-5 h-5" />}
              title="Red Teams"
              benefit="358 reproducible attack primitives and an adaptive ladder to attack your own configs faster."
            />
            <PersonaCard
              icon={<Gauge className="w-5 h-5" />}
              title="Model Risk Teams"
              benefit="Quantified breach rates per model × prompt × tool, with 95% CIs you can sign off on."
            />
            <PersonaCard
              icon={<ScrollText className="w-5 h-5" />}
              title="Compliance Teams"
              benefit="A CISO-readable threat brief mapped to OWASP LLM Top 10 and MITRE ATLAS."
            />
          </div>
        </Section>

        {/* 4c. WORKFLOW WALKTHROUGH — the concrete end-to-end story
            (connect endpoint → ladder scan → jailbreak → filed ticket).
            Self-headed; sits between the personas and the MCP pitch so the
            "how it actually works" answer lands right after "who it's for". */}
        <section className="animate-rogue-fade-up">
          <WorkflowWalkthrough />
        </section>

        {/* 5. CONNECT VIA MCP — query it yourself, one click ----------- */}
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

        {/* 5b. PRODUCT PREVIEW TEASER — make it concrete: a real scored
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

        {/* 8. AUGMENTATION LAB — interactive --------------------------- */}
        <AugmentationLab
          persona={persona}
          escalation={escalation}
          mutation={mutation}
          stubbornness={stubbornness}
        />

        {/* 8b. PROOF BAND — defensible, verified numbers -------------- */}
        <Section
          eyebrow="the receipts"
          title="Numbers we can defend."
          lede="Every figure traces to a published line in the corpus or plan — no inflated ASR headlines, just what holds up under a recalibrated judge."
          className="!px-0 animate-rogue-fade-up"
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {PROOF_POINTS.map((p) => (
              <StatCard
                key={p.label}
                value={p.value}
                label={p.label}
                sublabel={p.sublabel}
              />
            ))}
          </div>
        </Section>

        {/* 8c. EARLY ACCESS — the honest "who's using it" answer: no logos
            yet, we're onboarding first partners. Self-contained, max-w-7xl. */}
        <div className="animate-rogue-fade-up">
          <EarlyAccessSection />
        </div>

        {/* 9. DEEP-DIVE LINKS ------------------------------------------ */}
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

        {/* 9b. THREAT INTEL + NEWSLETTER — concrete artifacts to take away
            plus a low-commitment subscribe, adjacent on desktop. ---------- */}
        <section className="grid grid-cols-1 lg:grid-cols-2 gap-6 animate-rogue-fade-up">
          <ThreatReportDownload />
          <NewsletterSignup variant="section" />
        </section>

        {/* 10. CLOSING CTA — conversion close ------------------------- */}
        <section className="rogue-card border border-border rounded-2xl p-8 md:p-12 bg-card/40 backdrop-blur-sm text-center animate-rogue-fade-up">
          <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
            get started
          </p>
          <h2 className="mt-3 text-3xl md:text-4xl font-bold tracking-tight">
            See ROGUE break your stack.
          </h2>
          <p className="mt-3 text-base text-muted-foreground max-w-2xl mx-auto leading-relaxed">
            Point us at an endpoint and get a scored security report back. Book a
            walkthrough, or run a scan yourself right now.
          </p>
          <div className="mt-8 flex flex-col sm:flex-row gap-3 md:gap-4 justify-center items-center">
            <Link
              href="/scans/new"
              className="inline-flex items-center justify-center rounded-lg px-6 py-3 bg-rogue-green text-black font-mono text-sm font-bold tracking-[0.15em] uppercase transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rogue-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              Run a free scan
            </Link>
            <CtaRow />
          </div>
          <div className="mt-4 flex flex-col sm:flex-row gap-x-6 gap-y-2 justify-center font-mono text-xs uppercase tracking-[0.15em] text-muted-foreground">
            <Link
              href="/pricing"
              className="transition-colors hover:text-rogue-green"
            >
              View pricing
            </Link>
          </div>
        </section>

      </div>
    </main>
  );
}

// --------------------------------------------------------------------------

function PersonaCard({
  icon,
  title,
  benefit,
}: {
  icon: React.ReactNode;
  title: string;
  benefit: string;
}) {
  return (
    <div className="rogue-card border border-border rounded-xl p-5 bg-card/40 backdrop-blur-sm">
      <div className="inline-flex items-center justify-center w-9 h-9 rounded-lg border border-border text-rogue-green">
        {icon}
      </div>
      <p className="text-lg font-bold mt-3">{title}</p>
      <p className="text-sm text-muted-foreground mt-1.5 leading-relaxed">
        {benefit}
      </p>
    </div>
  );
}

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
