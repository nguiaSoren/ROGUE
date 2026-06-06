import Link from "next/link";

import { Section } from "@/components/marketing/section";
import { CtaRow } from "@/components/marketing/cta-row";
import { DashboardPreview } from "@/components/marketing/preview/dashboard-preview";
import { FindingsPreview } from "@/components/marketing/preview/findings-preview";
import { ReportPreview } from "@/components/marketing/preview/report-preview";
import { McpPreview } from "@/components/marketing/preview/mcp-preview";

export const metadata = {
  title: "Product — ROGUE",
  description:
    "See exactly what ROGUE does to your stack: a live walkthrough of the scan dashboard, ranked findings, the CISO-ready report, and the MCP server your IDE queries directly.",
};

/**
 * /product — the "see the product" tour. Composes the native marketing
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
            <h1 className="text-4xl md:text-6xl font-bold tracking-tight leading-[1.05]">
              See exactly what ROGUE does to your stack.
            </h1>
            <p className="text-base md:text-lg text-muted-foreground leading-relaxed max-w-2xl">
              Point ROGUE at a deployment and it harvests live open-web
              jailbreaks, reproduces them against your exact model ×
              system-prompt × tools, and ranks what breaks. Here is the whole
              loop — the dashboard, the findings, the report, and the MCP server
              your IDE talks to — shown with real example data.
            </p>
            <CtaRow className="pt-2" />
          </div>
        </Section>

        {/* 2. DASHBOARD ---------------------------------------------- */}
        <Section
          eyebrow="live scans"
          title="Run a scan, watch it live."
          lede="Kick off a scan and watch breaches surface in real time — every attack on the ladder, every panel response, scored as it lands."
          className="animate-rogue-fade-up"
        >
          <DashboardPreview className="mx-auto max-w-4xl" />
        </Section>

        {/* 3. FINDINGS ----------------------------------------------- */}
        <Section
          eyebrow="findings"
          title="Every breach, ranked worst-first."
          lede="The findings feed sorts by severity, so the CRITICAL and HIGH breaches sit at the top — you triage the things that actually matter, not a wall of noise."
          className="animate-rogue-fade-up"
        >
          <FindingsPreview className="mx-auto max-w-4xl" />
        </Section>

        {/* 4. REPORT ------------------------------------------------- */}
        <Section
          eyebrow="reporting"
          title="A report your CISO can read."
          lede="Each scan ships a dated, exportable threat-brief diff — judge-graded breach rates, reproductions, and what changed since last time, in plain language."
          className="animate-rogue-fade-up"
        >
          <ReportPreview className="mx-auto max-w-4xl" />
        </Section>

        {/* 5. MCP ---------------------------------------------------- */}
        <Section
          eyebrow="the signature move"
          title="Red-team from inside your IDE."
          lede="ROGUE exposes its own MCP server, so Claude Desktop, Cursor, and Windsurf query the live threat DB directly. Ask in natural language; get primitives, the breach matrix, and threat briefs back as tools. No other red-team does this."
          className="animate-rogue-fade-up"
        >
          <McpPreview className="mx-auto max-w-4xl" />
        </Section>

        {/* 6. CLOSING ------------------------------------------------ */}
        <Section className="animate-rogue-fade-up">
          <div className="rogue-card border border-border rounded-xl p-8 md:p-12 bg-card/40 backdrop-blur-sm space-y-6">
            <h2 className="text-3xl md:text-4xl font-bold tracking-tight max-w-2xl">
              Point it at your stack.
            </h2>
            <p className="text-base text-muted-foreground leading-relaxed max-w-2xl">
              Get on the list for{" "}
              <Link
                href="/early-access"
                className="text-rogue-green hover:underline underline-offset-4"
              >
                early access
              </Link>
              , or see plans and packaging on{" "}
              <Link
                href="/pricing"
                className="text-rogue-green hover:underline underline-offset-4"
              >
                Pricing
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
