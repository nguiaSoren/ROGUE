import { Term } from "@/components/glossary";
import { SourceLogo } from "@/components/ui/source-logo";

/**
 * 3-step narrative: HARVEST → REPRODUCE → DEFEND.
 *
 * Each step is a card with a number badge, headline, one-sentence
 * explanation, and a mini visualization. Animated arrows between them
 * complete the "this is a pipeline" mental model in one glance.
 *
 * Server component — all motion is CSS keyframes (the Term children are
 * client components, which is fine inside a server component).
 */
export function HowRogueThinks({
  nSources = 19,
  nPrimitives,
  nConfigs,
  nBreaches,
}: {
  nSources?: number;
  nPrimitives: number | null;
  nConfigs: number | null;
  nBreaches: number | null;
}) {
  return (
    <section className="space-y-6">
      <div className="space-y-2 animate-rogue-fade-up">
        <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
          how rogue thinks
        </p>
        <h2 className="text-3xl md:text-4xl font-bold tracking-tight max-w-3xl">
          Three loops, one outcome: a threat brief that&apos;s true today.
        </h2>
        <p className="text-base text-muted-foreground max-w-2xl leading-relaxed">
          Every dot on the dashboard traces back to a real attack that ran
          against a real config and got judged by a real LLM. No synthetic
          benchmarks, no hand-picked examples.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 md:gap-4 relative">
        <Step
          n="01"
          label="harvest"
          color="var(--rogue-green)"
          colorClass="text-rogue-green"
          metric={nSources}
          metricUnit="open-web sources"
          headline="Stream the latest jailbreaks."
          body={
            <>
              <SourceLogo source="Reddit" className="text-foreground/55 mr-0.5" />
              Reddit,{" "}
              <SourceLogo source="X" className="text-foreground/55 mr-0.5" />X,{" "}
              <SourceLogo source="GitHub" className="text-foreground/55 mr-0.5" />
              GitHub,{" "}
              <SourceLogo
                source="Hugging Face"
                className="text-foreground/55 mr-0.5"
              />
              Hugging Face,{" "}
              <SourceLogo source="arXiv" className="text-foreground/55 mr-0.5" />
              arXiv, leaks — fanned out through 5 Bright Data products. New
              attacks land in the DB within minutes of being posted.
            </>
          }
          delay="0.1s"
        />
        <Step
          n="02"
          label="reproduce"
          color="#22d3ee"
          colorClass="text-cyan-300"
          metric={nConfigs}
          metricUnit="deployment configs"
          headline="Run each one against your stack."
          body={
            <>
              A 5-config trial panel (your customer&apos;s models × system
              prompts × tool sets). <Term name="PAIR">PAIR</Term> makes the
              attacker iterate. Persona, escalation, and mutation stress
              tests probe brittle defenses.
            </>
          }
          delay="0.2s"
        />
        <Step
          n="03"
          label="defend"
          color="var(--rogue-red)"
          colorClass="text-rogue-red"
          metric={nBreaches}
          metricUnit="trials judged"
          headline="Ship a brief that ends an argument."
          body={
            <>
              Markdown, JSON, Slack, <Term name="MCP">MCP</Term>. Each
              finding carries 95% bootstrap{" "}
              <Term name="CI">CIs</Term> and a regenerable receipt.
              Today&apos;s diff vs yesterday&apos;s, automatically.
            </>
          }
          delay="0.3s"
        />

        {/* Hint at primitives count — appears as a floating annotation
            between steps 1 and 2 on desktop so the eye picks up the chain. */}
        {nPrimitives !== null && (
          <div className="hidden md:flex absolute top-1/2 left-1/3 -translate-x-1/2 -translate-y-1/2 pointer-events-none">
            <span className="px-2 py-1 rounded font-mono text-[10px] bg-background/80 border border-border text-muted-foreground backdrop-blur-sm">
              → {nPrimitives.toLocaleString()} primitives
            </span>
          </div>
        )}
      </div>
    </section>
  );
}

function Step({
  n,
  label,
  color,
  colorClass,
  metric,
  metricUnit,
  headline,
  body,
  delay,
}: {
  n: string;
  label: string;
  color: string;
  colorClass: string;
  metric: number | null;
  metricUnit: string;
  headline: string;
  body: React.ReactNode;
  delay: string;
}) {
  return (
    <div
      className="rogue-card border border-border rounded-xl p-5 md:p-6 bg-card/40 backdrop-blur-sm space-y-4 relative animate-rogue-fade-up"
      style={{ animationDelay: delay, borderTop: `2px solid ${color}` }}
    >
      <div className="flex items-baseline justify-between">
        <span
          className="font-mono text-xs tracking-[0.22em] uppercase opacity-70"
          style={{ color }}
        >
          {n} · {label}
        </span>
        {metric !== null && (
          <span className={`tabular-nums font-mono text-xs ${colorClass}`}>
            {metric.toLocaleString()} <span className="opacity-60">{metricUnit}</span>
          </span>
        )}
      </div>
      <h3 className="text-lg md:text-xl font-semibold leading-snug">{headline}</h3>
      <p className="text-sm text-muted-foreground leading-relaxed">{body}</p>
    </div>
  );
}
