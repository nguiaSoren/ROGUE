import type { Metadata } from "next";

import { PopularCards } from "@/components/popular-cards";
import { PublicScan } from "@/components/public-scan";

/**
 * /scan — public, zero-install self-serve red-team.
 *
 * A visitor points ROGUE at their OWN model endpoint, runs a small bounded
 * ATTACKER → MODEL → JUDGE scan, and gets back a shareable breach card. Public
 * route (NOT under the `(app)` auth group), sibling to /try and /leaderboard.
 *
 * Server-component shell: it only renders the metadata + the static intro and
 * mounts the `<PublicScan />` client form, which owns all the fetch/loading/
 * result state. No live API call at render time — the form talks to the Wave
 * backend (`POST {API_BASE}/api/public-scan`) on submit.
 */
export const metadata: Metadata = {
  title: "Scan your model for jailbreaks — get a shareable breach card · ROGUE",
  description:
    "Point ROGUE at your own LLM endpoint and run a live ATTACKER → MODEL → JUDGE red-team — zero install. Get back a shareable breach card. Only scan endpoints you own or are authorized to test; keys are never stored or logged.",
  openGraph: {
    title: "Scan your model for jailbreaks — get a shareable breach card",
    description:
      "Point ROGUE at your own LLM endpoint and run a live red-team in ~10–60s — zero install. Get back a shareable breach card.",
    url: "/scan",
    siteName: "ROGUE",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Scan your model for jailbreaks — get a shareable breach card",
    description: "Point ROGUE at your own LLM endpoint and run a live red-team in ~10–60s — zero install.",
  },
};

export default function ScanPage() {
  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-12 space-y-10">
        <header className="space-y-3 animate-rogue-fade-up">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
            /scan · zero install
          </p>
          <h1 className="text-3xl sm:text-4xl font-bold tracking-tight">
            Scan your model for jailbreaks
          </h1>
          <p className="text-sm text-muted-foreground max-w-2xl leading-relaxed">
            No SDK, no signup. Pick a{" "}
            <span className="text-foreground">popular model</span> to see its already-measured breach
            card instantly — or point ROGUE at your own endpoint to run a live{" "}
            <span className="text-rogue-green">ATTACKER → MODEL → JUDGE</span> red-team and get back a{" "}
            <span className="text-foreground">shareable breach card</span> in about a minute.
          </p>
        </header>

        {/* Path A — zero-input, zero-cost: see a popular model's pre-rendered
            breach card. The "no endpoint?" path for a visitor who has nothing
            to type into the form yet. Purely client-side, no API call. */}
        <section className="animate-rogue-fade-up" style={{ animationDelay: "0.1s" }}>
          <PopularCards />
        </section>

        {/* Visual divider between the two clearly-separate paths. */}
        <div className="flex items-center gap-4 animate-rogue-fade-up" style={{ animationDelay: "0.15s" }}>
          <span className="h-px flex-1 bg-border/60" />
          <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
            or scan your own
          </span>
          <span className="h-px flex-1 bg-border/60" />
        </div>

        {/* Path B — the live self-serve scan against the visitor's OWN endpoint. */}
        <section className="space-y-3 animate-rogue-fade-up" style={{ animationDelay: "0.2s" }}>
          <div className="space-y-2">
            <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
              have an endpoint? · live scan
            </p>
            <h2 className="text-2xl sm:text-3xl font-bold tracking-tight">Scan your own model</h2>
            <p className="text-sm text-muted-foreground max-w-2xl leading-relaxed">
              Point ROGUE at your own LLM endpoint and run a live{" "}
              <span className="text-rogue-green">ATTACKER → MODEL → JUDGE</span> red-team. You get back
              your own shareable breach card in about a minute.
            </p>
          </div>
          <PublicScan />
        </section>
      </div>
    </main>
  );
}
