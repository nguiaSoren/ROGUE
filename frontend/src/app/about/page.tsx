import Link from "next/link";
import { Trophy, Target, Radar, Mail, ArrowRight, FlaskConical } from "lucide-react";
import { Section } from "@/components/marketing/section";
import { CtaRow } from "@/components/marketing/cta-row";
import { StatCard } from "@/components/marketing/stat-card";
import { PROOF_POINTS } from "@/lib/proof";

export const metadata = {
  title: "About — ROGUE",
  description:
    "ROGUE is an autonomous open-web LLM red-team agent — built solo by Soren Nguia for the Bright Data × lablab.ai hackathon, now a hosted platform live in production. Mission: make LLM deployments secure by default.",
};

/**
 * /about — the story, mission, and verified numbers behind ROGUE. Strictly
 * factual: solo-build + hackathon origin + live-in-production. The Grand Prize
 * is the founder's PRIOR award (Yonsei CS Exhibition 2024, for the GPTFuzz
 * LLM-security fuzzer) — NOT a ROGUE/hackathon award; attributed accordingly.
 * Contact is email only (no social links, per founder decision). Server
 * component. All proof numbers come from src/lib/proof.ts.
 */
export default function AboutPage() {
  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="space-y-20 md:space-y-28 py-16 md:py-24">
        {/* 1. HERO --------------------------------------------------------- */}
        <Section
          eyebrow="about"
          title="Built to make LLM deployments secure by default."
          lede="ROGUE is a continuous, autonomous red-team for large language models. It learns how real attackers break models from the open web, reproduces those attacks against your deployment, and tells you what's exploitable — before someone else finds out."
        />

        {/* 2. THE STORY --------------------------------------------------- */}
        <Section eyebrow="the story" title="From hackathon to live platform.">
          <div className="max-w-3xl space-y-5">
            <p className="text-base text-muted-foreground leading-relaxed">
              ROGUE was built solo by{" "}
              <span className="text-foreground font-medium">Soren Nguia</span> in
              roughly six days during the{" "}
              <span className="text-foreground font-medium">
                Bright Data × lablab.ai &ldquo;Web Data UNLOCKED&rdquo;
                hackathon
              </span>{" "}
              in May 2026 — an autonomous open-web LLM red-team agent.
            </p>
            <p className="text-base text-muted-foreground leading-relaxed">
              Since the hackathon it has been extended into a hosted,
              multi-tenant platform — SDK, REST API, dashboard, and an MCP
              server — that is permanently live in production.
            </p>
            <div className="rogue-card border border-border rounded-xl p-5 md:p-6 bg-card/40 backdrop-blur-sm flex gap-4">
              <Trophy
                className="h-6 w-6 text-rogue-green shrink-0 mt-0.5"
                strokeWidth={1.75}
                aria-hidden
              />
              <div>
                <p className="text-base font-semibold text-foreground">
                  Grand Prize · Yonsei University CS Exhibition, 2024
                </p>
                <p className="mt-1 text-sm text-muted-foreground leading-relaxed">
                  Awarded to the founder for GPTFuzz optimization — an
                  LLM-security fuzzer. ROGUE is his next LLM-security project,
                  built and run live solo from Seoul, South Korea.
                </p>
              </div>
            </div>
          </div>
        </Section>

        {/* 2b. WHY THIS EXISTS — honest framing: solo research/engineering
            build, early access, no customers yet. Preempts the "overselling a
            customerless SaaS" read for a technical / hiring audience. ------- */}
        <Section
          eyebrow="why this exists"
          title="A solo research build, in the open."
        >
          <div className="rogue-card border border-border rounded-xl p-5 md:p-6 bg-card/40 backdrop-blur-sm max-w-3xl flex gap-4">
            <FlaskConical
              className="h-6 w-6 text-rogue-green shrink-0 mt-0.5"
              strokeWidth={1.75}
              aria-hidden
            />
            <p className="text-base text-muted-foreground leading-relaxed">
              ROGUE is a solo research-and-engineering project, not a funded
              company. It began as a six-day hackathon build and kept getting
              extended — into a hosted platform, an MCP server, a benchmark
              layer, a self-recalibrating judge — to see how far one engineer
              can take a continuous open-web red-team, end to end and in
              production. It&rsquo;s in{" "}
              <span className="text-foreground font-medium">early access</span>:
              a real, running system with real measurements, and no paying
              customers yet. Every figure on this site traces to something
              measured; where the evidence is thin, it says so.
            </p>
          </div>
        </Section>

        {/* 3. MISSION ----------------------------------------------------- */}
        <Section eyebrow="mission">
          <div className="rogue-card border border-border rounded-xl p-6 md:p-10 bg-card/40 backdrop-blur-sm max-w-3xl">
            <Target
              className="h-7 w-7 text-rogue-green"
              strokeWidth={1.75}
              aria-hidden
            />
            <p className="mt-5 text-2xl md:text-3xl font-bold tracking-tight leading-snug">
              To make LLM deployments secure by default — real-time, autonomous
              threat intelligence enterprises can trust.
            </p>
          </div>
        </Section>

        {/* 4. HOW IT WORKS ------------------------------------------------ */}
        <Section eyebrow="how it works" title="Harvest, reproduce, judge.">
          <div className="max-w-3xl space-y-5">
            <p className="text-base text-muted-foreground leading-relaxed">
              ROGUE harvests, reproduces, and judges LLM jailbreaks and
              prompt-injection from the open web —{" "}
              <span className="text-foreground font-medium">
                19 sources across 5 Bright Data products
              </span>{" "}
              — then surfaces the vulnerabilities and exactly how to fix them
              before attackers exploit them.
            </p>
            <div className="flex items-start gap-3">
              <Radar
                className="h-5 w-5 text-rogue-green shrink-0 mt-1"
                strokeWidth={1.75}
                aria-hidden
              />
              <Link
                href="/product"
                className="inline-flex items-center gap-2 font-mono text-sm font-bold tracking-[0.12em] uppercase text-rogue-green hover:opacity-90 transition-opacity"
              >
                See the product
                <ArrowRight className="h-4 w-4" aria-hidden />
              </Link>
            </div>
          </div>
        </Section>

        {/* 5. BY THE NUMBERS ---------------------------------------------- */}
        <Section eyebrow="by the numbers" title="Verified, defensible figures.">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {PROOF_POINTS.map((p) => (
              <StatCard
                key={p.label}
                value={p.value}
                label={p.label}
                sublabel={p.sublabel}
                accent={p.value.startsWith("−") ? "red" : "green"}
              />
            ))}
          </div>
        </Section>

        {/* 6. CONTACT ----------------------------------------------------- */}
        <Section eyebrow="contact" title="Get in touch.">
          <div className="rogue-card border border-border rounded-xl p-6 md:p-8 bg-card/40 backdrop-blur-sm max-w-2xl space-y-4">
            <div className="flex items-center gap-3">
              <Mail
                className="h-5 w-5 text-rogue-green"
                strokeWidth={1.75}
                aria-hidden
              />
              <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
                email
              </p>
            </div>
            <p className="text-sm text-muted-foreground leading-relaxed">
              Questions, partnerships, or anything else — reach the founder
              directly at{" "}
              <a
                href="mailto:nguiasoren@gmail.com"
                className="font-mono text-rogue-green underline-offset-4 hover:underline"
              >
                nguiasoren@gmail.com
              </a>
              .
            </p>
            <Link
              href="/request-demo"
              className="inline-flex items-center gap-2 font-mono text-sm font-bold tracking-[0.12em] uppercase text-rogue-green hover:opacity-90 transition-opacity"
            >
              Request a demo
              <ArrowRight className="h-4 w-4" aria-hidden />
            </Link>
          </div>
        </Section>

        {/* 7. CLOSING CTA ------------------------------------------------- */}
        <Section
          eyebrow="ready when you are"
          title="Point ROGUE at your endpoint."
          lede="See what a continuous open-web red-team finds in your deployment, on a real report."
        >
          <CtaRow />
        </Section>
      </div>
    </main>
  );
}
