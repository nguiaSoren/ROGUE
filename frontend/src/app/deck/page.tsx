import Link from "next/link";
import {
  ShieldAlert,
  Clock,
  Crosshair,
  Workflow,
  Plug,
  Boxes,
  ArrowRight,
} from "lucide-react";
import { Section } from "@/components/marketing/section";
import { StatCard } from "@/components/marketing/stat-card";
import { CtaRow } from "@/components/marketing/cta-row";
import {
  CORPUS,
  JUDGE_V3,
  SCHEDULER_AB,
  EFFICIENCY,
  PROOF_POINTS,
} from "@/lib/proof";

export const metadata = {
  title: "ROGUE, Pitch",
  description:
    "ROGUE in ten slides: one engine that measures every way a high-stakes AI agent goes wrong — model, human oversight, accumulated knowledge — against an independent, signed standard, before your users do. Built on Bright Data, queryable over MCP.",
};

/**
 * /deck, a scrollable, screen-shareable pitch deck. Ten full-width sections,
 * each reading like one slide. Server component; pulls every number from
 * @/lib/proof so the narrative can never drift from the verified figures.
 *
 * Each slide carries a mono "NN / 10" eyebrow so it reads as a deck whether
 * scrolled in-browser or screen-shared one viewport at a time.
 */
export default function DeckPage() {
  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="space-y-24 md:space-y-32 py-20 md:py-28">
        {/* 01, TITLE -------------------------------------------------- */}
        <Slide n={1}>
          <div className="max-w-7xl mx-auto px-6">
            <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green flex items-center gap-2">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-rogue-green animate-rogue-pulse-green" />
              01 / 10 · ROGUE
            </p>
            <h1 className="mt-6 text-3xl sm:text-4xl md:text-6xl font-bold tracking-tight leading-[1.05]">
              Measure every way a high-stakes
              <br />
              <span className="text-rogue-green">AI agent goes wrong.</span>
            </h1>
            <p className="mt-6 text-lg md:text-xl text-muted-foreground max-w-2xl leading-relaxed">
              Three failure modes, one engine: the model can be broken, the
              human gate can be meaningless, the skill memory can leak. ROGUE
              measures each against an independent, continuously-refreshed
              standard — reproducible, signed, one engine.
            </p>
            <p className="mt-4 text-sm text-muted-foreground max-w-2xl leading-relaxed">
              The live path today is the SDK or a scoped pilot; hosted scanning
              is in private beta.
            </p>
            <p className="mt-10 font-mono text-sm text-muted-foreground">
              Soren Obounou Nguia · Incheon ·{" "}
              <a
                href="mailto:nguiasoren@gmail.com"
                className="text-rogue-green hover:underline"
              >
                nguiasoren@gmail.com
              </a>
            </p>
          </div>
        </Slide>

        {/* 02, PROBLEM ------------------------------------------------ */}
        <Slide n={2}>
          <Section
            eyebrow="02 / 10 · the problem"
            title="You find out you were jailbroken from your users, not before."
            lede="Every LLM you ship is a public attack surface. Prompt injection, jailbreaks, and tool-abuse land in production silently. The first signal is usually a screenshot on social media or an angry support ticket, long after the model already said the thing."
          >
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <PainCard
                icon={<ShieldAlert className="h-5 w-5" />}
                title="Silent failures"
                desc="A model that complies with a malicious prompt throws no error. Nothing alerts. The breach is invisible until someone shows you."
              />
              <PainCard
                icon={<Clock className="h-5 w-5" />}
                title="Detection lag"
                desc="By the time a jailbreak trends, it has been working against your deployment for days or weeks."
              />
              <PainCard
                icon={<Crosshair className="h-5 w-5" />}
                title="Your exact config"
                desc="Generic safety benchmarks don't test your model × your system prompt × your tools. The risk that matters is the one specific to your stack."
              />
            </div>
          </Section>
        </Slide>

        {/* 03, WHY NOW ----------------------------------------------- */}
        <Slide n={3}>
          <Section
            eyebrow="03 / 10 · why now"
            title="Attack techniques evolve daily. Your red-team report is already stale."
            lede="Jailbreaks and injection patterns are published, remixed, and refined in the open every day, on Reddit, X, GitHub, Discord, and research feeds. A one-off pentest is a photograph of a moving target. The moment it ships, it's out of date."
          >
            <div className="rogue-card border border-border rounded-xl p-6 md:p-8 bg-card/40 backdrop-blur-sm">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-8 items-center">
                <div className="space-y-3">
                  <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
                    the old way
                  </p>
                  <p className="text-lg font-bold">
                    One-off pentest, twice a year.
                  </p>
                  <p className="text-sm text-muted-foreground leading-relaxed">
                    A consultant runs a fixed checklist, hands you a PDF, and
                    leaves. The checklist ages out the day they finish.
                  </p>
                </div>
                <div className="space-y-3">
                  <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
                    the rogue way
                  </p>
                  <p className="text-lg font-bold text-rogue-green">
                    Continuous harvest, daily diff.
                  </p>
                  <p className="text-sm text-muted-foreground leading-relaxed">
                    New techniques are harvested from the open web every day and
                    reproduced against your configs automatically. Your report
                    is never older than yesterday.
                  </p>
                </div>
              </div>
            </div>
          </Section>
        </Slide>

        {/* 04, SOLUTION ---------------------------------------------- */}
        <Slide n={4}>
          <Section
            eyebrow="04 / 10 · the solution"
            title="Wire ROGUE into your stack. Get a scored report with a verified fix."
            lede="No agents to install, no traffic to mirror. Give ROGUE your deployment config and it does the rest, continuously. Today that runs over the SDK or a scoped pilot; hosted scanning is in private beta."
          >
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <StepCard
                step="1"
                title="Connect"
                desc="Register your deployment, model, system prompt, and tools. Hosted, private, or via the SDK."
              />
              <StepCard
                step="2"
                title="Scan"
                desc="ROGUE reproduces live open-web attacks against that exact config, continuously, and grades every attempt with a calibrated judge."
              />
              <StepCard
                step="3"
                title="Report"
                desc="A scored security report with severity, the exact prompts that broke through, and concrete remediation, refreshed daily."
              />
            </div>
          </Section>
        </Slide>

        {/* 05, HOW IT WORKS ----------------------------------------- */}
        <Slide n={5}>
          <Section
            eyebrow="05 / 10 · how it works"
            title="Harvest → reproduce → diff."
            lede="A three-stage pipeline that turns the open web's newest attacks into a report about your stack."
          >
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <PipelineCard
                phase="Harvest"
                headline={`${CORPUS.sources} sources · ${CORPUS.bdProducts} Bright Data products`}
                desc="Continuously collect fresh jailbreaks and prompt-injection from across the open web, normalized into a structured threat corpus of attack primitives."
              />
              <PipelineCard
                phase="Reproduce"
                headline="Against your configs"
                desc="Replay each attack against your model × system prompt × tools, escalate with an adaptive ladder, and grade every attempt with a calibrated judge."
              />
              <PipelineCard
                phase="Diff"
                headline="Daily threat brief"
                desc="Ship a CISO-readable diff of what's new, what regressed, and what to fix, the artifact you'd actually forward to your team."
              />
            </div>
            <p className="mt-6 font-mono text-xs text-muted-foreground">
              {CORPUS.primitives} attack primitives · {CORPUS.families}{" "}
              families · {CORPUS.reproductionTrials.toLocaleString()}{" "}
              reproduction trials run to date.
            </p>
          </Section>
        </Slide>

        {/* 06, DIFFERENTIATOR --------------------------------------- */}
        <Slide n={6}>
          <Section
            eyebrow="06 / 10 · the differentiator"
            title="One independent, signed standard across all three surfaces."
            lede="Anyone can run a checklist once. ROGUE measures the model, the human oversight gate, and the accumulated skill-memory against the same independent, continuously-refreshed open-web corpus — and emits a reproducible, signed record for every result. As the corpus grows, the standard re-tests itself; the moat is the standard, not a feature."
          >
            <div className="rogue-card border border-border rounded-xl p-6 md:p-8 bg-card/40 backdrop-blur-sm">
              <div className="flex items-start gap-4">
                <div className="rounded-lg border border-rogue-green/40 bg-rogue-green/5 p-3 text-rogue-green shrink-0">
                  <ShieldAlert className="h-6 w-6" />
                </div>
                <div className="space-y-3">
                  <p className="text-lg font-bold">
                    Model broken · human gate meaningless · skill memory leaks —
                    measured, scored, and signed.
                  </p>
                  <p className="text-sm text-muted-foreground leading-relaxed max-w-3xl">
                    Each surface is graded against the same independent corpus
                    that refreshes from the open web, so the standard is never
                    your own marking your own homework, and never stale. Every
                    result ships with a reproducible, signed record you can hand
                    to an auditor. The model surface is mature today; the
                    oversight and memory surfaces are measured and
                    research-validated (signed, small-n), not yet turnkey.
                  </p>
                  <p className="font-mono text-xs text-muted-foreground flex items-center gap-2">
                    <Plug className="h-3.5 w-3.5" />
                    Distributed over MCP too — Claude Desktop · Cursor ·
                    Windsurf query the same signed standard from inside your IDE.
                  </p>
                </div>
              </div>
            </div>
          </Section>
        </Slide>

        {/* 07, PROOF ------------------------------------------------- */}
        <Slide n={7}>
          <Section
            eyebrow="07 / 10 · proof"
            title="Defensible numbers, every one traceable."
            lede="No inflated asterisks. These are the figures we stand behind, measured, sourced, and recalibrated under the current judge."
          >
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {PROOF_POINTS.map((p) => (
                <StatCard
                  key={p.label}
                  value={p.value}
                  label={p.label}
                  sublabel={p.sublabel}
                  accent={p.value.startsWith("−") ? "red" : "green"}
                />
              ))}
            </div>
            <p className="mt-6 font-mono text-xs text-muted-foreground max-w-3xl leading-relaxed">
              Judge v3: {JUDGE_V3.precision}% precision · {JUDGE_V3.recall}%
              recall · {JUDGE_V3.humanAgreement}% human agreement on
              JailbreakBench. Adaptive ladder cuts cost per successful breach
              from ${SCHEDULER_AB.costFrom.toFixed(2)} to $
              {SCHEDULER_AB.costTo.toFixed(2)} (−{SCHEDULER_AB.costReductionPct}
              %). Judge cost ${EFFICIENCY.judgeCostPerCallUsd} per call with
              caching + batch API.
            </p>
          </Section>
        </Slide>

        {/* 08, DEPLOYMENT ------------------------------------------- */}
        <Slide n={8}>
          <Section
            eyebrow="08 / 10 · deployment"
            title="Four ways to run it."
            lede="From a hosted scan to fully air-gapped, ROGUE meets your security posture, not the other way around."
          >
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <DeployCard
                title="Hosted"
                desc="The fastest path. We run the scans against your registered endpoint and serve the dashboard — hosted execution in private beta."
              />
              <DeployCard
                title="Private"
                desc="Run ROGUE inside your own perimeter. Your prompts and traffic never leave your environment."
              />
              <DeployCard
                title="SDK"
                desc="A Python client against a frozen v1 contract, wire ROGUE into your own CI or test harness."
              />
              <DeployCard
                title="MCP"
                desc="Query the live threat DB from Claude Desktop, Cursor, or Windsurf, one-click connect."
              />
            </div>
            <div className="mt-8">
              <Link
                href="/try"
                className="inline-flex items-center gap-2 font-mono text-sm font-bold tracking-[0.12em] uppercase text-rogue-green hover:underline"
              >
                Run ROGUE on your stack <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
          </Section>
        </Slide>

        {/* 09, WHO IT'S FOR ----------------------------------------- */}
        <Slide n={9}>
          <Section
            eyebrow="09 / 10 · who it's for"
            title="Built for the people who own the risk."
            lede="Anyone shipping an LLM into production has an open attack surface. These are the five who feel it first."
          >
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
              {[
                ["AI / ML engineers", "Shipping a model behind a system prompt and tools."],
                ["Security & red teams", "Owning the LLM attack surface and the audit."],
                ["Platform teams", "Running the gateway every other team ships through."],
                ["CISOs", "Accountable for what the model says in production."],
                ["AI product leads", "On the hook when the model goes off-script publicly."],
              ].map(([persona, desc]) => (
                <div
                  key={persona}
                  className="rogue-card border border-border rounded-xl p-5 bg-card/40 backdrop-blur-sm"
                >
                  <p className="text-sm font-bold">{persona}</p>
                  <p className="mt-1.5 text-sm text-muted-foreground leading-relaxed">
                    {desc}
                  </p>
                </div>
              ))}
            </div>
            <div className="mt-8 flex items-center gap-3">
              <Boxes className="h-5 w-5 text-rogue-green shrink-0" />
              <p className="text-sm text-muted-foreground">
                Point ROGUE at your stack and threat model.{" "}
                <Link
                  href="/try"
                  className="text-rogue-green font-mono uppercase tracking-[0.1em] text-xs hover:underline"
                >
                  Try the demo →
                </Link>
              </p>
            </div>
          </Section>
        </Slide>

        {/* 10, CLOSE / CTA ------------------------------------------ */}
        <Slide n={10}>
          <div className="max-w-7xl mx-auto px-6">
            <div className="rogue-card border border-border rounded-2xl p-8 md:p-14 bg-card/40 backdrop-blur-sm text-center">
              <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
                10 / 10 · let&apos;s talk
              </p>
              <h2 className="mt-5 text-3xl md:text-5xl font-bold tracking-tight">
                Find every way a high-stakes agent goes wrong, before your users
                do.
              </h2>
              <p className="mt-5 text-base md:text-lg text-muted-foreground max-w-2xl mx-auto leading-relaxed">
                Bring your stack. We&apos;ll show you exactly what breaks
                through it — model, oversight, and memory — and what to fix.
              </p>
              <div className="mt-8 flex justify-center">
                <CtaRow />
              </div>
            </div>
          </div>
        </Slide>
      </div>
    </main>
  );
}

// --------------------------------------------------------------------------

/** One full-width deck section. min-h keeps each slide screen-shareable. */
function Slide({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <section
      id={`slide-${n}`}
      className="scroll-mt-24 animate-rogue-fade-up flex flex-col justify-center"
    >
      {children}
    </section>
  );
}

function PainCard({
  icon,
  title,
  desc,
}: {
  icon: React.ReactNode;
  title: string;
  desc: string;
}) {
  return (
    <div className="rogue-card border border-border rounded-xl p-6 bg-card/40 backdrop-blur-sm">
      <div className="text-rogue-red">{icon}</div>
      <p className="mt-4 text-lg font-bold">{title}</p>
      <p className="mt-1.5 text-sm text-muted-foreground leading-relaxed">{desc}</p>
    </div>
  );
}

function StepCard({
  step,
  title,
  desc,
}: {
  step: string;
  title: string;
  desc: string;
}) {
  return (
    <div className="rogue-card border border-border rounded-xl p-6 bg-card/40 backdrop-blur-sm">
      <div className="font-mono text-3xl font-bold text-rogue-green">{step}</div>
      <p className="mt-3 text-lg font-bold">{title}</p>
      <p className="mt-1.5 text-sm text-muted-foreground leading-relaxed">{desc}</p>
    </div>
  );
}

function PipelineCard({
  phase,
  headline,
  desc,
}: {
  phase: string;
  headline: string;
  desc: string;
}) {
  return (
    <div className="rogue-card border border-border rounded-xl p-6 bg-card/40 backdrop-blur-sm">
      <div className="flex items-center gap-2 text-rogue-green">
        <Workflow className="h-4 w-4" />
        <p className="font-mono text-[11px] uppercase tracking-[0.22em]">
          {phase}
        </p>
      </div>
      <p className="mt-3 text-base font-bold">{headline}</p>
      <p className="mt-1.5 text-sm text-muted-foreground leading-relaxed">{desc}</p>
    </div>
  );
}

function DeployCard({ title, desc }: { title: string; desc: string }) {
  return (
    <div className="rogue-card border border-border rounded-xl p-5 bg-card/40 backdrop-blur-sm">
      <p className="font-mono text-sm font-bold uppercase tracking-[0.12em] text-rogue-green">
        {title}
      </p>
      <p className="mt-2 text-sm text-muted-foreground leading-relaxed">{desc}</p>
    </div>
  );
}
