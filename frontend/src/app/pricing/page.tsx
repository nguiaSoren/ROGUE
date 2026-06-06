import { Section } from "@/components/marketing/section";
import { PricingCard } from "@/components/marketing/pricing-card";
import { CtaRow } from "@/components/marketing/cta-row";
import { StatCard } from "@/components/marketing/stat-card";
import { PROOF_POINTS } from "@/lib/proof";

export const metadata = {
  title: "Pricing — ROGUE",
  description:
    "Continuous open-web red-team, priced to the depth you need. Starter, Team, and Enterprise tiers for evaluating and hardening your LLM deployments.",
};

const TIERS = [
  {
    name: "Starter",
    blurb: "For internal evaluations",
    price: "Free during beta",
    features: [
      "Scan a single endpoint",
      "Core jailbreak pack",
      "Sample reports",
      "Community support",
    ],
    ctaLabel: "Request a demo",
    ctaHref: "/request-demo",
    featured: false,
  },
  {
    name: "Team",
    blurb: "For product & security teams running continuous red-team",
    price: "Custom",
    features: [
      "Multiple deployment configs",
      "Full repertoire + escalation ladder",
      "Scheduled scans",
      "Daily threat-brief diff",
      "Slack / Jira delivery",
      "API access",
    ],
    ctaLabel: "Request a demo",
    ctaHref: "/request-demo",
    featured: true,
  },
  {
    name: "Enterprise",
    blurb: "Custom deployment",
    price: "Contact sales",
    features: [
      "Private / self-hosted deployment",
      "SSO",
      "Org isolation",
      "Private scans",
      "MCP server access",
      "Priority support",
      "Custom SLAs",
    ],
    ctaLabel: "Talk to sales",
    ctaHref: "/request-demo",
    featured: false,
  },
] as const;

const FAQ = [
  {
    q: "How does ROGUE connect to my model?",
    a: "Point ROGUE at any HTTP endpoint — a hosted model, a gateway, or your own API. You provide a DeploymentConfig (model × system prompt × tools); ROGUE drives it like a black box and grades every response. No SDK or code change on your side.",
  },
  {
    q: "Which providers are supported?",
    a: "OpenAI, Anthropic, and Gemini out of the box, plus any custom HTTP API that speaks chat-style requests. The provider layer is pluggable, so adding a new target is a thin adapter, not a rewrite.",
  },
  {
    q: "Do you store my model weights?",
    a: "No. ROGUE never sees or stores model weights. It interacts with your deployment only over its public or private API surface — prompts in, responses out — and retains the transcripts needed to produce your report.",
  },
  {
    q: "What's in a report?",
    a: "A headline risk score, the ranked findings (which attack families breached, with the exact prompts that worked and 95% confidence intervals), and concrete remediation guidance for each finding — the artifact you'd actually send to a stakeholder.",
  },
  {
    q: "How is pricing determined?",
    a: "By depth, not seats: the number of deployment configs you cover, how often scans run, and the breadth of the attack repertoire and delivery integrations you need. Pricing is in beta — request a demo and we'll scope it to your stack.",
  },
] as const;

/**
 * /pricing — three tiers, a proof strip, and an FAQ.
 *
 * Pricing figures are placeholders ("Free during beta", "Custom",
 * "Contact sales") per the founder; no committed dollar amounts.
 *
 * Server component. Outer wrapper mirrors the homepage.
 */
export default function PricingPage() {
  const proof = PROOF_POINTS.slice(0, 4);

  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-7xl mx-auto px-6 space-y-20 md:space-y-28 py-20 md:py-28">
        {/* HERO ------------------------------------------------------- */}
        <header className="max-w-3xl space-y-4 animate-rogue-fade-up">
          <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
            pricing
          </p>
          <h1 className="text-4xl md:text-5xl font-bold tracking-tight">
            Priced to the depth you need.
          </h1>
          <p className="text-base text-muted-foreground leading-relaxed">
            ROGUE is a continuous open-web red-team for your LLM deployments —
            harvested live attacks, reproduced against your stack, scored, and
            shipped as a daily threat brief. Pick the tier that matches how deep
            you want to go.
          </p>
        </header>

        {/* TIERS ----------------------------------------------------- */}
        <section className="animate-rogue-fade-up">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-start">
            {TIERS.map((tier) => (
              <PricingCard
                key={tier.name}
                name={tier.name}
                blurb={tier.blurb}
                price={tier.price}
                features={[...tier.features]}
                ctaLabel={tier.ctaLabel}
                ctaHref={tier.ctaHref}
                featured={tier.featured}
              />
            ))}
          </div>
          <p className="mt-6 text-sm text-muted-foreground">
            Pricing is in beta — figures above are placeholders. Request a demo
            and we&apos;ll scope a plan to your deployments.
          </p>
        </section>

        {/* PROOF STRIP ----------------------------------------------- */}
        <Section
          eyebrow="a real engine, not a deck"
          title="Every tier runs the same proven core."
          lede="The numbers below come from the live system — the corpus, the recalibrated judge, and the measured efficiency of the adaptive ladder."
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {proof.map((p) => (
              <StatCard
                key={p.label}
                value={p.value}
                label={p.label}
                sublabel={p.sublabel}
              />
            ))}
          </div>
        </Section>

        {/* FAQ ------------------------------------------------------- */}
        <Section eyebrow="faq" title="Questions, answered.">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {FAQ.map((item) => (
              <div
                key={item.q}
                className="rogue-card border border-border rounded-xl p-5 md:p-6 bg-card/40 backdrop-blur-sm"
              >
                <h3 className="text-base font-bold tracking-tight text-foreground">
                  {item.q}
                </h3>
                <p className="mt-2 text-sm text-muted-foreground leading-relaxed">
                  {item.a}
                </p>
              </div>
            ))}
          </div>
        </Section>

        {/* CLOSING CTA ----------------------------------------------- */}
        <section className="space-y-6 animate-rogue-fade-up">
          <div className="max-w-3xl space-y-4">
            <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
              get started
            </p>
            <h2 className="text-3xl md:text-4xl font-bold tracking-tight">
              See ROGUE run against your stack.
            </h2>
            <p className="text-base text-muted-foreground leading-relaxed">
              Point us at an endpoint and we&apos;ll show you what the open web
              can already do to it.
            </p>
          </div>
          <CtaRow />
        </section>
      </div>
    </main>
  );
}
