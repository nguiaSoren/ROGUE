import Link from "next/link";
import { notFound } from "next/navigation";
import {
  ArrowRight,
  Server,
  Cloud,
  TerminalSquare,
  Plug,
  ShieldCheck,
  Boxes,
  Crosshair,
  Scale,
  FileCheck,
  Radar,
  FileText,
  type LucideIcon,
} from "lucide-react";

import { Section } from "@/components/marketing/section";
import { StatCard } from "@/components/marketing/stat-card";
import { CtaRow } from "@/components/marketing/cta-row";
import { EnterprisePitch } from "@/components/marketing/enterprise-pitch";
import { PROOF_POINTS } from "@/lib/proof";
import { COMMERCIAL } from "@/lib/flags";
import { cn } from "@/lib/utils";

export const metadata = {
  title: "Enterprise, ROGUE",
  description:
    "Continuous, private, enterprise-grade LLM red-teaming. Deploy ROGUE self-hosted inside your perimeter, as managed SaaS, via the Python SDK in CI, or as a live MCP server your IDE queries directly.",
};

/**
 * /enterprise, the deployment-modes page. Sells how an org runs ROGUE:
 * private/self-hosted, hosted SaaS, SDK-in-CI, or MCP server.
 *
 * Server component. All content is static; the only dynamic-flavoured bits are
 * the proof numbers, imported from the single source of truth in @/lib/proof.
 */
export default function EnterprisePage() {
  // Commercial-pitch page: hidden (404) in the default honest hiring mode, shown
  // only when NEXT_PUBLIC_SHOW_COMMERCIAL=true, same gating as /pricing.
  if (!COMMERCIAL) notFound();

  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="space-y-20 md:space-y-28 py-20 md:py-28">
        {/* 1. HERO ----------------------------------------------------- */}
        <Section className="animate-rogue-fade-up">
          <div className="max-w-3xl space-y-6">
            <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
              enterprise
            </p>
            <h1 className="text-3xl sm:text-4xl md:text-6xl font-bold tracking-tight leading-[1.05]">
              Red-team your AI at the scale your org runs it.
            </h1>
            <p className="text-base md:text-lg text-muted-foreground leading-relaxed max-w-2xl">
              ROGUE is a continuous, private, enterprise-grade red-team for the
              LLM systems you ship. Point it at your deployments and it harvests
              live open-web jailbreaks, reproduces them against your exact model
              × system-prompt × tools, and hands you a graded report, on your
              infrastructure or ours.
            </p>
            <CtaRow className="pt-2" />
          </div>
        </Section>

        {/* 1b. ENTERPRISE PITCH, honest feature checklist ------------ */}
        <EnterprisePitch className="animate-rogue-fade-up" />

        {/* 2. FOUR DEPLOYMENT MODES ----------------------------------- */}
        <Section
          eyebrow="deployment modes"
          title="Four ways to run ROGUE."
          lede="Same engine, four delivery shapes, pick the one that fits your perimeter, your pipeline, and your team."
          className="animate-rogue-fade-up"
        >
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 md:gap-5">
            {DEPLOYMENT_MODES.map((mode) => (
              <DeploymentCard key={mode.title} {...mode} />
            ))}
          </div>
        </Section>

        {/* 3. ARCHITECTURE DIAGRAM ------------------------------------ */}
        <Section
          eyebrow="how it flows"
          title="One straight line from endpoint to report."
          lede="No agents to babysit, no pipeline to assemble. ROGUE takes a target, runs the attacks, scores what breaks, and ships the artifact."
          className="animate-rogue-fade-up"
        >
          <ArchitectureFlow />
        </Section>

        {/* 4. BUILT FOR ----------------------------------------------- */}
        <Section
          eyebrow="built for"
          title="The teams who own the risk."
          lede="ROGUE speaks to everyone on the hook for an AI system in production, not just one of them."
          className="animate-rogue-fade-up"
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {PERSONAS.map((persona) => (
              <PersonaCard key={persona.title} {...persona} />
            ))}
          </div>
        </Section>

        {/* 5. PROOF BAND ---------------------------------------------- */}
        <Section
          eyebrow="this is a real engine"
          title="Numbers, not adjectives."
          lede="Every figure traces to the corpus, the judge calibration, and the live scheduler, not a pitch deck."
          className="animate-rogue-fade-up"
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {PROOF_POINTS.map((point) => (
              <StatCard
                key={point.label}
                value={point.value}
                label={point.label}
                sublabel={point.sublabel}
              />
            ))}
          </div>
        </Section>

        {/* 6. CLOSING ------------------------------------------------- */}
        <Section className="animate-rogue-fade-up">
          <div className="rogue-card border border-border rounded-xl p-8 md:p-12 bg-card/40 backdrop-blur-sm space-y-6">
            <h2 className="text-3xl md:text-4xl font-bold tracking-tight max-w-2xl">
              Bring ROGUE to your stack.
            </h2>
            <p className="text-[17px] text-foreground leading-relaxed max-w-2xl">
              Tell us your deployment shape and we&apos;ll spin up the right
              mode. For how we handle your data and credentials, see{" "}
              <Link
                href="/security"
                className="text-rogue-green hover:underline underline-offset-4"
              >
                Security
              </Link>
              . Or apply for{" "}
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

// --------------------------------------------------------------------------
// Deployment modes
// --------------------------------------------------------------------------

interface DeploymentMode {
  icon: LucideIcon;
  title: string;
  description: string;
  specifics: string[];
  /** Signature mode (MCP) gets the highlighted treatment. */
  featured?: boolean;
}

const DEPLOYMENT_MODES: DeploymentMode[] = [
  {
    icon: Server,
    title: "Private / self-hosted",
    description:
      "ROGUE runs entirely inside your perimeter. Prompts, responses, and findings never leave your network.",
    specifics: [
      "Deploys into your VPC or on-prem cluster",
      "No customer data egress, air-gap friendly",
      "Bring your own keys for every model panel",
    ],
  },
  {
    icon: Cloud,
    title: "Hosted",
    description:
      "Managed SaaS. You register your endpoints and system prompts; we run the infrastructure, with hard org isolation per tenant.",
    specifics: [
      "Zero ops, scans run on our cluster",
      "Per-org isolation, no cross-tenant data",
      "Daily threat-brief diff out of the box",
    ],
  },
  {
    icon: TerminalSquare,
    title: "SDK",
    description:
      "pip install the Python SDK and wire red-teaming straight into your CI and eval pipelines, fail the build when a new jailbreak lands.",
    specifics: [
      "First-class Python client (ships in this repo)",
      "Frozen v1 contract, stable across releases",
      "Drop into CI as a pass/fail gate",
    ],
  },
  {
    icon: Plug,
    title: "MCP server",
    description:
      "ROGUE exposes its own MCP server, so Claude Desktop, Cursor, and Windsurf query the live threat DB directly, the signature ROGUE move.",
    specifics: [
      "Ask your IDE about the threat DB in natural language",
      "Live primitives, breach matrix, and threat briefs as tools",
      "One-click connect, no glue code to write",
    ],
    featured: true,
  },
];

function DeploymentCard({
  icon: Icon,
  title,
  description,
  specifics,
  featured,
}: DeploymentMode) {
  return (
    <div
      className={cn(
        "rogue-card border rounded-xl p-6 md:p-7 bg-card/40 backdrop-blur-sm flex flex-col gap-4",
        featured ? "border-rogue-green/60" : "border-border"
      )}
    >
      <div className="flex items-center gap-3">
        <span
          className={cn(
            "inline-flex items-center justify-center w-10 h-10 rounded-lg border",
            featured
              ? "border-rogue-green/50 text-rogue-green bg-rogue-green/5"
              : "border-border text-rogue-green"
          )}
        >
          <Icon className="w-5 h-5" aria-hidden="true" />
        </span>
        <div className="flex items-center gap-2">
          <h3 className="text-lg md:text-xl font-bold tracking-tight">{title}</h3>
          {featured && (
            <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-rogue-green border border-rogue-green/40 rounded px-1.5 py-0.5">
              signature
            </span>
          )}
        </div>
      </div>
      <p className="text-sm text-muted-foreground leading-relaxed">
        {description}
      </p>
      <ul className="mt-auto space-y-2">
        {specifics.map((spec) => (
          <li key={spec} className="flex items-start gap-2 text-sm">
            <ArrowRight
              className="w-3.5 h-3.5 mt-1 shrink-0 text-rogue-green"
              aria-hidden="true"
            />
            <span className="text-muted-foreground">{spec}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// --------------------------------------------------------------------------
// Architecture flow
// --------------------------------------------------------------------------

interface FlowNode {
  icon: LucideIcon;
  label: string;
  sublabel: string;
}

const FLOW_NODES: FlowNode[] = [
  { icon: Boxes, label: "Your LLM endpoint", sublabel: "model × prompt × tools" },
  { icon: Radar, label: "ROGUE scanner", sublabel: "harvest → reproduce" },
  { icon: ShieldCheck, label: "Findings", sublabel: "judge-v3 graded" },
  { icon: FileText, label: "Report", sublabel: "threat-brief diff" },
];

function ArchitectureFlow() {
  return (
    <div className="rogue-card border border-border rounded-xl p-6 md:p-10 bg-card/40 backdrop-blur-sm">
      <div className="flex flex-col md:flex-row md:items-stretch gap-4 md:gap-2">
        {FLOW_NODES.map((node, i) => (
          <div
            key={node.label}
            className="flex flex-col md:flex-row md:items-stretch gap-4 md:gap-2 md:flex-1"
          >
            <div className="flex-1 rounded-lg border border-border bg-background/60 p-5 flex flex-col items-center text-center gap-2">
              <span className="inline-flex items-center justify-center w-11 h-11 rounded-lg border border-rogue-green/30 text-rogue-green bg-rogue-green/5">
                <node.icon className="w-5 h-5" aria-hidden="true" />
              </span>
              <span className="text-sm font-bold tracking-tight">
                {node.label}
              </span>
              <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                {node.sublabel}
              </span>
            </div>
            {i < FLOW_NODES.length - 1 && (
              <div className="flex items-center justify-center text-rogue-green shrink-0">
                <ArrowRight className="w-6 h-6 rotate-90 md:rotate-0" aria-hidden="true" />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------
// Personas
// --------------------------------------------------------------------------

interface Persona {
  icon: LucideIcon;
  title: string;
  blurb: string;
}

const PERSONAS: Persona[] = [
  {
    icon: Boxes,
    title: "AI Product Teams",
    blurb:
      "Ship features knowing exactly how your assistant breaks before users find out.",
  },
  {
    icon: ShieldCheck,
    title: "Security Teams",
    blurb:
      "A continuous, attacker-realistic view of your LLM attack surface, not a one-off pentest.",
  },
  {
    icon: Crosshair,
    title: "Red Teams",
    blurb:
      "A live arsenal of reproduced jailbreaks and prompt-injections to run against any target.",
  },
  {
    icon: Scale,
    title: "Model Risk Teams",
    blurb:
      "Quantified, judge-calibrated breach rates per deployment to feed model-risk reviews.",
  },
  {
    icon: FileCheck,
    title: "Compliance Teams",
    blurb:
      "Dated, exportable evidence of ongoing red-team coverage for audits and attestations.",
  },
];

function PersonaCard({ icon: Icon, title, blurb }: Persona) {
  return (
    <div className="rogue-card border border-border rounded-xl p-5 bg-card/40 backdrop-blur-sm flex flex-col gap-3">
      <span className="inline-flex items-center justify-center w-9 h-9 rounded-lg border border-border text-rogue-green">
        <Icon className="w-4 h-4" aria-hidden="true" />
      </span>
      <h3 className="text-base font-bold tracking-tight">{title}</h3>
      <p className="text-sm text-muted-foreground leading-relaxed">{blurb}</p>
    </div>
  );
}
