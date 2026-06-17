/**
 * Instant Suspense fallback for /leaderboard. Mirrors the page shell — header,
 * stat capsules, the submit CTA strip, and the ranked-row table — so the
 * transition into the real board is seamless on a cold-cache / cold-Render visit.
 */
export default function LeaderboardLoading() {
  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-5xl mx-auto px-6 py-10 space-y-8 animate-pulse">
        {/* Header */}
        <div className="flex items-start justify-between gap-6 flex-wrap">
          <div className="space-y-2">
            <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
              /leaderboard · loading…
            </p>
            <div className="h-9 w-72 rounded bg-card/60" />
            <div className="h-4 w-96 rounded bg-card/40" />
          </div>
          <div className="flex items-center gap-3">
            <div className="h-16 w-32 rounded-md border border-border bg-card/30" />
            <div className="h-16 w-32 rounded-md border border-border bg-card/30" />
          </div>
        </div>

        {/* Submit CTA strip */}
        <div className="h-20 rounded-lg border border-border bg-card/30" />

        {/* Board */}
        <div className="border border-border rounded-lg bg-card/40 overflow-hidden">
          <div className="h-10 border-b border-border bg-background/60" />
          {[0, 1, 2, 3, 4, 5, 6, 7].map((r) => (
            <div
              key={r}
              className="flex items-center gap-3 px-4 h-16 border-b border-border/50 last:border-b-0"
            >
              <div className="h-7 w-7 rounded-md bg-card/60" />
              <div className="h-4 w-40 rounded bg-card/50" />
              <div className="h-2.5 flex-1 rounded-full bg-card/40" />
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}
