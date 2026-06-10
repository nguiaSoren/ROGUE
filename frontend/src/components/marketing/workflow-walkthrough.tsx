import { ArrowRight, PlugZap, Layers, ShieldAlert, Ticket } from "lucide-react"

import { cn } from "@/lib/utils"
import { ProviderLogo } from "@/components/ui/provider-logo"

/**
 * WorkflowWalkthrough, a self-contained, concrete end-to-end product story:
 *
 *   Connect endpoint → Run ladder scan → Find the jailbreak → Ticket auto-filed
 *
 * Renders as a `w-full` block (no outer page padding) so it can be dropped
 * directly inside a <Section> or any max-w container. Carries its own eyebrow +
 * heading so it also reads fine standalone. All visuals are local mini-mocks, 
 * no dependency on dashboard / findings / report preview components. The data is
 * representative, not a real customer.
 */
export function WorkflowWalkthrough({ className }: { className?: string }) {
  return (
    <div className={cn("w-full", className)}>
      <div className="max-w-3xl space-y-4">
        <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
          How it works
        </p>
        <h2 className="text-3xl md:text-4xl font-bold tracking-tight">
          From endpoint to filed ticket in four steps
        </h2>
        <p className="text-[17px] text-foreground leading-relaxed">
          Point ROGUE at a model, escalate every goal through the full arsenal,
          and let the criticals route themselves to your tracker.
        </p>
      </div>

      <ol
        className={cn(
          "mt-10 md:mt-12 grid gap-4",
          "grid-cols-1 lg:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr]",
          "items-stretch"
        )}
      >
        <Step
          index="01"
          icon={PlugZap}
          title="Connect your endpoint"
          detail="Point ROGUE at any OpenAI-compatible endpoint."
          visual={<ConnectVisual />}
        />
        <Connector />

        <Step
          index="02"
          icon={Layers}
          title="Run a ladder scan"
          detail="Escalate each goal through the full arsenal, graduated techniques, multi-turn, multimodal."
          visual={<LadderVisual />}
        />
        <Connector />

        <Step
          index="03"
          icon={ShieldAlert}
          accent="red"
          title="Find the jailbreak"
          detail="ROGUE surfaces exactly which attacks break it, with evidence."
          visual={<BreachVisual />}
        />
        <Connector />

        <Step
          index="04"
          icon={Ticket}
          title="Ticket auto-filed"
          detail="Criticals flow straight to Jira/Slack via the MCP integration."
          visual={<TicketVisual />}
        />
      </ol>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Step card                                                          */
/* ------------------------------------------------------------------ */

function Step({
  index,
  icon: Icon,
  title,
  detail,
  visual,
  accent = "green",
}: {
  index: string
  icon: React.ComponentType<{ className?: string }>
  title: string
  detail: string
  visual: React.ReactNode
  accent?: "green" | "red"
}) {
  const accentText = accent === "red" ? "text-rogue-red" : "text-rogue-green"
  return (
    <li
      className={cn(
        "rogue-card flex flex-col rounded-xl border border-border bg-card/40 p-5 backdrop-blur-sm",
        accent === "red" && "rogue-card-critical"
      )}
    >
      <div className="flex items-center justify-between">
        <span
          className={cn(
            "inline-flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-background/60",
            accentText
          )}
        >
          <Icon className="h-[18px] w-[18px]" />
        </span>
        <span className="font-mono text-2xl font-bold tracking-tight text-muted-foreground/40">
          {index}
        </span>
      </div>

      <h3 className="mt-4 text-lg font-semibold tracking-tight text-foreground">
        {title}
      </h3>
      <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
        {detail}
      </p>

      <div className="mt-4">{visual}</div>
    </li>
  )
}

/* ------------------------------------------------------------------ */
/*  Connector arrow, horizontal on lg, rotated down on mobile        */
/* ------------------------------------------------------------------ */

function Connector() {
  return (
    <li
      aria-hidden
      className="flex items-center justify-center py-1 lg:py-0"
    >
      <ArrowRight className="h-5 w-5 rotate-90 text-rogue-green/60 lg:rotate-0" />
    </li>
  )
}

/* ------------------------------------------------------------------ */
/*  Step visuals (local mini-mocks)                                   */
/* ------------------------------------------------------------------ */

function EndpointChip({
  model,
  label,
}: {
  model: string | null
  label: string
}) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background/60 px-2 py-1 font-mono text-[11px] text-foreground/80">
      {model ? (
        <ProviderLogo model={model} className="text-foreground/70" />
      ) : (
        <span className="inline-block h-2 w-2 rounded-sm bg-rogue-green/70" />
      )}
      {label}
    </span>
  )
}

function ConnectVisual() {
  return (
    <div className="flex flex-wrap gap-1.5">
      <EndpointChip model="openai/gpt-5" label="OpenAI" />
      <EndpointChip model="anthropic/claude" label="Anthropic" />
      <EndpointChip model="google/gemini" label="Gemini" />
      <EndpointChip model={null} label="Custom API" />
    </div>
  )
}

function LadderVisual() {
  const tiers = [
    { label: "Direct", w: "30%" },
    { label: "Graduated", w: "52%" },
    { label: "Multi-turn", w: "74%" },
    { label: "Multimodal", w: "100%" },
  ]
  return (
    <div className="space-y-1.5 font-mono text-[10px]">
      {tiers.map((t, i) => (
        <div key={t.label} className="flex items-center gap-2">
          <span className="w-16 shrink-0 text-muted-foreground">{t.label}</span>
          <span className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-background/70">
            <span
              className="absolute inset-y-0 left-0 rounded-full bg-rogue-green/70"
              style={{ width: t.w, opacity: 0.45 + i * 0.18 }}
            />
          </span>
        </div>
      ))}
    </div>
  )
}

function BreachVisual() {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-rogue-red/40 bg-rogue-red/5 px-2.5 py-1.5 font-mono text-[11px]">
      <span className="inline-block h-2 w-2 shrink-0 rounded-full bg-rogue-red animate-rogue-pulse-critical" />
      <span className="text-foreground/90">Crescendo</span>
      <span className="text-muted-foreground/50">·</span>
      <span className="font-semibold text-rogue-red">CRITICAL</span>
      <span className="text-muted-foreground/50">·</span>
      <span className="text-muted-foreground">breached 4/5</span>
    </div>
  )
}

function TicketVisual() {
  return (
    <div className="rounded-md border border-border bg-background/60 p-2.5">
      <div className="flex items-center justify-between font-mono text-[10px]">
        <span className="font-semibold text-foreground/80">ROGUE-142</span>
        <span className="rounded-sm border border-rogue-red/40 bg-rogue-red/10 px-1.5 py-0.5 font-semibold text-rogue-red">
          Critical
        </span>
      </div>
      <div className="mt-1.5 text-[12px] font-medium leading-snug text-foreground">
        Crescendo bypass
      </div>
      <div className="mt-1 flex items-center gap-1.5 font-mono text-[10px] text-muted-foreground">
        <span className="inline-block h-1.5 w-1.5 rounded-sm bg-rogue-green" />
        filed via MCP → Jira
      </div>
    </div>
  )
}
