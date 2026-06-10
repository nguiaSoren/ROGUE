import { notFound } from "next/navigation";
import { Check, Minus } from "lucide-react";
import { Section } from "@/components/marketing/section";
import { PricingCard } from "@/components/marketing/pricing-card";
import { CtaRow } from "@/components/marketing/cta-row";
import { StatCard } from "@/components/marketing/stat-card";
import { PROOF_POINTS } from "@/lib/proof";
import { COMMERCIAL } from "@/lib/flags";

export const metadata = {
  title: "Pricing, ROGUE",
  description:
    "Continuous open-web red-team, priced to the depth you need. Free, Pro, and Enterprise tiers for evaluating and hardening your LLM deployments.",
};

const TIERS = [
  {
    name: "Free",
    blurb: "For evaluations",
    price: "$0",
    period: undefined,
    features: [
      "10 scans / month",
      "1 deployment config",
      "Public-data attack packs",
      "Community support",
      "Integrations: MCP + Slack",
    ],
    ctaLabel: "Start free",
    ctaHref: "/request-demo",
    featured: false,
  },
  {
    name: "Pro",
    blurb: "For product & security teams",
    price: "$999",
    period: "/month",
    features: [
      "Unlimited scans",
      "5 deployment configs",
      "Private deployments",
      "Priority support",
      "Integrations: MCP + Slack + SOAR/SIEM (coming soon)",
    ],
    ctaLabel: "Request a demo",
    ctaHref: "/request-demo",
    featured: true,
  },
  {
    name: "Enterprise",
    blurb: "For regulated & large-scale orgs",
    price: "Custom",
    period: undefined,
    features: [
      "Unlimited scans",
      "Unlimited deployment configs",
      "Private / self-hosted",
      "Dedicated support",
      "RBAC + SSO",
      "Audit-ready compliance reports",
      "All integrations",
    ],
    ctaLabel: "Talk to sales",
    ctaHref: "/request-demo",
    featured: false,
  },
] as const;

/**
 * Comparison-table rows. Each cell is either a string label, `true` (check),
 * or `false` (dash). Columns are [Free, Pro, Enterprise].
 */
type Cell = string | boolean;
const COMPARISON: ReadonlyArray<{
  label: string;
  cells: readonly [Cell, Cell, Cell];
}> = [
  { label: "Price", cells: ["$0", "$999 / month", "Custom"] },
  { label: "Scans / month", cells: ["10", "Unlimited", "Unlimited"] },
  { label: "Deployment configs", cells: ["1", "5", "Unlimited"] },
  {
    label: "Data",
    cells: ["Public packs", "Public + private", "Public + private / self-hosted"],
  },
  { label: "Support", cells: ["Community", "Priority", "Dedicated"] },
  {
    label: "Integrations",
    cells: [
      "MCP + Slack",
      "MCP + Slack + SOAR/SIEM (soon)",
      "All (SOAR/SIEM soon)",
    ],
  },
  { label: "RBAC", cells: [false, false, true] },
  { label: "SSO", cells: [false, false, true] },
  {
    label: "Compliance",
    cells: [false, false, "Audit-ready (SOC 2 / ISO on roadmap)"],
  },
] as const;

const FAQ = [
  {
    q: "How does a scan connect to my model?",
    a: "Point ROGUE at any HTTP endpoint, a hosted model, a gateway, or your own API. You provide a DeploymentConfig (model × system prompt × tools); ROGUE drives it like a black box and grades every response. No SDK or code change on your side.",
  },
  {
    q: "What counts as a scan?",
    a: "One scan is a full red-team run against a single deployment config: ROGUE replays the attack repertoire, escalates the ones that land, judges every response, and ships you a scored report. Free includes 10 scans a month; Pro and Enterprise are unlimited.",
  },
  {
    q: "Can I self-host?",
    a: "Yes, on Enterprise. We support private and self-hosted deployments so the engine runs inside your own environment with your network controls. Free and Pro run on our hosted platform.",
  },
  {
    q: "Do you store my model weights?",
    a: "No. ROGUE never sees or stores model weights. It interacts with your deployment only over its public or private API surface, prompts in, responses out, and retains the transcripts needed to produce your report.",
  },
  {
    q: "What about SOC 2?",
    a: "SOC 2 and ISO 27001 are on our roadmap, we are not certified today and don't claim to be. What we provide now are audit-ready reports and compliance-supporting evidence: every breach is reproduced with the exact prompt, the judge verdict, and confidence intervals, so the artifact stands up to scrutiny.",
  },
  {
    q: "Which providers are supported?",
    a: "OpenAI, Anthropic, and Gemini out of the box, plus any custom HTTP API that speaks chat-style requests. The provider layer is pluggable, so adding a new target is a thin adapter, not a rewrite.",
  },
] as const;

/** Renders one comparison-table cell, check, dash, or label text. */
function CompCell({ value }: { value: Cell }) {
  if (value === true) {
    return (
      <Check
        className="size-4 text-rogue-green"
        aria-label="Included"
      />
    );
  }
  if (value === false) {
    return (
      <Minus
        className="size-4 text-muted-foreground/50"
        aria-label="Not included"
      />
    );
  }
  return <span className="leading-relaxed">{value}</span>;
}

/**
 * /pricing, concrete tiers (Free / Pro / Enterprise), a comparison table,
 * a proof strip, and an FAQ.
 *
 * Server component. Outer wrapper mirrors the homepage. Pricing figures are
 * committed real numbers. Compliance is framed honestly: audit-ready evidence
 * today, SOC 2 / ISO 27001 on the roadmap (NOT certified). SOAR/SIEM
 * integrations are labeled "coming soon".
 */
export default function PricingPage() {
  // Gated by NEXT_PUBLIC_SHOW_COMMERCIAL (see @/lib/flags). In honest hiring
  // mode (the default), /pricing 404s; flip the flag on for the startup pitch.
  if (!COMMERCIAL) notFound();

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
          <p className="text-[17px] text-foreground leading-relaxed">
            ROGUE is a continuous open-web red-team for your LLM deployments, 
            harvested live attacks, reproduced against your stack, scored, and
            shipped as a report. Start free, scale on Pro, go private on
            Enterprise.
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
                period={tier.period}
                features={[...tier.features]}
                ctaLabel={tier.ctaLabel}
                ctaHref={tier.ctaHref}
                featured={tier.featured}
              />
            ))}
          </div>
          <p className="mt-6 text-sm text-muted-foreground">
            All plans include the same proven engine. SOAR/SIEM integrations
            (Splunk, Palo Alto) are coming soon; MCP, Slack, Jira, and the API
            are available today.
          </p>
        </section>

        {/* COMPARISON TABLE ------------------------------------------ */}
        <Section
          eyebrow="compare"
          title="What's in each plan."
          lede="The same core engine across every tier, the plan sets how many configs you cover, how often you scan, and the controls your org needs."
        >
          {/* Desktop: full comparison table (md+). */}
          <div className="hidden md:block rogue-card border border-border rounded-xl bg-card/40 backdrop-blur-sm overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th className="px-5 py-4 text-left font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                    Feature
                  </th>
                  {TIERS.map((tier) => (
                    <th
                      key={tier.name}
                      className={
                        "px-5 py-4 text-left font-bold tracking-tight " +
                        (tier.featured ? "text-rogue-green" : "text-foreground")
                      }
                    >
                      {tier.name}
                      {tier.featured && (
                        <span className="ml-2 align-middle font-mono text-[9px] font-bold uppercase tracking-[0.18em] text-rogue-green">
                          Most popular
                        </span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {COMPARISON.map((row) => (
                  <tr
                    key={row.label}
                    className="border-b border-border/60 last:border-b-0"
                  >
                    <th
                      scope="row"
                      className="px-5 py-4 text-left font-medium text-foreground align-top"
                    >
                      {row.label}
                    </th>
                    {row.cells.map((cell, i) => (
                      <td
                        key={i}
                        className="px-5 py-4 text-left text-muted-foreground align-top"
                      >
                        <CompCell value={cell} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile: stacked per-tier comparison cards (below md). */}
          <div className="md:hidden space-y-4">
            {TIERS.map((tier, tierIdx) => (
              <div
                key={tier.name}
                className={
                  "rogue-card rounded-xl bg-card/40 backdrop-blur-sm p-5 " +
                  (tier.featured
                    ? "border-2 border-rogue-green"
                    : "border border-border")
                }
              >
                <div className="flex items-baseline justify-between gap-3 border-b border-border/60 pb-3">
                  <h3
                    className={
                      "text-lg font-bold tracking-tight " +
                      (tier.featured ? "text-rogue-green" : "text-foreground")
                    }
                  >
                    {tier.name}
                  </h3>
                  {tier.featured && (
                    <span className="font-mono text-[9px] font-bold uppercase tracking-[0.18em] text-rogue-green">
                      Most popular
                    </span>
                  )}
                </div>
                <dl className="mt-3 space-y-2.5 text-sm">
                  {COMPARISON.map((row) => (
                    <div
                      key={row.label}
                      className="flex items-start justify-between gap-4"
                    >
                      <dt className="min-w-0 font-medium text-foreground break-words">
                        {row.label}
                      </dt>
                      <dd className="min-w-0 text-right text-muted-foreground break-words">
                        <CompCell value={row.cells[tierIdx]} />
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            ))}
          </div>
        </Section>

        {/* PROOF STRIP ----------------------------------------------- */}
        <Section
          eyebrow="a real engine, not a deck"
          title="Every tier runs the same proven core."
          lede="The numbers below come from the live system, the corpus, the recalibrated judge, and the measured efficiency of the adaptive ladder."
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
            <p className="text-[17px] text-foreground leading-relaxed">
              Point us at an endpoint and we&apos;ll show you what the open web
              can already do to it.
            </p>
          </div>
          <CtaRow />
          <p className="text-sm text-muted-foreground">
            Need a custom plan?{" "}
            <a
              href="/request-demo"
              className="text-rogue-green hover:underline underline-offset-4"
            >
              Contact sales →
            </a>
          </p>
        </section>
      </div>
    </main>
  );
}
