import Link from "next/link";
import { Rocket, ClipboardCheck, FlaskConical, ArrowRight } from "lucide-react";

/**
 * EarlyAccessSection, the honest social-proof replacement.
 *
 * ROGUE has no customers yet, so this section never claims any. Instead it
 * frames the three on-ramps for the first partners we're onboarding now:
 * Early Access, Pilot, and Research Partners. Self-contained and
 * max-w-7xl-aware so it can be dropped in as a top-level homepage section.
 * Server component.
 *
 * The honest "what's being built" content: the pilot+partner sales asks are
 * dropped and every card routes to /early-access, /research, or /matrix.
 */
export function EarlyAccessSection() {
  const tracks = RESEARCH_TRACKS;
  return (
    <section className="max-w-7xl mx-auto px-6">
      <div className="max-w-3xl space-y-4">
        <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
          early access
        </p>
        <h2 className="text-3xl md:text-4xl font-bold tracking-tight">
          We&apos;re onboarding our first partners.
        </h2>
        <p className="text-[17px] text-foreground leading-relaxed">
          ROGUE is new and we&apos;re choosing the teams we build it with. No
          customer logos to show yet, just three honest ways to get on the
          engine early and shape where it goes.
        </p>
      </div>

      <div className="mt-10 md:mt-12 grid grid-cols-1 md:grid-cols-3 gap-4">
        {tracks.map((track) => (
          <div
            key={track.name}
            className="rogue-card border border-border rounded-xl p-5 md:p-6 bg-card/40 backdrop-blur-sm flex flex-col"
          >
            <track.icon
              className="h-6 w-6 text-rogue-green"
              strokeWidth={1.75}
              aria-hidden
            />
            <h3 className="mt-4 text-lg font-bold tracking-tight">
              {track.name}
            </h3>
            <p className="mt-1 text-sm text-muted-foreground leading-relaxed">
              {track.forWhom}
            </p>
            <p className="mt-3 text-sm text-foreground/90 leading-relaxed">
              {track.gist}
            </p>
            <Link
              href={track.href}
              className="mt-5 inline-flex items-center gap-2 font-mono text-xs font-bold tracking-[0.12em] uppercase text-rogue-green hover:opacity-90 transition-opacity"
            >
              {track.cta}
              <ArrowRight className="h-4 w-4" aria-hidden />
            </Link>
          </div>
        ))}
      </div>

      <p className="mt-10 text-sm text-muted-foreground leading-relaxed">
        Not sure which fits?{" "}
        <Link
          href="/early-access"
          className="text-rogue-green underline-offset-4 hover:underline"
        >
          See the early-access tracks
        </Link>{" "}
        or{" "}
        <Link
          href="/research"
          className="text-rogue-green underline-offset-4 hover:underline"
        >
          read the research
        </Link>{" "}
, we read every one.
      </p>
    </section>
  );
}

// ---------------------------------------------------------------------------

// The honest "what's being built" content: the pilot+partner *sales* asks are
// dropped, every card routes to the research surface, the early-access tracks,
// or the live matrix instead of any /request-demo sales surface.
const RESEARCH_TRACKS: ReadonlyArray<{
  icon: React.ComponentType<{
    className?: string;
    strokeWidth?: number;
    "aria-hidden"?: boolean;
  }>;
  name: string;
  forWhom: string;
  gist: string;
  cta: string;
  href: string;
}> = [
  {
    icon: FlaskConical,
    name: "The research",
    forWhom: "The methods and measured results behind the engine.",
    gist: "Judge calibration against human-labeled benchmarks, scheduling as a capability lever, a publication-grade null result, and measure-before-build discipline, including the negative results.",
    cta: "Read the research",
    href: "/research",
  },
  {
    icon: Rocket,
    name: "What's being built",
    forWhom: "A real, running continuous open-web red-team.",
    gist: "The full repertoire and adaptive-ladder scans, a self-recalibrating judge, a benchmark layer, and an MCP server, all live in production, built solo.",
    cta: "See the early-access tracks",
    href: "/early-access",
  },
  {
    icon: ClipboardCheck,
    name: "The live evidence",
    forWhom: "Don't take the writeup's word for it.",
    gist: "The breach matrix with 95% bootstrap CIs, live telemetry, and the harvest feed, the running system's own surfaces.",
    cta: "Open the matrix",
    href: "/matrix",
  },
];
