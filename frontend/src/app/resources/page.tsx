import Link from "next/link";
import {
  FileText,
  FileCode2,
  ScaleIcon,
  BookOpen,
  Video,
  ArrowRight,
  Lock,
} from "lucide-react";

import { Section } from "@/components/marketing/section";
import { NewsletterSignup } from "@/components/marketing/newsletter-signup";
import { ThreatReportDownload } from "@/components/marketing/threat-report-download";

export const metadata = {
  title: "Resources, ROGUE",
  description:
    "Threat intel and research from ROGUE: the latest LLM threat brief, a sample security report, and our judge v3 recalibration write-up. Subscribe to get future threat briefs.",
};

/**
 * /resources, lead-gen hub. Deliberately honest: only links artifacts that
 * actually exist (the daily threat brief, a static sample report, and the
 * judge-v3 recalibration result whose numbers are real/defensible). Unwritten
 * content (blog, webinar) is shown under a visibly-labeled "Coming soon" group,
 * never as a live link, and carries no fabricated stats. The "gated content"
 * mechanism is the real newsletter signup. Server component.
 */
export default function ResourcesPage() {
  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="space-y-20 md:space-y-28 py-16 md:py-24">
        {/* 1. HERO --------------------------------------------------------- */}
        <Section
          eyebrow="resources"
          title="Threat intel & research from ROGUE."
          lede="ROGUE runs a continuous open-web red-team, harvesting jailbreaks and prompt-injection, reproducing them against real LLM deployments, and writing down what we learn. Here's what's published, and what's on the way."
        />

        {/* 2. LIVE NOW, real artifacts ----------------------------------- */}
        <Section
          eyebrow="live now"
          title="Available today."
          lede="These are real, published outputs, not placeholders."
        >
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {/* Latest threat brief */}
            <Link
              href="/brief"
              className="rogue-card group border border-border rounded-xl p-6 bg-card/40 backdrop-blur-sm flex flex-col transition-colors hover:border-rogue-green focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rogue-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              <FileText
                className="h-6 w-6 text-rogue-green"
                strokeWidth={1.75}
                aria-hidden
              />
              <h3 className="mt-4 text-lg font-bold tracking-tight">
                Latest LLM threat brief
              </h3>
              <p className="mt-2 flex-1 text-sm text-muted-foreground leading-relaxed">
                A regenerated daily diff of new jailbreaks and prompt-injection
                harvested from the open web and reproduced against real
                deployments.
              </p>
              <span className="mt-4 inline-flex items-center gap-2 font-mono text-xs font-bold uppercase tracking-[0.12em] text-rogue-green">
                Read the brief
                <ArrowRight
                  className="h-4 w-4 transition-transform group-hover:translate-x-0.5"
                  aria-hidden
                />
              </span>
            </Link>

            {/* Sample security report */}
            <a
              href="/sample-report.html"
              target="_blank"
              rel="noopener noreferrer"
              className="rogue-card group border border-border rounded-xl p-6 bg-card/40 backdrop-blur-sm flex flex-col transition-colors hover:border-rogue-green focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rogue-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              <FileCode2
                className="h-6 w-6 text-rogue-green"
                strokeWidth={1.75}
                aria-hidden
              />
              <h3 className="mt-4 text-lg font-bold tracking-tight">
                Sample security report
              </h3>
              <p className="mt-2 flex-1 text-sm text-muted-foreground leading-relaxed">
                A full example of the scored scan report ROGUE produces, which
                attacks landed, how severe they are, and the evidence behind
                each verdict.
              </p>
              <span className="mt-4 inline-flex items-center gap-2 font-mono text-xs font-bold uppercase tracking-[0.12em] text-rogue-green">
                Open the report
                <ArrowRight
                  className="h-4 w-4 transition-transform group-hover:translate-x-0.5"
                  aria-hidden
                />
              </span>
            </a>

            {/* Judge v3 recalibration write-up, on-page summary card */}
            <div className="rogue-card border border-rogue-green/40 rounded-xl p-6 bg-card/40 backdrop-blur-sm flex flex-col">
              <ScaleIcon
                className="h-6 w-6 text-rogue-green"
                strokeWidth={1.75}
                aria-hidden
              />
              <h3 className="mt-4 text-lg font-bold tracking-tight">
                Judge v3 recalibration write-up
              </h3>
              <p className="mt-2 text-sm text-muted-foreground leading-relaxed">
                We diagnosed our LLM judge over-flagging against JailbreakBench
                and recalibrated it. The result, measured on that benchmark:
              </p>
              <dl className="mt-4 grid grid-cols-2 gap-3">
                <div className="rounded-lg border border-border bg-background/40 p-3">
                  <dt className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                    Human agreement
                  </dt>
                  <dd className="mt-1 font-mono text-sm font-bold tabular-nums text-rogue-green">
                    70.3% → 89.3%
                  </dd>
                </div>
                <div className="rounded-lg border border-border bg-background/40 p-3">
                  <dt className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                    Precision
                  </dt>
                  <dd className="mt-1 font-mono text-sm font-bold tabular-nums text-rogue-green">
                    55% → 79.5%
                  </dd>
                </div>
              </dl>
              <p className="mt-4 text-xs text-muted-foreground leading-relaxed">
                The full methodology write-up is going out to threat-brief
                subscribers, sign up below to get it.
              </p>
            </div>
          </div>
        </Section>

        {/* 3. GATED, newsletter + threat-brief CTA ----------------------- */}
        <Section
          eyebrow="get the threat brief"
          title="Subscribe for future briefs and write-ups."
          lede="The threat brief, and deeper write-ups like the judge v3 recalibration, go out to subscribers. No spam, unsubscribe anytime."
        >
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <NewsletterSignup variant="section" />
            <ThreatReportDownload />
          </div>
        </Section>

        {/* 4. COMING SOON, not yet written ------------------------------- */}
        <Section
          eyebrow="coming soon"
          title="On the way."
          lede="These aren't published yet. We'd rather label them honestly than fake a link."
        >
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {COMING_SOON.map((item) => (
              <div
                key={item.title}
                className="rogue-card border border-dashed border-border rounded-xl p-6 bg-card/20 flex flex-col opacity-90"
              >
                <div className="flex items-center justify-between gap-3">
                  <item.icon
                    className="h-6 w-6 text-muted-foreground"
                    strokeWidth={1.75}
                    aria-hidden
                  />
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                    <Lock className="h-3 w-3" aria-hidden />
                    Coming soon
                  </span>
                </div>
                <h3 className="mt-4 text-lg font-bold tracking-tight text-foreground/80">
                  {item.kind}
                </h3>
                <p className="mt-1 text-sm text-muted-foreground leading-relaxed">
                  {item.title}
                </p>
              </div>
            ))}
          </div>
          <p className="mt-6 text-sm text-muted-foreground leading-relaxed">
            Want these when they drop?{" "}
            <Link
              href="#"
              className="text-rogue-green underline-offset-4 hover:underline"
            >
              Subscribe above
            </Link>{" "}
            and we&apos;ll send them out.
          </p>
        </Section>

        {/* 5. CLOSING CTA ------------------------------------------------- */}
        <Section
          eyebrow="ready when you are"
          title="See what ROGUE finds against your model."
          lede="The fastest way to understand the threat brief is to run a scan on your own endpoint."
        >
          <Link
            href="/request-demo"
            className="inline-flex items-center justify-center gap-2 rounded-lg px-6 py-3 bg-rogue-green text-black font-mono text-sm font-bold tracking-[0.15em] uppercase transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rogue-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            Request a demo
            <ArrowRight className="h-4 w-4" aria-hidden />
          </Link>
        </Section>
      </div>
    </main>
  );
}

// ---------------------------------------------------------------------------

const COMING_SOON: ReadonlyArray<{
  icon: React.ComponentType<{
    className?: string;
    strokeWidth?: number;
    "aria-hidden"?: boolean;
  }>;
  kind: string;
  title: string;
}> = [
  {
    icon: BookOpen,
    kind: "Blog",
    title: "The State of LLM Jailbreaks in 2026",
  },
  {
    icon: Video,
    kind: "Webinar",
    title: "Live demo: blocking jailbreaks in real time",
  },
];
