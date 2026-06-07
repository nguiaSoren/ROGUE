/**
 * Instant Suspense fallback for /brief. The brief page is server-rendered with
 * an ISR window; a cold-cache or cold-Render visit waits on the markdown brief
 * fetch with no feedback. This skeleton mirrors the page shell — dated masthead,
 * KPI snapshot strip, and a long-form report placeholder — so the transition
 * into the real brief is seamless. Mirrors matrix/loading.tsx.
 */
export default function BriefLoading() {
  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-4xl mx-auto px-6 py-10 space-y-8 animate-pulse">
        {/* Masthead */}
        <div className="flex items-start justify-between gap-6 flex-wrap">
          <div className="space-y-2">
            <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
              /brief · loading…
            </p>
            <div className="h-9 w-72 max-w-full rounded bg-card/60" />
            <div className="h-4 w-48 rounded bg-card/40" />
          </div>
          <div className="flex items-center gap-3">
            <div className="h-10 w-24 rounded-md border border-border bg-card/30" />
            <div className="h-10 w-24 rounded-md border border-border bg-card/30" />
          </div>
        </div>

        {/* KPI snapshot strip */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-20 rounded-md border border-border bg-card/30"
            />
          ))}
        </div>

        {/* Long-form report */}
        <div className="space-y-3 border border-border rounded-lg bg-card/20 p-6">
          {[0, 1, 2, 3, 4, 5, 6, 7].map((r) => (
            <div
              key={r}
              className={`h-4 rounded bg-card/40 ${r % 3 === 0 ? "w-2/3" : "w-full"}`}
            />
          ))}
        </div>
      </div>
    </main>
  );
}
