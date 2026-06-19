"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { AttackPrimitive } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

/**
 * Single shared EventSource for /api/sse/feed.
 *
 * Before: nav, LiveAttackTicker, and LiveAttackCountPill each opened their
 * own SSE connection, three concurrent streams to the same endpoint per
 * page load, three retry loops when the backend is down. Now a single
 * connection at the widest window (since_days=2) populates this context
 * and every consumer reads from it.
 *
 * The backend (src/rogue/api/main.py: /api/sse/feed) sends one snapshot
 * per connection followed by heartbeats. New snapshots only arrive on
 * reconnect (browser auto-retries on disconnect), so primitives state
 * here changes at most once per connection lifecycle, there is no
 * per-render storm even if consumers depend on `primitives` directly.
 */

type SseSnapshot = {
  primitives: AttackPrimitive[];
  count: number;
  count24h: number;
  snapshotAt: string | null;
};

const EMPTY: SseSnapshot = {
  primitives: [],
  count: 0,
  count24h: 0,
  snapshotAt: null,
};

const SseFeedContext = createContext<SseSnapshot>(EMPTY);

export function useSseFeed(): SseSnapshot {
  return useContext(SseFeedContext);
}

export function SseFeedProvider({ children }: { children: React.ReactNode }) {
  const [snapshot, setSnapshot] = useState<SseSnapshot>(EMPTY);

  useEffect(() => {
    const es = new EventSource(`${API_BASE}/api/sse/feed?since_days=2`);

    const handler = (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as {
          primitives?: AttackPrimitive[];
          count?: number;
          now?: string;
        };
        const primitives = data.primitives ?? [];
        const dayCutoff = Date.now() - 24 * 60 * 60 * 1000;
        const count24h = primitives.reduce((n, p) => {
          if (!p.discovered_at) return n;
          const t = Date.parse(p.discovered_at);
          return Number.isFinite(t) && t >= dayCutoff ? n + 1 : n;
        }, 0);
        setSnapshot({
          primitives,
          count: typeof data.count === "number" ? data.count : primitives.length,
          count24h,
          snapshotAt: data.now ?? new Date().toISOString(),
        });
      } catch {
        /* swallow malformed event */
      }
    };

    es.addEventListener("snapshot", handler as EventListener);
    return () => {
      es.removeEventListener("snapshot", handler as EventListener);
      es.close();
    };
  }, []);

  // Memo so the context value reference only changes when snapshot does.
  const value = useMemo(() => snapshot, [snapshot]);

  return (
    <SseFeedContext.Provider value={value}>{children}</SseFeedContext.Provider>
  );
}
