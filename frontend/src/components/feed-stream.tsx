"use client";

import { useMemo, useState } from "react";
import { api, type AttacksResponse } from "@/lib/api";
import { AttackRow } from "@/components/attack-row";
import { sourceBackendLabel } from "@/lib/source-backend";

/**
 * Client-side time-window control for the /feed attack stream.
 *
 * The page server-renders the default 7-day window (instant first paint + ISR),
 * then hands the LEFT intel ribbons + CENTER attack list to this component so
 * the user can re-scope the window, today | 7 days | all time, without a
 * navigation round-trip. Keeping it client-side (not a `?window=` searchParam)
 * preserves the page's static render, the same reason /matrix reads its run-day
 * override from `window.location` rather than `useSearchParams`.
 *
 * Renders BOTH the left aside and center section as a fragment so it drops into
 * the page's existing `grid-cols-[220px_1fr_300px]` war-room layout untouched
 * (the right sidebar stays server-rendered).
 */

const WINDOWS = [
  { key: "today", label: "Today", since_days: 1 },
  { key: "7d", label: "7 days", since_days: 7 },
  { key: "all", label: "All time", since_days: undefined },
] as const;

type WindowKey = (typeof WINDOWS)[number]["key"];

export function FeedStream({
  initialAttacks,
}: {
  // The server's 7-day fetch, seeds the default window so no client re-fetch
  // happens on load; only changing the window triggers one.
  initialAttacks: AttacksResponse;
}) {
  const [windowKey, setWindowKey] = useState<WindowKey>("7d");
  const [attacks, setAttacks] = useState<AttacksResponse>(initialAttacks);
  const [loading, setLoading] = useState(false);
  const [errored, setErrored] = useState(false);

  function selectWindow(key: WindowKey) {
    if (key === windowKey || loading) return;
    const win = WINDOWS.find((w) => w.key === key)!;
    setWindowKey(key);
    setLoading(true);
    setErrored(false);
    api
      .attacks({ since_days: win.since_days, limit: 50 })
      .then((r) => setAttacks(r))
      .catch(() => setErrored(true))
      .finally(() => setLoading(false));
  }

  const list = useMemo(() => attacks.attacks ?? [], [attacks]);

  // Family + source-backend histograms for the left ribbon, recomputed
  // from whatever window is currently loaded.
  const familyCounts = useMemo(() => topCounts(list.map((a) => a.family), 8), [list]);
  const productCounts = useMemo(
    () =>
      topCounts(
        list.map((a) => {
          const p = a.sources?.[0]?.bright_data_product;
          return p ? sourceBackendLabel(p) : null;
        }),
      ),
    [list],
  );

  const windowLabel = WINDOWS.find((w) => w.key === windowKey)!.label.toLowerCase();
  // The API relabels to "newest rows regardless of recency" when the window is
  // empty and it falls back, surface that so the count isn't read as in-window.
  const stale = Boolean(attacks.stale) && windowKey !== "all";

  return (
    <>
      {/* LEFT, intel ribbon: families + products distribution */}
      <aside className="space-y-4 lg:order-1">
        <IntelRibbon
          title="hot families"
          data={familyCounts}
          accent="var(--rogue-green)"
          empty="no attacks in window"
        />
        <IntelRibbon
          title="by source backend"
          data={productCounts}
          accent="#22d3ee"
          empty="no provenance yet"
        />
      </aside>

      {/* CENTER, time toggle + attack list */}
      <section className="space-y-3 lg:order-2 min-w-0">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <h2 className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
            newest attacks, click row to expand
          </h2>
          {/* Window segmented control, styling mirrors the /matrix scope toggle. */}
          <div className="inline-flex items-center gap-2">
            <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground">
              window:
            </span>
            <div className="inline-flex rounded-md border border-border overflow-hidden font-mono text-[10px] uppercase tracking-wider">
              {WINDOWS.map((w, i) => (
                <button
                  key={w.key}
                  type="button"
                  onClick={() => selectWindow(w.key)}
                  className={`px-3 py-1.5 transition-colors ${
                    i > 0 ? "border-l border-border" : ""
                  } ${
                    windowKey === w.key
                      ? "bg-rogue-green/15 text-rogue-green"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {w.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="flex items-baseline justify-between">
          <p className="font-mono text-[10px] text-muted-foreground">
            {loading ? (
              <span className="text-rogue-green animate-pulse">loading {windowLabel}…</span>
            ) : errored ? (
              <span className="text-rogue-red">
                {"// couldn't load, the API may be waking up; pick a window to retry"}
              </span>
            ) : stale ? (
              <span>
                no attacks in {windowLabel} · showing newest {list.length}
              </span>
            ) : (
              <span>
                {list.length} shown · {windowLabel}
              </span>
            )}
          </p>
        </div>

        {list.length ? (
          <ul className="space-y-2">
            {list.map((a, i) => (
              <AttackRow key={a.primitive_id} attack={a} index={i} />
            ))}
          </ul>
        ) : (
          <div className="border border-border rounded-lg p-6 font-mono text-sm text-muted-foreground">
            {loading
              ? "// loading…"
              : `// no attacks in ${windowLabel}.`}
          </div>
        )}
      </section>
    </>
  );
}

// ---------------------------------------------------------------------------

/** Top-N label frequencies, descending. Nulls dropped. */
function topCounts(
  values: (string | null)[],
  limit?: number,
): { label: string; value: number }[] {
  const m = new Map<string, number>();
  for (const v of values) {
    if (!v) continue;
    m.set(v, (m.get(v) ?? 0) + 1);
  }
  const sorted = Array.from(m.entries())
    .sort(([, a], [, b]) => b - a)
    .map(([label, value]) => ({ label, value }));
  return limit ? sorted.slice(0, limit) : sorted;
}

function IntelRibbon({
  title,
  data,
  accent,
  empty,
}: {
  title: string;
  data: { label: string; value: number }[];
  accent: string;
  empty: string;
}) {
  const peak = data.length > 0 ? Math.max(...data.map((d) => d.value)) : 1;
  return (
    <div className="rogue-card border border-border rounded-lg p-4 bg-card/40 backdrop-blur-sm space-y-3">
      <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground">
        {title}
      </p>
      {data.length === 0 ? (
        <p className="text-[11px] font-mono text-muted-foreground">{`// ${empty}`}</p>
      ) : (
        <ul className="space-y-1.5">
          {data.map((d) => {
            const pct = (d.value / peak) * 100;
            return (
              <li key={d.label} className="text-[11px] font-mono space-y-0.5">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate text-foreground" title={d.label}>
                    {d.label}
                  </span>
                  <span className="tabular-nums text-muted-foreground">{d.value}</span>
                </div>
                <span className="block h-1 bg-card/60 rounded-sm overflow-hidden">
                  <span
                    className="block h-full rounded-sm transition-all duration-700 ease-out"
                    style={{
                      width: `${pct}%`,
                      background: accent,
                      boxShadow: `0 0 6px ${accent}88`,
                    }}
                  />
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
