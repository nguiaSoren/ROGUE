/**
 * Instant Suspense fallback for /matrix/cell. The cell page server-renders a
 * (family × config) breakdown against the API, which can take a second or two
 * on a cold Render instance — without this, a click on "worst attacker today"
 * (or "see all primitives") froze on the previous page with no feedback. This
 * mirrors the CellShell layout so the skeleton → content swap is seamless.
 */
export default function CellLoading() {
  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-4xl mx-auto px-6 py-10 space-y-4 animate-pulse">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
          /matrix/cell · loading…
        </p>
        <div className="h-9 w-2/3 rounded bg-card/60" />
        <div className="h-4 w-1/3 rounded bg-card/40" />
        <div className="h-4 w-1/2 rounded bg-card/40" />
        <div className="mt-8 space-y-4">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="rounded-lg border border-border bg-card/30 p-5 space-y-3"
            >
              <div className="h-5 w-1/2 rounded bg-card/60" />
              <div className="h-3 w-full rounded bg-card/40" />
              <div className="h-3 w-3/4 rounded bg-card/40" />
              <div className="h-16 w-full rounded bg-card/40" />
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}
