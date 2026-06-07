/**
 * Instant Suspense fallback for /matrix. The matrix page is server-rendered on
 * demand (it reads ?date= from searchParams), so a cold-cache or cold-Render
 * visit waited on the baseline-matrix fetch with no feedback. This skeleton
 * mirrors the page shell, header, stat capsules, and a grid placeholder, so
 * the transition into the real heatmap is seamless.
 */
export default function MatrixLoading() {
  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-7xl mx-auto px-6 py-10 space-y-8 animate-pulse">
        {/* Header */}
        <div className="flex items-start justify-between gap-6 flex-wrap">
          <div className="space-y-2">
            <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
              /matrix · loading…
            </p>
            <div className="h-9 w-64 rounded bg-card/60" />
            <div className="h-4 w-80 rounded bg-card/40" />
          </div>
          <div className="flex items-center gap-3">
            <div className="h-16 w-32 rounded-md border border-border bg-card/30" />
            <div className="h-16 w-32 rounded-md border border-border bg-card/30" />
          </div>
        </div>

        {/* Grid placeholder */}
        <div className="border border-border rounded-lg bg-card/40 overflow-hidden">
          <div className="h-12 border-b border-border bg-background/60" />
          {[0, 1, 2, 3, 4, 5, 6, 7].map((r) => (
            <div key={r} className="flex border-b border-border/50 last:border-b-0">
              <div className="w-[180px] shrink-0 h-14 border-r border-border bg-background/40" />
              <div className="flex-1 h-14 bg-card/20" />
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}
