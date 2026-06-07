import Link from "next/link"
import {
  ArrowRight,
  Code2,
  MessageSquare,
  ShieldCheck,
  Terminal,
} from "lucide-react"

import { Section } from "@/components/marketing/section"
import { cn } from "@/lib/utils"

/**
 * IntegrationsSection, enterprise-friendly reframing of the MCP pitch.
 *
 * Instead of leading with "we expose an MCP server" jargon, this groups
 * ROGUE's connection points by the tools a security/eng team already uses:
 * IDEs, chat, security tooling, and the raw API/SDK. The MCP differentiator
 * stays, phrased plainly ("ROGUE is its own connector, so an agent inside
 * your editor can run a whole scan"), rather than fronting the acronym.
 *
 * HONESTY: SOAR/SIEM (Splunk, Palo Alto) is NOT live today and is badged
 * "Coming soon". Everything else listed is real and available now.
 *
 * Server component. Drops into the marketing page like any other <Section>.
 */
export function IntegrationsSection({ className }: { className?: string }) {
  return (
    <Section
      eyebrow="integrations"
      title="Connects to the tools your team already uses."
      lede="ROGUE meets your workflow where it lives, your editor, your chat, your tracker, your own services. It runs as a connector your AI agents can call directly, so a full scan is one command away from wherever you work."
      className={className}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {GROUPS.map((group) => (
          <IntegrationCard key={group.title} {...group} />
        ))}
      </div>

      <div className="mt-8">
        <Link
          href="/product"
          className="inline-flex items-center gap-1.5 font-mono text-sm text-rogue-green transition-colors hover:text-rogue-green/80"
        >
          View the product tour
          <ArrowRight className="h-4 w-4" />
        </Link>
      </div>
    </Section>
  )
}

/* ------------------------------------------------------------------ */
/*  Content                                                            */
/* ------------------------------------------------------------------ */

type Availability = "now" | "soon"

interface Group {
  icon: React.ComponentType<{ className?: string }>
  title: string
  availability: Availability
  /** Plain-language description of the capability. */
  detail: string
  /** Named tools shown as chips. */
  tools: string[]
}

const GROUPS: Group[] = [
  {
    icon: Terminal,
    title: "Your IDE",
    availability: "now",
    detail:
      "One-click setup in Claude Desktop, Cursor, Windsurf, and VS Code. ROGUE acts as a connector, so an AI agent inside your editor can launch and read back a whole scan without leaving your work.",
    tools: ["Claude Desktop", "Cursor", "Windsurf", "VS Code"],
  },
  {
    icon: MessageSquare,
    title: "Your chat & tracker",
    availability: "now",
    detail:
      "Daily threat briefs and breach alerts land in Slack. Every critical finding is auto-filed as a Jira ticket, your team triages where it already works.",
    tools: ["Slack", "Jira"],
  },
  {
    icon: ShieldCheck,
    title: "Security tooling",
    availability: "soon",
    detail:
      "SOAR / SIEM connectors to pipe findings into your existing security stack. On the roadmap, not available today.",
    tools: ["Splunk", "Palo Alto"],
  },
  {
    icon: Code2,
    title: "API & SDK",
    availability: "now",
    detail:
      "A REST /v1 API and a Python SDK for anything bespoke, wire ROGUE into your own pipelines, dashboards, and CI.",
    tools: ["REST /v1", "Python SDK"],
  },
]

/* ------------------------------------------------------------------ */
/*  Card                                                               */
/* ------------------------------------------------------------------ */

function IntegrationCard({ icon: Icon, title, availability, detail, tools }: Group) {
  return (
    <div className="rogue-card flex flex-col rounded-xl border border-border bg-card/40 p-6 backdrop-blur-sm">
      <div className="flex items-center justify-between gap-3">
        <span className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-border bg-background/60 text-rogue-green">
          <Icon className="h-5 w-5" />
        </span>
        <AvailabilityBadge availability={availability} />
      </div>

      <h3 className="mt-4 text-lg font-semibold tracking-tight text-foreground">
        {title}
      </h3>
      <p className="mt-1.5 flex-1 text-sm leading-relaxed text-muted-foreground">
        {detail}
      </p>

      <ul className="mt-4 flex flex-wrap gap-1.5">
        {tools.map((tool) => (
          <li
            key={tool}
            className={cn(
              "rounded-md border border-border bg-background/60 px-2 py-1 font-mono text-[11px] text-foreground/80",
              availability === "soon" && "text-muted-foreground/70"
            )}
          >
            {tool}
          </li>
        ))}
      </ul>
    </div>
  )
}

function AvailabilityBadge({ availability }: { availability: Availability }) {
  if (availability === "soon") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-background/60 px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-muted-foreground/50" />
        Coming soon
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-rogue-green/30 bg-rogue-green/5 px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.12em] text-rogue-green">
      <span className="inline-block h-1.5 w-1.5 rounded-full bg-rogue-green" />
      Available now
    </span>
  )
}
