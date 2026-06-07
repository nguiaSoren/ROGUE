/**
 * Instant Suspense fallback for /feed. The feed page is server-rendered with an
 * ISR window but a cold-cache or cold-Render visit still waits on the attacks
 * fetch with no feedback. This skeleton mirrors the page shell — KPI strip,
 * augmentation strip, and the 3-column war-room grid — so the transition into
 * the real feed is seamless. Mirrors matrix/loading.tsx.
 */
export default function FeedLoading() {
  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-7xl mx-auto px-6 py-10 space-y-8 animate-pulse">
        {/* Header */}
        <div className="space-y-2">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
            /feed · loading…
          </p>
          <div className="h-9 w-56 rounded bg-card/60" />
          <div className="h-4 w-96 max-w-full rounded bg-card/40" />
        </div>

        {/* KPI strip */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-20 rounded-md border border-border bg-card/30"
            />
          ))}
        </div>

        {/* Augmentation strip */}
        <div className="h-16 rounded-md border border-border bg-card/20" />

        {/* War-room grid */}
        <div className="grid grid-cols-1 lg:grid-cols-[200px_1fr_320px] gap-4">
          <div className="h-96 rounded-lg border border-border bg-card/20" />
          <div className="space-y-2">
            {[0, 1, 2, 3, 4, 5].map((r) => (
              <div
                key={r}
                className="h-14 rounded-md border border-border bg-card/30"
              />
            ))}
          </div>
          <div className="h-96 rounded-lg border border-border bg-card/20" />
        </div>
      </div>
    </main>
  );
}
