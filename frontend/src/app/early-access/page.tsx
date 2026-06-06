import Link from "next/link";
import {
  Rocket,
  ClipboardCheck,
  FlaskConical,
  ArrowRight,
  Check,
} from "lucide-react";
import { Section } from "@/components/marketing/section";
import { CtaRow } from "@/components/marketing/cta-row";
import { StatCard } from "@/components/marketing/stat-card";
import { PROOF_POINTS } from "@/lib/proof";

export const metadata = {
  title: "Early Access — ROGUE",
  description:
    "ROGUE is onboarding its first partners. Three honest on-ramps: an Early Access program, scoped pilots on your real deployment, and research partnerships on the harvested corpus and benchmark infra. No customer claims — just an invitation to be early.",
};

/**
 * /early-access — the honest social-proof replacement. ROGUE has no customers
 * yet, so this page never implies any: it frames the three on-ramps for the
 * first partners we're onboarding now. Server component.
 */
export default function EarlyAccessPage() {
  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="space-y-20 md:space-y-28 py-16 md:py-24">
        {/* 1. HERO ---------------------------------------------------------- */}
        <Section
          eyebrow="early access"
          title="We're onboarding our first partners."
          lede="ROGUE is a working red-team engine looking for the teams it goes to production with. We're not showing customer logos, because we don't have customers yet — we have an invitation. There are three ways to take it, depending on where you are."
        >
          <CtaRow />
        </Section>

        {/* 2. THE THREE TRACKS -------------------------------------------- */}
        <Section
          eyebrow="three on-ramps"
          title="Pick the track that fits."
          lede="Every track runs against your real deployment and gives you a direct line to the founder. The difference is depth of commitment, not depth of access."
        >
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {TRACKS.map((track) => (
              <div
                key={track.name}
                className="rogue-card border border-border rounded-xl p-6 md:p-8 bg-card/40 backdrop-blur-sm flex flex-col"
              >
                <track.icon
                  className="h-7 w-7 text-rogue-green"
                  strokeWidth={1.75}
                  aria-hidden
                />
                <h3 className="mt-4 text-xl font-bold tracking-tight">
                  {track.name}
                </h3>
                <p className="mt-2 text-sm text-muted-foreground leading-relaxed">
                  {track.forWhom}
                </p>

                <p className="mt-5 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                  What you get
                </p>
                <ul className="mt-3 space-y-2.5 flex-1">
                  {track.benefits.map((b) => (
                    <li key={b} className="flex gap-2.5 text-sm leading-relaxed">
                      <Check
                        className="h-4 w-4 text-rogue-green shrink-0 mt-0.5"
                        strokeWidth={2}
                        aria-hidden
                      />
                      <span className="text-foreground/90">{b}</span>
                    </li>
                  ))}
                </ul>

                <Link
                  href={track.href}
                  className="mt-6 inline-flex items-center gap-2 font-mono text-sm font-bold tracking-[0.12em] uppercase text-rogue-green hover:opacity-90 transition-opacity"
                >
                  {track.cta}
                  <ArrowRight className="h-4 w-4" aria-hidden />
                </Link>
              </div>
            ))}
          </div>
        </Section>

        {/* 3. WHY PARTNER NOW -------------------------------------------- */}
        <Section
          eyebrow="why partner now"
          title="Being early is the advantage."
          lede="The window where you can shape a security product to your own stack closes fast. Right now it's wide open — and the engine underneath is already real, not a slide deck."
        >
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 max-w-4xl">
            {[PROOF_POINTS[0], PROOF_POINTS[1], PROOF_POINTS[2]].map((p) => (
              <StatCard
                key={p.label}
                value={p.value}
                label={p.label}
                sublabel={p.sublabel}
              />
            ))}
          </div>
          <div className="mt-8 grid grid-cols-1 md:grid-cols-3 gap-4">
            {REASONS.map((r) => (
              <div
                key={r.title}
                className="rogue-card border border-border rounded-xl p-5 md:p-6 bg-card/40 backdrop-blur-sm"
              >
                <h3 className="text-base font-bold tracking-tight">
                  {r.title}
                </h3>
                <p className="mt-2 text-sm text-muted-foreground leading-relaxed">
                  {r.body}
                </p>
              </div>
            ))}
          </div>
        </Section>

        {/* 4. FAQ -------------------------------------------------------- */}
        <Section
          eyebrow="questions"
          title="Before you reach out."
        >
          <dl className="space-y-4 max-w-3xl">
            {FAQ.map((item) => (
              <div
                key={item.q}
                className="rogue-card border border-border rounded-xl p-5 md:p-6 bg-card/40 backdrop-blur-sm"
              >
                <dt className="text-base font-semibold text-foreground">
                  {item.q}
                </dt>
                <dd className="mt-2 text-sm text-muted-foreground leading-relaxed">
                  {item.a}
                </dd>
              </div>
            ))}
          </dl>
        </Section>

        {/* 5. CLOSING CTA ------------------------------------------------ */}
        <Section
          eyebrow="be one of the first"
          title="Take the invitation."
          lede="Tell us about your deployment and which track fits. We're onboarding partners one at a time, so the earlier you reach out, the more say you have in what we build."
        >
          <CtaRow />
        </Section>
      </div>
    </main>
  );
}

// ---------------------------------------------------------------------------

const TRACKS: ReadonlyArray<{
  icon: React.ComponentType<{
    className?: string;
    strokeWidth?: number;
    "aria-hidden"?: boolean;
  }>;
  name: string;
  forWhom: string;
  benefits: ReadonlyArray<string>;
  cta: string;
  href: string;
}> = [
  {
    icon: Rocket,
    name: "Early Access Program",
    forWhom: "For teams who want ROGUE on their stack now.",
    benefits: [
      "Hands-on onboarding from the founder",
      "Full repertoire and adaptive-ladder scans",
      "A direct line to the founder, not a ticket queue",
      "Real influence over the roadmap",
    ],
    cta: "Apply for early access",
    href: "/request-demo",
  },
  {
    icon: ClipboardCheck,
    name: "Pilot Program",
    forWhom:
      "For orgs evaluating their AI security posture before committing.",
    benefits: [
      "A scoped, time-boxed pilot on your real deployment",
      "An executive risk report you can take upstairs",
      "Concrete remediation guidance, not just findings",
      "A clear read on posture before you sign anything",
    ],
    cta: "Start a pilot",
    href: "/request-demo",
  },
  {
    icon: FlaskConical,
    name: "Research Partners",
    forWhom: "For academic, red-team, and model-risk researchers.",
    benefits: [
      "Access to the harvested corpus and benchmark infra",
      "Co-authorship on findings",
      "The MCP server for live threat-DB queries",
      "Early sight of new attack families as they land",
    ],
    cta: "Partner with us",
    href: "/request-demo",
  },
];

const REASONS: ReadonlyArray<{ title: string; body: string }> = [
  {
    title: "Be early",
    body: "First partners get the most attention, the fastest turnaround, and pricing that reflects coming in before everyone else.",
  },
  {
    title: "Shape the product",
    body: "What the first partners need is what gets built next. Your stack, your threat model, your reporting needs feed directly into the roadmap.",
  },
  {
    title: "A real, defensible engine",
    body: "This isn't vaporware. There's a continuous open-web harvest, a recalibrated judge, and an adaptive ladder behind it — working today, against real deployments.",
  },
];

const FAQ: ReadonlyArray<{ q: string; a: React.ReactNode }> = [
  {
    q: "Is there a cost?",
    a: "Early-access and pilot terms are set per partner while we're onboarding our first cohort — being early is meant to be a good deal, not a premium one. Research partnerships are typically non-commercial. Tell us your situation and we'll be straight about what it costs.",
  },
  {
    q: "What do you need from us?",
    a: "Very little: a reachable model endpoint to point ROGUE at, and a judge key for grading the results. ROGUE is the attacker side — it never needs your model weights, training data, or source code.",
  },
  {
    q: "How long is a pilot?",
    a: "Pilots are deliberately time-boxed — usually a couple of weeks from kickoff to the executive risk report. Long enough to run the full repertoire against your real deployment, short enough to get an answer fast.",
  },
  {
    q: "Do you store our data?",
    a: (
      <>
        Only what&apos;s useful to you, and credentials are encrypted at rest.
        Raw attack transcripts can be retained or deleted on request. The full
        data-handling story is on our{" "}
        <Link
          href="/security"
          className="text-rogue-green underline-offset-4 hover:underline"
        >
          security page
        </Link>
        .
      </>
    ),
  },
];
