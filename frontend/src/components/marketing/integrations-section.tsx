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

      <div className="mt-8 flex flex-col sm:flex-row sm:items-center gap-x-6 gap-y-3">
        <Link
          href="/early-access"
          className="inline-flex items-center gap-1.5 font-mono text-sm text-rogue-green transition-colors hover:text-rogue-green/80"
        >
          Get ROGUE set up on your stack
          <ArrowRight className="h-4 w-4" />
        </Link>
        <Link
          href="/product"
          className="inline-flex items-center gap-1.5 font-mono text-sm text-muted-foreground transition-colors hover:text-rogue-green"
        >
          View the product tour
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
  /**
   * Concrete proof artifact under the tools. `live: true` means a genuinely
   * public, reachable endpoint (rendered with a green pulse) — only the MCP
   * server and the REST API qualify, both verified live. Slack/Jira are
   * per-customer (you wire your own workspace), so their proof is a SAMPLE of
   * the delivered message with `live` omitted (no pulse), never a fabricated
   * public URL. The SDK has no proof: it is not publicly installable yet.
   */
  proof?: { badge: string; value: string; live?: boolean }
  /** Where clicking the tile goes. Omitted = inert (e.g. a Coming-soon tile). */
  href?: string
}

const GROUPS: Group[] = [
  {
    icon: Terminal,
    title: "Your IDE",
    availability: "now",
    detail:
      "Add one config block in Claude Desktop, Cursor, Windsurf, or VS Code. Connect keyless and your editor's AI agent queries ROGUE's live threat DB on the spot; add an account for the full scan dashboard, reports, and the key-authorized /v1 API.",
    tools: ["Claude Desktop", "Cursor", "Windsurf", "VS Code"],
    proof: {
      badge: "live · keyless",
      value: "https://rogue-private.onrender.com/mcp",
      live: true,
    },
    href: "/product#mcp",
  },
  {
    icon: MessageSquare,
    title: "Your chat & tracker",
    availability: "now",
    detail:
      "Slack alerts work today via an incoming webhook — the daily threat brief plus every CRITICAL/HIGH breach posts to your workspace. Connect Slack or Jira as a per-org integration and deliver findings through the MCP action tools; automatic fan-out on every scan completion is rolling out.",
    tools: ["Slack", "Jira"],
    proof: {
      badge: "lands in your channel",
      value: "ROGUE · score 68 · 4/14 breached · top: Crescendo (CRITICAL) · View report ↗",
    },
    href: "/product",
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
      "A documented REST /v1 API, live now with a public OpenAPI spec; an API key authorizes the calls. A Python SDK speaks the same v1 contract for wiring ROGUE into your pipelines, dashboards, and CI.",
    tools: ["REST /v1", "Python SDK"],
    proof: {
      badge: "live · OpenAPI",
      value: "https://rogue-private.onrender.com/v1",
      live: true,
    },
    href: "/early-access",
  },
]

/* ------------------------------------------------------------------ */
/*  Card                                                               */
/* ------------------------------------------------------------------ */

function IntegrationCard({ icon: Icon, title, availability, detail, tools, proof, href }: Group) {
  const cardClass =
    "rogue-card flex flex-col rounded-xl border border-border bg-card/40 p-6 backdrop-blur-sm"
  const inner = (
    <>
      <div className="flex items-center justify-between gap-3">
        <span className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-border bg-background/60 text-rogue-green">
          <Icon className="h-5 w-5" />
        </span>
        <AvailabilityBadge availability={availability} />
      </div>

      <h3 className="mt-4 flex items-center gap-1.5 text-lg font-semibold tracking-tight text-foreground group-hover:text-rogue-green transition-colors">
        {title}
        {href && (
          <ArrowRight className="h-4 w-4 opacity-0 -translate-x-1 transition-all group-hover:opacity-100 group-hover:translate-x-0" />
        )}
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

      {/* Concrete proof artifact. Display-only (the card itself is the link), so
          nothing interactive nests inside the anchor. A green pulse + green band
          is reserved for genuinely-live public endpoints (proof.live); per-customer
          samples (Slack/Jira) render flat, so we never imply a public URL. */}
      {proof && (
        <div
          className={cn(
            "mt-4 flex items-center gap-2 rounded-md border px-2.5 py-2",
            proof.live
              ? "border-rogue-green/30 bg-rogue-green/[0.04]"
              : "border-border bg-background/60"
          )}
        >
          <span
            className={cn(
              "inline-flex shrink-0 items-center gap-1.5 font-mono text-[9px] uppercase tracking-[0.14em]",
              proof.live ? "text-rogue-green" : "text-muted-foreground"
            )}
          >
            {proof.live && (
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-rogue-green animate-rogue-pulse-green" />
            )}
            {proof.badge}
          </span>
          <code className="min-w-0 flex-1 truncate font-mono text-[11px] text-foreground/80">
            {proof.value}
          </code>
        </div>
      )}
    </>
  )

  // Linked tiles (everything real) jump to the relevant next step; the
  // Coming-soon tile (no href) stays inert, so nothing dead-ends or overpromises.
  if (href) {
    return (
      <Link
        href={href}
        className={cn(cardClass, "group block transition-colors hover:border-rogue-green/40")}
      >
        {inner}
      </Link>
    )
  }
  return <div className={cardClass}>{inner}</div>
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
