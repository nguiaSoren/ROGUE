import Link from "next/link";

/**
 * PRODUCT pitch strip — the "what you actually buy" section.
 *
 * Reframes ROGUE from a threat-intel dashboard into a product: point it at
 * your LLM endpoint, get back a scored report of which jailbreaks break it
 * and how to fix them. The live threat-intel below this section is the proof
 * that the arsenal is real and fresh — this section is the offer.
 *
 * Server component — no interactivity, all motion is CSS keyframes. The
 * continuously-harvested corpus size (nAttacks) is shown as supporting proof.
 */
export function ProductPitch({ nAttacks }: { nAttacks: number | null }) {
  return (
    <section className="space-y-8 animate-rogue-fade-up">
      <div className="space-y-3">
        <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
          the product
        </p>
        <h2 className="text-3xl md:text-4xl font-bold tracking-tight max-w-3xl">
          Point ROGUE at your LLM endpoint. Get a report of which jailbreaks
          break it — and how to fix them.
        </h2>
        <p className="text-base text-muted-foreground max-w-2xl leading-relaxed">
          No new harness to write, no attack corpus to curate. Give us an
          endpoint or{" "}
          <code className="font-mono text-rogue-green text-sm bg-rogue-green/5 px-1.5 py-0.5 rounded">
            pip install rogue
          </code>{" "}
          the SDK, and ROGUE throws its continuously-harvested arsenal of
          {nAttacks !== null ? (
            <>
              {" "}
              <span className="text-foreground font-medium tabular-nums">
                {nAttacks.toLocaleString()}
              </span>{" "}
              real attacks
            </>
          ) : (
            " real, open-web attacks"
          )}{" "}
          at it — then hands you a scored report with the breaches and the
          fixes.
        </p>
      </div>

      {/* How it works — 3-step strip */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 md:gap-4">
        <PitchStep
          n="01"
          label="point it"
          headline="Give us an endpoint."
          body={
            <>
              An API endpoint, a provider + model, or{" "}
              <code className="font-mono text-foreground/80 text-xs bg-foreground/5 px-1 py-0.5 rounded">
                pip install rogue
              </code>{" "}
              and call it from your own CI. No agent to deploy.
            </>
          }
          delay="0.05s"
        />
        <PitchStep
          n="02"
          label="we attack"
          headline="ROGUE throws its arsenal."
          body={
            <>
              Every jailbreak and prompt-injection we&apos;ve harvested from the
              open web, replayed against your stack — with PAIR, persona,
              escalation, and mutation stress tests layered on.
            </>
          }
          delay="0.15s"
        />
        <PitchStep
          n="03"
          label="you fix"
          headline="Get a scored report."
          body={
            <>
              Every breach, graded by an independent judge with 95% CIs — plus
              remediation: the system-prompt patch or guardrail that closes each
              hole.
            </>
          }
          delay="0.25s"
        />
      </div>

      {/* CTAs */}
      <div className="flex flex-wrap items-center gap-3">
        <Link
          href="/scans/new"
          className="px-6 py-3 rounded-md bg-rogue-green text-black font-mono text-sm font-bold tracking-[0.15em] uppercase hover:bg-rogue-green/90 transition-all shadow-[0_0_32px_var(--rogue-green-dim)] hover:shadow-[0_0_48px_var(--rogue-green-dim)] hover:-translate-y-0.5"
        >
          Run a scan →
        </Link>
        <a
          href="/sample-report.html"
          target="_blank"
          rel="noopener noreferrer"
          className="px-6 py-3 rounded-md border border-border font-mono text-sm tracking-[0.15em] uppercase hover:border-rogue-green hover:text-rogue-green transition-colors"
        >
          See a sample report
        </a>
        <Link
          href="/scans"
          className="px-6 py-3 rounded-md border border-transparent font-mono text-sm tracking-[0.15em] uppercase text-muted-foreground hover:text-foreground transition-colors"
        >
          Dashboard / quickstart
        </Link>
      </div>
    </section>
  );
}

function PitchStep({
  n,
  label,
  headline,
  body,
  delay,
}: {
  n: string;
  label: string;
  headline: string;
  body: React.ReactNode;
  delay: string;
}) {
  return (
    <div
      className="rogue-card border border-border rounded-xl p-5 md:p-6 bg-card/40 backdrop-blur-sm space-y-3 relative animate-rogue-fade-up"
      style={{ animationDelay: delay, borderTop: "2px solid var(--rogue-green)" }}
    >
      <span className="font-mono text-xs tracking-[0.22em] uppercase text-rogue-green opacity-70">
        {n} · {label}
      </span>
      <h3 className="text-lg md:text-xl font-semibold leading-snug">{headline}</h3>
      <p className="text-sm text-muted-foreground leading-relaxed">{body}</p>
    </div>
  );
}
