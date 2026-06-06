import Link from "next/link";
import type { Metadata } from "next";
import { ArrowRight, FlaskConical } from "lucide-react";
import { CASE_STUDIES } from "@/content/case-studies";

export const metadata: Metadata = {
  title: "Case Studies — ROGUE",
  description:
    "How a ROGUE engagement reads. Two illustrative templates — one seed-stage startup, one enterprise model-risk team — demonstrating the Problem → Deployment → Findings → Remediation → Outcome reporting framework.",
};

/**
 * /case-studies — index of all case studies.
 *
 * Today the store holds two illustrative TEMPLATES (no real customers exist
 * yet). The intro makes that explicit and invites the reader to become the
 * first real case study. New real entries appended to the content store appear
 * here automatically.
 */
export default function CaseStudiesIndex() {
  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-7xl mx-auto px-6 space-y-20 md:space-y-28 py-20 md:py-28">
        {/* Intro --------------------------------------------------------- */}
        <section className="space-y-5 max-w-3xl animate-rogue-fade-up">
          <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
            case studies
          </p>
          <h1 className="text-3xl md:text-5xl font-bold tracking-tight">
            What a ROGUE engagement looks like.
          </h1>
          <p className="text-base text-muted-foreground leading-relaxed">
            We are pre-first-customer, and we will not invent one. The two
            studies below are{" "}
            <span className="text-foreground font-medium">templates</span> — honest,
            generic examples that show exactly how ROGUE reports a red-team
            engagement, section by section: Problem → Deployment → Findings →
            Remediation → Outcome. Every number in them is an illustrative
            placeholder, clearly marked. When we run our first real engagement,
            its report will land here in this same shape — with real, measured
            results.
          </p>

          {/* Visible templates notice */}
          <div className="flex items-start gap-3 rounded-xl border border-rogue-green/30 bg-rogue-green/5 p-4">
            <FlaskConical className="size-4 text-rogue-green mt-0.5 shrink-0" />
            <p className="text-sm text-muted-foreground leading-relaxed">
              <span className="text-foreground font-medium">
                These are example templates — not real customer engagements.
              </span>{" "}
              They demonstrate ROGUE&apos;s reporting framework using hypothetical,
              generic scenarios.
            </p>
          </div>

          {/* CTA */}
          <div className="pt-2">
            <Link
              href="/request-demo"
              className="inline-flex items-center gap-2 rounded-lg px-6 py-3 bg-rogue-green text-black font-mono text-sm font-bold tracking-[0.15em] uppercase transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rogue-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              Become our first case study
              <ArrowRight className="size-4" />
            </Link>
          </div>
        </section>

        {/* Listing ------------------------------------------------------- */}
        <section className="grid grid-cols-1 md:grid-cols-2 gap-5 animate-rogue-fade-up">
          {CASE_STUDIES.map((cs) => (
            <Link
              key={cs.slug}
              href={`/case-studies/${cs.slug}`}
              className="rogue-card border border-border rounded-xl p-6 bg-card/40 backdrop-blur-sm block group flex flex-col"
            >
              <div className="flex items-center gap-2">
                <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
                  {cs.segment}
                </span>
                {cs.isTemplate && (
                  <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground border border-border rounded px-1.5 py-0.5">
                    Template
                  </span>
                )}
              </div>
              <h2 className="text-xl font-bold mt-3 tracking-tight group-hover:text-rogue-green transition-colors">
                {cs.title}
              </h2>
              <p className="text-sm text-muted-foreground mt-2 leading-relaxed flex-1">
                {cs.summary}
              </p>
              {cs.isTemplate && (
                <p className="mt-4 font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/80">
                  Example template — not a real customer engagement
                </p>
              )}
              <span className="mt-4 inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.16em] text-rogue-green">
                Read the framework
                <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" />
              </span>
            </Link>
          ))}
        </section>
      </div>
    </main>
  );
}
