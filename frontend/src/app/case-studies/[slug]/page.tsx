import Link from "next/link";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ArrowLeft, ArrowRight, FlaskConical } from "lucide-react";
import { StatCard } from "@/components/marketing/stat-card";
import {
  CASE_STUDIES,
  getCaseStudy,
  isTaggedFindings,
  type CaseStudy,
  type Severity,
} from "@/content/case-studies";

/**
 * /case-studies/[slug], one case study rendered through the canonical
 * framework: Problem → Deployment → Findings → Remediation → Outcome, with an
 * optional metrics strip.
 *
 * Static at build (generateStaticParams), per-study metadata, 404 on unknown
 * slug. Next.js 16: route params are async.
 */

export function generateStaticParams() {
  return CASE_STUDIES.map((cs) => ({ slug: cs.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const cs = getCaseStudy(slug);
  if (!cs) {
    return { title: "Case study not found, ROGUE" };
  }
  return {
    title: `${cs.title}, ROGUE Case Studies`,
    description: cs.summary,
  };
}

const severityChip: Record<Severity, string> = {
  critical: "text-rogue-red border-rogue-red/40 bg-rogue-red/10",
  high: "text-rogue-red border-rogue-red/30 bg-rogue-red/5",
  medium: "text-foreground border-border bg-muted/30",
  low: "text-rogue-green border-rogue-green/30 bg-rogue-green/5",
};

export default async function CaseStudyDetail({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const cs = getCaseStudy(slug);
  if (!cs) notFound();

  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-7xl mx-auto px-6 py-20 md:py-28 space-y-16 md:space-y-20">
        {/* Back-link --------------------------------------------------- */}
        <Link
          href="/case-studies"
          className="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.16em] text-muted-foreground hover:text-rogue-green transition-colors"
        >
          <ArrowLeft className="size-3.5" />
          All case studies
        </Link>

        {/* Header ------------------------------------------------------ */}
        <header className="max-w-3xl space-y-5 animate-rogue-fade-up">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
              {cs.segment}
            </span>
            {cs.isTemplate && (
              <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground border border-border rounded px-1.5 py-0.5">
                Template
              </span>
            )}
          </div>
          <h1 className="text-3xl md:text-5xl font-bold tracking-tight">
            {cs.title}
          </h1>
          <p className="text-[17px] text-foreground leading-relaxed">
            {cs.summary}
          </p>

          {cs.isTemplate && (
            <div className="flex items-start gap-3 rounded-xl border border-rogue-green/30 bg-rogue-green/5 p-4">
              <FlaskConical className="size-4 text-rogue-green mt-0.5 shrink-0" />
              <p className="text-sm text-muted-foreground leading-relaxed">
                <span className="text-foreground font-medium">
                  Example template, not a real customer engagement.
                </span>{" "}
                This illustrates ROGUE&apos;s reporting framework with a
                hypothetical scenario; all metrics are placeholders.
              </p>
            </div>
          )}
        </header>

        {/* Metrics strip ---------------------------------------------- */}
        {cs.metrics && cs.metrics.length > 0 && (
          <section className="grid grid-cols-1 sm:grid-cols-3 gap-4 animate-rogue-fade-up">
            {cs.metrics.map((m) => (
              <StatCard key={m.label} value={m.value} label={m.label} />
            ))}
          </section>
        )}

        {/* Canonical sections ----------------------------------------- */}
        <article className="space-y-14 md:space-y-16 max-w-3xl">
          <ReportSection eyebrow="01 · Problem" title="The problem">
            <p className="text-[17px] text-foreground leading-relaxed">
              {cs.problem}
            </p>
          </ReportSection>

          <ReportSection eyebrow="02 · Deployment" title="The deployment under test">
            <p className="text-[17px] text-foreground leading-relaxed">
              {cs.deployment}
            </p>
          </ReportSection>

          <ReportSection eyebrow="03 · Findings" title="What ROGUE measured">
            <Findings cs={cs} />
          </ReportSection>

          <ReportSection eyebrow="04 · Remediation" title="Remediation">
            <ul className="space-y-3">
              {cs.remediation.map((r, i) => (
                <li
                  key={i}
                  className="flex items-start gap-3 text-[17px] text-foreground leading-relaxed"
                >
                  <span className="mt-2 size-1.5 rounded-full bg-rogue-green shrink-0" />
                  <span>{r}</span>
                </li>
              ))}
            </ul>
          </ReportSection>

          <ReportSection eyebrow="05 · Outcome" title="The outcome">
            <p className="text-[17px] text-foreground leading-relaxed">
              {cs.outcome}
            </p>
          </ReportSection>
        </article>

        {/* Footer CTA -------------------------------------------------- */}
        <section className="rogue-card border border-border rounded-xl p-8 bg-card/40 backdrop-blur-sm max-w-3xl space-y-4">
          <h2 className="text-2xl font-bold tracking-tight">
            Want a report like this for your stack?
          </h2>
          <p className="text-sm text-muted-foreground leading-relaxed">
            Point ROGUE at your agent and get this exact framework filled in with
            real, measured results across all three surfaces, whether the model
            can be broken, whether the human oversight is meaningful, and whether
            the accumulated knowledge is safe, with a signed, reproducible
            record. ROGUE even generates and re-tests the fix; you own and deploy
            the runtime.
          </p>
          <Link
            href="/request-demo"
            className="inline-flex items-center gap-2 rounded-lg px-6 py-3 bg-rogue-green text-black font-mono text-sm font-bold tracking-[0.15em] uppercase transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rogue-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            Become our first case study
            <ArrowRight className="size-4" />
          </Link>
        </section>
      </div>
    </main>
  );
}

// --------------------------------------------------------------------------

function ReportSection({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-5 animate-rogue-fade-up">
      <div className="space-y-2">
        <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
          {eyebrow}
        </p>
        <h2 className="text-2xl md:text-3xl font-bold tracking-tight">
          {title}
        </h2>
      </div>
      {children}
    </section>
  );
}

function Findings({ cs }: { cs: CaseStudy }) {
  if (isTaggedFindings(cs.findings)) {
    return (
      <div className="space-y-4">
        {cs.findings.map((f, i) => (
          <div
            key={i}
            className="rogue-card border border-border rounded-xl p-5 bg-card/40 backdrop-blur-sm space-y-2"
          >
            <div className="flex items-center gap-3">
              <span
                className={`font-mono text-[10px] uppercase tracking-[0.16em] border rounded px-1.5 py-0.5 ${severityChip[f.severity]}`}
              >
                {f.severity}
              </span>
              <h3 className="text-base font-bold tracking-tight">{f.title}</h3>
            </div>
            <p className="text-sm text-muted-foreground leading-relaxed">
              {f.detail}
            </p>
          </div>
        ))}
      </div>
    );
  }

  return (
    <ul className="space-y-3">
      {cs.findings.map((f, i) => (
        <li
          key={i}
          className="flex items-start gap-3 text-[17px] text-foreground leading-relaxed"
        >
          <span className="mt-2 size-1.5 rounded-full bg-rogue-red shrink-0" />
          <span>{f}</span>
        </li>
      ))}
    </ul>
  );
}
