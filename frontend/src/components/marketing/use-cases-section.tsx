import Link from "next/link"
import { ArrowRight, Code2, ShieldCheck, Briefcase } from "lucide-react"

import { cn } from "@/lib/utils"
import { Section } from "@/components/marketing/section"

/**
 * UseCasesSection, "Who uses ROGUE?" persona grid.
 *
 * Three honest persona cards (LLM Engineers, Security Teams, CTOs & CISOs),
 * each with a Problem line and a Solution line, plus a closing link to the
 * product page. Server component; carries its own eyebrow + heading via the
 * shared <Section>. Drop directly into any page, it owns its container
 * padding through <Section>.
 *
 * Honesty constraints baked into copy (do not loosen):
 *   - SOAR/SIEM (Splunk, Palo Alto) = coming soon, not integrated today.
 *   - Compliance = audit-ready evidence + roadmap, never "certified".
 *   - No SLA guarantees, no customer claims.
 */
export function UseCasesSection({ className }: { className?: string }) {
  return (
    <Section
      eyebrow="use cases"
      title="Who uses ROGUE?"
      className={className}
    >
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {personas.map((p) => (
          <PersonaCard key={p.title} {...p} />
        ))}
      </div>

      <div className="mt-8">
        <Link
          href="/product"
          className="inline-flex items-center gap-1.5 font-mono text-sm text-rogue-green transition-colors hover:text-rogue-green/80"
        >
          See how ROGUE works
          <ArrowRight className="h-4 w-4" />
        </Link>
      </div>
    </Section>
  )
}

/* ------------------------------------------------------------------ */
/*  Persona content                                                    */
/* ------------------------------------------------------------------ */

interface Persona {
  icon: React.ComponentType<{ className?: string }>
  title: string
  problem: string
  solution: string
}

const personas: Persona[] = [
  {
    icon: Code2,
    title: "LLM Engineers",
    problem:
      "Your model keeps getting jailbroken and you don't know how to patch it.",
    solution:
      "ROGUE automatically tests your deployment against the latest attacks and tells you exactly which break it, with remediation for each.",
  },
  {
    icon: ShieldCheck,
    title: "Security Teams",
    problem:
      "Manual red-teaming is slow and expensive, and the threat landscape moves daily.",
    solution:
      "ROGUE continuously harvests the open web and re-tests your deployment in periodic measured runs, delivering a threat-brief diff; Slack + Jira today, SOAR/SIEM (Splunk, Palo Alto) coming soon.",
  },
  {
    icon: Briefcase,
    title: "CTOs & CISOs",
    problem:
      "You need risk visibility and compliance evidence for your LLM deployments.",
    solution:
      "ROGUE produces audit-ready risk reports and a CISO executive summary; RBAC and private deployment for sensitive environments. SOC 2 / ISO 27001 on the roadmap.",
  },
]

/* ------------------------------------------------------------------ */
/*  Persona card                                                       */
/* ------------------------------------------------------------------ */

function PersonaCard({ icon: Icon, title, problem, solution }: Persona) {
  return (
    <div
      className={cn(
        "rogue-card flex flex-col rounded-xl border border-border bg-card/40 p-6 backdrop-blur-sm"
      )}
    >
      <span className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-border bg-background/60 text-rogue-green">
        <Icon className="h-5 w-5" />
      </span>

      <h3 className="mt-4 text-lg font-semibold tracking-tight text-foreground">
        {title}
      </h3>

      <dl className="mt-4 space-y-3">
        <div>
          <dt className="font-mono text-[10px] uppercase tracking-[0.18em] text-rogue-red">
            Problem
          </dt>
          <dd className="mt-1 text-sm leading-relaxed text-muted-foreground">
            {problem}
          </dd>
        </div>
        <div>
          <dt className="font-mono text-[10px] uppercase tracking-[0.18em] text-rogue-green">
            Solution
          </dt>
          <dd className="mt-1 text-sm leading-relaxed text-foreground/90">
            {solution}
          </dd>
        </div>
      </dl>
    </div>
  )
}
