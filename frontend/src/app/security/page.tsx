import Link from "next/link";
import { notFound } from "next/navigation";
import {
  Shield,
  Lock,
  KeyRound,
  EyeOff,
  FileText,
  ServerOff,
  Trash2,
  Building2,
  ArrowRight,
} from "lucide-react";
import { Section } from "@/components/marketing/section";
import { CtaRow } from "@/components/marketing/cta-row";
import { COMMERCIAL } from "@/lib/flags";

export const metadata = {
  title: "Security, ROGUE",
  description:
    "How ROGUE keeps your data safe: encrypted secrets, organization isolation, no stored model weights, audit logging, and least-privilege access. ROGUE is the attacker side, it tests your endpoint over the API.",
};

/**
 * /security, answers "can I safely point this at production AI?" before a
 * buyer has to ask. Describes genuine, defensible posture only; compliance
 * (SOC2 etc.) is framed as roadmap, never claimed. Server component.
 */
export default function SecurityPage() {
  // Commercial-pitch page: hidden (404) in the default honest hiring mode, shown
  // only when NEXT_PUBLIC_SHOW_COMMERCIAL=true, same gating as /pricing.
  if (!COMMERCIAL) notFound();

  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="space-y-20 md:space-y-28 py-16 md:py-24">
        {/* 1. HERO ---------------------------------------------------------- */}
        <Section
          eyebrow="security & trust"
          title="Built to be safe to point at production AI."
          lede="ROGUE attacks your model so you can patch it before someone else does, which means it has to be trustworthy with the credentials and responses it touches. Here's exactly how your data is handled, and why ROGUE never needs your model weights or training data."
        />

        {/* 2. SECURITY POSTURE GRID --------------------------------------- */}
        <Section eyebrow="how we handle your data" title="Security posture.">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {POSTURE.map((p) => (
              <div
                key={p.title}
                className="rogue-card border border-border rounded-xl p-5 md:p-6 bg-card/40 backdrop-blur-sm"
              >
                <p.icon
                  className="h-6 w-6 text-rogue-green"
                  strokeWidth={1.75}
                  aria-hidden
                />
                <h3 className="mt-4 text-lg font-bold tracking-tight">
                  {p.title}
                </h3>
                <p className="mt-2 text-sm text-muted-foreground leading-relaxed">
                  {p.body}
                </p>
              </div>
            ))}
          </div>
        </Section>

        {/* 3. HOW A SCAN HANDLES YOUR DATA -------------------------------- */}
        <Section
          eyebrow="data flow"
          title="How a scan handles your data."
          lede="ROGUE is the attacker side of the test. It needs inference access to the endpoint you point it at, nothing more. No training data, no model weights, no source code."
        >
          <ol className="space-y-3">
            {FLOW.map((step, i) => (
              <li
                key={step.title}
                className="rogue-card border border-border rounded-xl p-5 bg-card/40 backdrop-blur-sm flex gap-4"
              >
                <span className="font-mono text-sm font-bold text-rogue-green shrink-0 mt-0.5 tabular-nums">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <div>
                  <p className="text-base font-semibold text-foreground">
                    {step.title}
                  </p>
                  <p className="mt-1 text-sm text-muted-foreground leading-relaxed">
                    {step.body}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </Section>

        {/* 4. RESPONSIBLE DISCLOSURE -------------------------------------- */}
        <Section
          eyebrow="responsible disclosure"
          title="Found a vulnerability in ROGUE?"
          lede="ROGUE is itself a security tool, and we hold ourselves to the same standard we help you meet. If you believe you've found a security issue in ROGUE, please tell us before disclosing it publicly."
        >
          <div className="rogue-card border border-border rounded-xl p-6 md:p-8 bg-card/40 backdrop-blur-sm max-w-2xl space-y-4">
            <div className="flex items-center gap-3">
              <Shield
                className="h-5 w-5 text-rogue-green"
                strokeWidth={1.75}
                aria-hidden
              />
              <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
                reporting a vulnerability
              </p>
            </div>
            <p className="text-sm text-muted-foreground leading-relaxed">
              Email a description of the issue, reproduction steps, and any
              proof-of-concept to{" "}
              <a
                href="mailto:nguiasoren@gmail.com?subject=ROGUE%20security%20disclosure"
                className="font-mono text-rogue-green underline-offset-4 hover:underline"
              >
                nguiasoren@gmail.com
              </a>
              . We aim to acknowledge reports promptly and will keep you updated
              as we investigate. Please give us reasonable time to remediate
              before any public disclosure.
            </p>
            <p className="text-sm text-muted-foreground leading-relaxed">
              No inbox set up yet? You can also{" "}
              <Link
                href="/request-demo"
                className="text-rogue-green underline-offset-4 hover:underline"
              >
                reach us through our contact form
              </Link>{" "}
              and we&apos;ll route it to the right person.
            </p>
          </div>
        </Section>

        {/* 5. DEPLOYMENT OPTIONS ------------------------------------------ */}
        <Section
          eyebrow="sensitive environments"
          title="Deployment options for air-gapped and regulated stacks."
        >
          <div className="rogue-card border border-border rounded-xl p-6 md:p-8 bg-card/40 backdrop-blur-sm max-w-3xl space-y-4">
            <Building2
              className="h-6 w-6 text-rogue-green"
              strokeWidth={1.75}
              aria-hidden
            />
            <p className="text-sm md:text-[17px] text-foreground leading-relaxed">
              The hosted platform fits most teams, but if your model can&apos;t be
              reached from the public internet, or your compliance posture
              requires data never leave your perimeter, ROGUE can run inside
              your own environment, pointed at internal endpoints. Self-hosted
              and private deployments keep every prompt, response, and report
              within your boundary.
            </p>
            <Link
              href="/enterprise"
              className="inline-flex items-center gap-2 font-mono text-sm font-bold tracking-[0.12em] uppercase text-rogue-green hover:opacity-90 transition-opacity"
            >
              Explore enterprise &amp; self-hosted
              <ArrowRight className="h-4 w-4" aria-hidden />
            </Link>
          </div>
        </Section>

        {/* 6. CLOSING CTA ------------------------------------------------- */}
        <Section
          eyebrow="ready when you are"
          title="Point ROGUE at your endpoint, safely."
          lede="See exactly what a scan touches, and what it returns, on a real report."
        >
          <CtaRow />
        </Section>
      </div>
    </main>
  );
}

// ---------------------------------------------------------------------------

const POSTURE: ReadonlyArray<{
  icon: React.ComponentType<{
    className?: string;
    strokeWidth?: number;
    "aria-hidden"?: boolean;
  }>;
  title: string;
  body: string;
}> = [
  {
    icon: KeyRound,
    title: "Encrypted secrets",
    body: "The API keys and credentials you give ROGUE are encrypted at rest with a dedicated platform encryption key. They are never written to logs and never returned in API responses.",
  },
  {
    icon: Lock,
    title: "Organization isolation",
    body: "Every scan, API key, and report is scoped to your organization. Tenancy is enforced at the data layer, so one org can never read, list, or reach another org's data.",
  },
  {
    icon: ServerOff,
    title: "No model weights stored",
    body: "ROGUE tests your model over its API. It never downloads, hosts, or stores your weights, and it doesn't need your training data or source to run a scan.",
  },
  {
    icon: FileText,
    title: "Audit logging",
    body: "Scan lifecycle events and access to your data are recorded, so you have a trail of what ran, when, and against which endpoint.",
  },
  {
    icon: Trash2,
    title: "Data retention policy",
    body: "Reports are retained for your account so you can track posture over time. Raw attack transcripts can be retained or deleted on request, we hold only what's useful to you.",
  },
  {
    icon: EyeOff,
    title: "Least-privilege access",
    body: "ROGUE only ever needs inference access to the single endpoint you point it at. No broad keys, no infrastructure access, no standing connection into your systems.",
  },
];

const FLOW: ReadonlyArray<{ title: string; body: string }> = [
  {
    title: "You provide an endpoint and a key",
    body: "Point ROGUE at the model endpoint you want tested and supply an inference key. The key is encrypted at rest the moment it lands.",
  },
  {
    title: "ROGUE sends attack prompts",
    body: "From the attacker side, ROGUE replays harvested jailbreaks and prompt-injection against your endpoint over the API, exactly as a real adversary would reach it.",
  },
  {
    title: "It captures the responses",
    body: "Each response your model returns is captured so the attack can be judged for an actual breach, not just a guess. Nothing about your model's internals is extracted.",
  },
  {
    title: "It judges and reports",
    body: "An LLM judge grades each exchange, and ROGUE compiles a scored report of which attacks landed and how severe they are.",
  },
  {
    title: "You can delete the transcripts",
    body: "Reports stay tied to your account; the raw transcripts behind them can be deleted on request once you've acted on the findings.",
  },
];
