import Link from "next/link"
import {
  Bot,
  Layers,
  Bell,
  FileCheck,
  Workflow,
} from "lucide-react"

import { cn } from "@/lib/utils"
import { COMMERCIAL } from "@/lib/flags"

interface EnterprisePitchProps {
  className?: string
}

interface Feature {
  icon: React.ComponentType<{ className?: string }>
  claim: string
  detail: React.ReactNode
}

/**
 * The enterprise feature checklist. Honest framing only — every claim maps to a
 * shipped capability. Compliance (SOC 2 / ISO 27001) and SOAR/SIEM are marked as
 * roadmap, never as delivered. No email alerts (Slack only). No customer claims.
 */
const FEATURES: Feature[] = [
  {
    icon: Bot,
    claim: "Autonomous red-teaming",
    detail:
      "ROGUE continuously tests your deployments against the latest harvested jailbreaks. No manual effort.",
  },
  {
    icon: Layers,
    claim: "Multimodal defense",
    detail: "Text, image, and audio carrier attacks — not just text.",
  },
  {
    icon: Bell,
    claim: "Real-time alerts",
    detail: "Slack notifications when new threats break your stack.",
  },
  {
    icon: FileCheck,
    claim: "Audit-ready reporting",
    detail: (
      <>
        Risk scores, findings, a remediation trail, and a CISO executive summary
        — compliance-supporting evidence.{" "}
        <span className="text-foreground/80">
          SOC 2 / ISO 27001: <RoadmapTag />.
        </span>
      </>
    ),
  },
  {
    icon: Workflow,
    claim: "Integrated where you work",
    detail: (
      <>
        MCP for IDEs (Claude Desktop, Cursor), Slack + Jira today; SOAR/SIEM
        (Splunk, Palo Alto) <ComingSoonTag />; REST API + Python SDK for custom
        wiring.
      </>
    ),
  },
]

/** Small mono pill marking a capability as not-yet-shipped. */
function RoadmapTag() {
  return (
    <span className="inline-flex items-center rounded-sm border border-border bg-background/60 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
      on the roadmap
    </span>
  )
}

function ComingSoonTag() {
  return (
    <span className="inline-flex items-center rounded-sm border border-border bg-background/60 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
      coming soon
    </span>
  )
}

/**
 * EnterprisePitch — "ROGUE for Enterprises" pitch section.
 *
 * Renders as a top-level <section> inside the shared max-w-7xl container, so it
 * can be dropped directly onto a marketing page. Server component. Dark terminal
 * aesthetic: mono rogue-green eyebrow, rogue-card feature rows, two CTAs.
 */
export function EnterprisePitch({ className }: EnterprisePitchProps) {
  return (
    <section className={cn("max-w-7xl mx-auto px-6", className)}>
      <div className="max-w-3xl space-y-4">
        <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
          For enterprises
        </p>
        <h2 className="text-3xl md:text-4xl font-bold tracking-tight">
          A security platform for teams deploying LLMs at scale.
        </h2>
        <p className="text-base text-muted-foreground leading-relaxed">
          Everything you need to find, triage, and route LLM jailbreaks before
          they reach production — wired into the tools your team already uses.
        </p>
      </div>

      <ul className="mt-10 md:mt-12 grid gap-4 sm:grid-cols-2">
        {FEATURES.map(({ icon: Icon, claim, detail }) => (
          <li
            key={claim}
            className={cn(
              "rogue-card flex gap-4 rounded-xl border border-border bg-card/40 p-5 backdrop-blur-sm md:p-6"
            )}
          >
            <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-background/60 text-rogue-green">
              <Icon className="h-[18px] w-[18px]" />
            </span>
            <div className="min-w-0">
              <h3 className="text-base font-semibold tracking-tight text-foreground">
                {claim}
              </h3>
              <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
                {detail}
              </p>
            </div>
          </li>
        ))}
      </ul>

      <div className="mt-10 flex flex-col sm:flex-row gap-3 md:gap-4">
        <Link
          href="/request-demo"
          className={cn(
            "inline-flex items-center justify-center rounded-lg px-6 py-3",
            "bg-rogue-green text-black font-mono text-sm font-bold tracking-[0.15em] uppercase",
            "transition-opacity hover:opacity-90",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rogue-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          )}
        >
          Request a demo
        </Link>
        <Link
          href={COMMERCIAL ? "/pricing" : "/early-access"}
          className={cn(
            "inline-flex items-center justify-center rounded-lg px-6 py-3 border border-border",
            "font-mono text-sm font-bold tracking-[0.15em] uppercase text-foreground",
            "transition-colors hover:border-rogue-green hover:text-rogue-green",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rogue-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          )}
        >
          {COMMERCIAL ? "See pricing" : "Early access"}
        </Link>
      </div>
    </section>
  )
}
