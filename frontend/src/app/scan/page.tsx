import type { Metadata } from "next";

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
            Point ROGUE at your own LLM endpoint and run a live{" "}
            <span className="text-rogue-green">ATTACKER → MODEL → JUDGE</span> red-team. No SDK, no signup —
            just your endpoint and a key. You get back a{" "}
            <span className="text-foreground">shareable breach card</span> in about a minute.
          </p>
        </header>

        <div className="animate-rogue-fade-up" style={{ animationDelay: "0.1s" }}>
          <PublicScan />
        </div>
      </div>
    </main>
  );
}
