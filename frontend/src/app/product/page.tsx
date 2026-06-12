import Link from "next/link";

import { Section } from "@/components/marketing/section";
import { CtaRow } from "@/components/marketing/cta-row";
import { DashboardPreview } from "@/components/marketing/preview/dashboard-preview";
import { FindingsPreview } from "@/components/marketing/preview/findings-preview";
import { ReportPreview } from "@/components/marketing/preview/report-preview";
import { McpPreview } from "@/components/marketing/preview/mcp-preview";
import { McpConnect } from "@/components/marketing/mcp-connect";
import { OversightPreview } from "@/components/marketing/preview/oversight-preview";
import { SkillPoolPreview } from "@/components/marketing/preview/skill-pool-preview";

export const metadata = {
  title: "Product, ROGUE",
  description:
    "See exactly what ROGUE does to your stack: a live walkthrough of the scan dashboard, ranked findings, the CISO-ready report, and the MCP server your IDE queries directly.",
};

/**
 * /product, the "see the product" tour. Composes the native marketing
 * previews into a single narrative walkthrough: a section per faux app-window
 * preview (dashboard, findings, report, MCP). Server component; every preview is
 * self-contained with example data, so there is no client state here.
 */
export default function ProductPage() {
  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="space-y-20 md:space-y-28 py-20 md:py-28">
        {/* 1. HERO ----------------------------------------------------- */}
        <Section className="animate-rogue-fade-up">
          <div className="max-w-3xl space-y-6">
            <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
              the product
            </p>
            <h1 className="text-3xl sm:text-4xl md:text-6xl font-bold tracking-tight leading-[1.05]">
              See exactly what ROGUE does to your stack.
            </h1>
            <p className="text-base md:text-lg text-muted-foreground leading-relaxed max-w-2xl">
              Point ROGUE at a deployment and it harvests live open-web
              jailbreaks, reproduces them against your exact model ×
              system-prompt × tools, and ranks what breaks. Here is the whole
              loop, the dashboard, the findings, the report, and the MCP server
              your IDE talks to, shown with real example data.
            </p>
            <CtaRow className="pt-2" />
          </div>
        </Section>

        {/* 2. DASHBOARD ---------------------------------------------- */}
        <Section
          id="live-scan"
          eyebrow="live scans"
          title="Run a scan, watch it live."
          lede="Kick off a scan and watch breaches surface in real time, every attack on the ladder, every panel response, scored as it lands."
          className="animate-rogue-fade-up"
        >
          <DashboardPreview className="mx-auto max-w-4xl" />
        </Section>

        {/* 3. FINDINGS ----------------------------------------------- */}
        <Section
          eyebrow="findings"
          title="Every breach, ranked worst-first."
          lede="The findings feed sorts by severity, so the CRITICAL and HIGH breaches sit at the top, you triage the things that actually matter, not a wall of noise."
          className="animate-rogue-fade-up"
        >
          <FindingsPreview className="mx-auto max-w-4xl" />
        </Section>

        {/* 4. REPORT ------------------------------------------------- */}
        <Section
          eyebrow="reporting"
          title="A report your CISO can read."
          lede="Each scan ships a dated, exportable threat-brief diff, judge-graded breach rates, reproductions, and what changed since last time, in plain language."
          className="animate-rogue-fade-up"
        >
          <ReportPreview className="mx-auto max-w-4xl" />
        </Section>

        {/* 5. MCP ---------------------------------------------------- */}
        <Section
          id="mcp"
          eyebrow="the signature move"
          title="Red-team from inside your IDE."
          lede="ROGUE exposes its own MCP server, so Claude Desktop, Cursor, and Windsurf query the live threat DB directly. Ask in natural language; get primitives, the breach matrix, and threat briefs back as tools. No other red-team does this."
          className="animate-rogue-fade-up"
        >
          <div className="mx-auto max-w-4xl space-y-6">
            <McpPreview />
            <p className="text-center font-mono text-[11px] uppercase tracking-[0.18em] text-rogue-green">
              ↓ this server is live — connect to it right now
            </p>
            <McpConnect />
          </div>
        </Section>

        {/* 6. v2 ASSURANCE SURFACES ---------------------------------- */}
        <Section
          eyebrow="beyond the model"
          title="Three surfaces where AI systems fail. ROGUE measures and signs all three."
          lede="Red-teaming the model is one surface. ROGUE also measures the two that usually go unaudited, the human who approves a risky action and the skill pool your agents share, and emits a signed, tamper-evident attestation for each, scored against an answer key provably independent of what it&rsquo;s grading."
          className="animate-rogue-fade-up"
        >
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 md:gap-6 max-w-5xl mx-auto">
            <Link
              href="#live-scan"
              className="rogue-card border border-border rounded-xl p-6 bg-card/40 backdrop-blur-sm space-y-3 block group transition-colors hover:border-rogue-green/40"
            >
              <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-rogue-green">
                the model · offense
              </p>
              <h3 className="text-lg font-semibold tracking-tight group-hover:text-rogue-green transition-colors">
                Reproduce real jailbreaks.
              </h3>
              <p className="text-[15px] text-muted-foreground leading-relaxed">
                Open-web jailbreaks reproduced against your exact model ×
                system-prompt × tools, ranked worst-first, the scan above.
              </p>
            </Link>
            <Link
              href="#human-gate"
              className="rogue-card border border-border rounded-xl p-6 bg-card/40 backdrop-blur-sm space-y-3 block group transition-colors hover:border-rogue-green/40"
            >
              <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-rogue-green">
                the human gate · oversight
              </p>
              <h3 className="text-lg font-semibold tracking-tight group-hover:text-rogue-green transition-colors">
                Is the sign-off meaningful?
              </h3>
              <p className="text-[15px] text-muted-foreground leading-relaxed">
                When a risky action escalates to a person, ROGUE measures whether
                that oversight is <span className="text-foreground">meaningful</span>,
                a false-approve rate against an independent answer key, so &ldquo;a
                human approved it&rdquo; becomes a measured control, not an
                assumption.
              </p>
            </Link>
            <Link
              href="#skill-pool"
              className="rogue-card border border-border rounded-xl p-6 bg-card/40 backdrop-blur-sm space-y-3 block group transition-colors hover:border-rogue-green/40"
            >
              <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-rogue-green">
                the agent&rsquo;s memory · assurance
              </p>
              <h3 className="text-lg font-semibold tracking-tight group-hover:text-rogue-green transition-colors">
                Audit the skill pool.
              </h3>
              <p className="text-[15px] text-muted-foreground leading-relaxed">
                Shared agent-skill pools are an unaudited surface. ROGUE red-teams
                the pool for leakage, verifies each skill actually helps before it
                spreads, flags dangerous skill combinations, and signs the result.
              </p>
            </Link>
          </div>
          <p className="text-[15px] text-muted-foreground leading-relaxed max-w-3xl mx-auto text-center pt-6">
            Every result is signed into a tamper-evident hash chain and scored
            against a provably-independent key,{" "}
            <span className="text-foreground">
              threat-informed assurance, not a safety guarantee
            </span>
            .
          </p>
        </Section>

        {/* 6a. OVERSIGHT / HUMAN GATE -------------------------------- */}
        <Section
          id="human-gate"
          eyebrow="the human gate"
          title="Is the sign-off meaningful, or a rubber stamp?"
          lede="When a risky action escalates to a person, ROGUE scores their decision against a provably-independent answer key and reports a measured false-approve rate, so &ldquo;a human approved it&rdquo; becomes a control you can audit."
          className="animate-rogue-fade-up"
        >
          <OversightPreview className="mx-auto max-w-4xl" />
        </Section>

        {/* 6b. SKILL POOL AUDIT -------------------------------------- */}
        <Section
          id="skill-pool"
          eyebrow="the agent's memory"
          title="Audit the skill pool before it spreads."
          lede="Shared agent-skill pools are an unaudited surface. ROGUE red-teams the pool for extraction leakage, verifies each skill actually helps before it promotes, and quarantines dangerous skill combinations."
          className="animate-rogue-fade-up"
        >
          <SkillPoolPreview className="mx-auto max-w-4xl" />
        </Section>

        {/* 7. CLOSING ------------------------------------------------ */}
        <Section className="animate-rogue-fade-up">
          <div className="rogue-card border border-border rounded-xl p-8 md:p-12 bg-card/40 backdrop-blur-sm space-y-6">
            <h2 className="text-3xl md:text-4xl font-bold tracking-tight max-w-2xl">
              Point it at your stack.
            </h2>
            <p className="text-[17px] text-foreground leading-relaxed max-w-2xl">
              Get on the list for{" "}
              <Link
                href="/early-access"
                className="text-rogue-green hover:underline underline-offset-4"
              >
                early access
              </Link>
              .
            </p>
            <CtaRow />
          </div>
        </Section>
      </div>
    </main>
  );
}
