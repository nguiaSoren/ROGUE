import Link from "next/link"
import { Plug, Zap, Database, ArrowUpRight, PlayCircle } from "lucide-react"

import { Section } from "@/components/marketing/section"
import { StatCard } from "@/components/marketing/stat-card"
import { CORPUS, JUDGE_V3 } from "@/lib/proof"
import { cn } from "@/lib/utils"

const HF_DATASET_URL = "https://huggingface.co/datasets/soren19/rogue-attacks-2026-05"
const DEMO_VIDEO_URL = "https://youtu.be/-luwKpfaf2M"

/**
 * Honest traction / proof band. Credibility through verifiable facts only —
 * NO customer logos, NO testimonials, NO "trusted by". Every claim is true and
 * sourced from the founder's record + src/lib/proof.ts (the single source for
 * corpus/judge numbers — never hard-code different values here). Server component.
 */
export function TractionBand({ className }: { className?: string }) {
  // Numbers come from proof.ts so a corpus/judge re-measure updates the band.
  const stats: ReadonlyArray<{ value: string; label: string; sublabel: string }> = [
    {
      value: `${CORPUS.primitives}`,
      label: "attack primitives",
      sublabel: `${CORPUS.families} families, OWASP + MITRE ATLAS aligned`,
    },
    {
      value: `${CORPUS.sources}`,
      label: "open-web sources",
      sublabel: `harvested via ${CORPUS.bdProducts} Bright Data products`,
    },
    {
      value: `${JUDGE_V3.humanAgreement}%`,
      label: "judge–human agreement",
      sublabel: `up from 70.3% (judge v3, JailbreakBench)`,
    },
    {
      value: `${JUDGE_V3.precision}%`,
      label: "judge precision",
      sublabel: `up from 55% (judge v3 recalibration)`,
    },
  ]

  const milestones: ReadonlyArray<{
    icon: typeof Zap
    title: string
    body: string
  }> = [
    {
      icon: Plug,
      title: "Its own MCP server",
      body: "Query live attacks from Claude, Cursor, or Windsurf — ROGUE is a Model Context Protocol server, not just a dashboard.",
    },
    {
      icon: Zap,
      title: "Live in production",
      body: "Permanently deployed on Vercel + Render + Neon. A running system, not a demo.",
    },
  ]

  return (
    <Section
      eyebrow="traction"
      title="Real results, not logos."
      lede="No customer testimonials, no borrowed credibility. Here's the verifiable evidence the engine is real — a live deployment, its own MCP server, a published dataset, and measured numbers you can check."
      className={className}
    >
      <div className="space-y-8">
        {/* Headline milestones — MCP differentiator + live deployment */}
        <div className="grid gap-4 md:grid-cols-2">
          {milestones.map(({ icon: Icon, title, body }) => (
            <div
              key={title}
              className="rogue-card border border-border rounded-xl p-5 md:p-6 bg-card/40 backdrop-blur-sm flex items-start gap-4"
            >
              <span
                className="shrink-0 grid place-items-center size-10 rounded-lg border border-rogue-green/40 text-rogue-green bg-rogue-green/5"
                aria-hidden
              >
                <Icon className="size-5" />
              </span>
              <div className="space-y-1">
                <div className="text-base font-semibold text-foreground">{title}</div>
                <p className="text-sm text-muted-foreground leading-relaxed">{body}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Measured proof numbers — all from proof.ts */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {stats.map((stat) => (
            <StatCard
              key={stat.label}
              value={stat.value}
              label={stat.label}
              sublabel={stat.sublabel}
            />
          ))}
        </div>

        {/* Verifiable links — open dataset + demo */}
        <div className="flex flex-col sm:flex-row sm:items-center gap-4">
          <Link
            href={HF_DATASET_URL}
            target="_blank"
            rel="noreferrer"
            className={cn(
              "rogue-card border border-border rounded-xl p-5 md:p-6 bg-card/40 backdrop-blur-sm",
              "flex items-center gap-4 flex-1 group transition-colors hover:border-rogue-green",
            )}
          >
            <span
              className="shrink-0 grid place-items-center size-10 rounded-lg border border-rogue-green/40 text-rogue-green bg-rogue-green/5"
              aria-hidden
            >
              <Database className="size-5" />
            </span>
            <div className="space-y-1 min-w-0">
              <div className="text-base font-semibold text-foreground flex items-center gap-1.5">
                Open dataset on Hugging Face
                <ArrowUpRight className="size-4 text-rogue-green opacity-70 transition-opacity group-hover:opacity-100" />
              </div>
              <p className="text-sm text-muted-foreground leading-relaxed">
                {CORPUS.harvested} harvested primitives, published and downloadable — inspect the corpus yourself.
              </p>
            </div>
          </Link>

          <Link
            href={DEMO_VIDEO_URL}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center justify-center gap-2 font-mono text-[12px] uppercase tracking-[0.18em] text-rogue-green hover:text-foreground transition-colors px-2"
          >
            <PlayCircle className="size-4" />
            Watch the demo
          </Link>
        </div>
      </div>
    </Section>
  )
}
