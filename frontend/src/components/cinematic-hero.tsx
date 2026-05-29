import Link from "next/link";
import { PausedOffscreen } from "@/components/paused-offscreen";
import { plainifyAttackCount, plainifyTrials } from "@/lib/plain-numbers";

/**
 * Cinematic home-page hero.
 *
 * Replaces the prior "Continuous red-team" header. Built for a 5-second
 * read: one massive headline, a rotating-word subhead (the threats ROGUE
 * watches), a single high-contrast CTA, and a scroll cue.
 *
 * Server component — no interactivity, all motion is CSS keyframes so
 * there's no JS hydration penalty before the first paint.
 */
export function CinematicHero({
  nAttacks,
  nConfigs,
  nBreaches,
}: {
  nAttacks: number | null;
  nConfigs: number | null;
  nBreaches: number | null;
}) {
  return (
    <PausedOffscreen
      tag="section"
      className="relative min-h-[88vh] flex flex-col justify-center overflow-hidden bg-rogue-mesh -mx-6 px-6"
    >
      {/* Subtle grid laid on top of the mesh so the hero still reads as part
          of the ROGUE design language, but lighter than the page default. */}
      <div
        className="absolute inset-0 opacity-40 pointer-events-none"
        style={{
          backgroundImage:
            "linear-gradient(rgba(0, 255, 136, 0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(0, 255, 136, 0.05) 1px, transparent 1px)",
          backgroundSize: "80px 80px",
        }}
      />

      <div className="relative max-w-7xl mx-auto w-full py-20 md:py-28 space-y-10">
        {/* Live pill + Bright Data pill */}
        <div className="flex flex-wrap items-center gap-2 animate-rogue-reveal">
          <div className="inline-flex items-center gap-2 px-3 py-1 border border-rogue-green/40 rounded-full bg-rogue-green/5 font-mono text-[10px] uppercase tracking-[0.22em] text-rogue-green">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-rogue-green animate-rogue-pulse-green" />
            live · streaming the open web
          </div>
          <div className="inline-flex items-center gap-2 px-3 py-1 border border-foreground/30 rounded-full bg-foreground/5 font-mono text-[10px] uppercase tracking-[0.22em] text-foreground">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-foreground/70" />
            powered by Bright Data · 5 / 5 products · cost-optimized
          </div>
        </div>

        {/* Title */}
        <h1
          className="text-5xl md:text-7xl lg:text-[5.5rem] font-bold tracking-tight leading-[0.95] max-w-5xl animate-rogue-reveal"
          style={{ animationDelay: "0.1s" }}
        >
          <span className="block">Your LLM is being</span>
          <span className="block">
            <span className="rogue-word-rotator-wrap inline-flex h-[1em] overflow-hidden align-baseline mr-3 text-rogue-red">
              <span className="rogue-word-rotator">
                <span className="block h-[1em]">jailbroken.</span>
                <span className="block h-[1em]">prompt-injected.</span>
                <span className="block h-[1em]">role-played.</span>
                <span className="block h-[1em]">escalated.</span>
                <span className="block h-[1em]">jailbroken.</span>
              </span>
            </span>
          </span>
          <span className="block text-muted-foreground">
            ROGUE finds out before your users do.
          </span>
        </h1>

        {/* Subhead */}
        <p
          className="text-lg md:text-xl text-muted-foreground max-w-2xl leading-relaxed animate-rogue-reveal"
          style={{ animationDelay: "0.25s" }}
        >
          Built on{" "}
          <span className="text-foreground font-medium">
            all 5 Bright Data products
          </span>
          . Harvests every new jailbreak from{" "}
          <span className="text-foreground font-medium">19 open-web sources</span>,
          reproduces each one against your stack, and ships a daily brief —
          on a budget the bandit auto-tunes for you.
        </p>

        {/* Hero stat trio — the "this is alive" proof */}
        <div
          className="grid grid-cols-3 gap-3 md:gap-6 max-w-2xl animate-rogue-reveal"
          style={{ animationDelay: "0.35s" }}
        >
          <HeroStat
            value={nAttacks}
            label="attacks tracked"
            sub={nAttacks !== null ? plainifyAttackCount(nAttacks) : "extracted + dedup'd"}
            tint="green"
          />
          <HeroStat
            value={nBreaches}
            label="trials judged"
            sub={nBreaches !== null ? plainifyTrials(nBreaches) : "across all configs"}
            tint="green"
          />
          <HeroStat
            value={nConfigs}
            label="deployments tested"
            sub={
              nConfigs !== null
                ? `${nConfigs} customer-style setups under live attack`
                : "model × system prompt"
            }
            tint="green"
          />
        </div>

        {/* CTA */}
        <div
          className="flex flex-wrap items-center gap-3 animate-rogue-reveal"
          style={{ animationDelay: "0.45s" }}
        >
          <Link
            href="/matrix"
            className="px-6 py-3 rounded-md bg-rogue-green text-black font-mono text-sm font-bold tracking-[0.15em] uppercase hover:bg-rogue-green/90 transition-all shadow-[0_0_32px_var(--rogue-green-dim)] hover:shadow-[0_0_48px_var(--rogue-green-dim)] hover:-translate-y-0.5"
          >
            See what&apos;s breaching → /matrix
          </Link>
          <Link
            href="#stress-tests"
            className="px-6 py-3 rounded-md border border-border font-mono text-sm tracking-[0.15em] uppercase hover:border-rogue-green hover:text-rogue-green transition-colors"
          >
            How it works
          </Link>
        </div>

        {/* Scroll cue */}
        <div
          className="absolute bottom-6 left-1/2 -translate-x-1/2 flex flex-col items-center gap-1 text-muted-foreground rogue-scroll-cue"
          aria-hidden
        >
          <span className="font-mono text-[10px] uppercase tracking-[0.2em]">
            scroll
          </span>
          <span className="text-base leading-none">↓</span>
        </div>
      </div>
    </PausedOffscreen>
  );
}

function HeroStat({
  value,
  label,
  sub,
  tint,
}: {
  value: number | null;
  label: string;
  sub: string;
  tint: "green" | "red";
}) {
  const tintClass = tint === "green" ? "text-rogue-green" : "text-rogue-red";
  return (
    <div>
      <p
        className={`text-3xl md:text-4xl font-bold tabular-nums leading-none ${tintClass}`}
      >
        {value !== null ? value.toLocaleString() : "—"}
      </p>
      <p className="text-[10px] font-mono uppercase tracking-[0.18em] text-muted-foreground mt-2">
        {label}
      </p>
      <p className="text-[10px] text-muted-foreground/70 mt-0.5">{sub}</p>
    </div>
  );
}
