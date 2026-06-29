"use client";

import { useEffect, useRef, useState } from "react";
import type { AttackPrimitive } from "@/lib/api";
import { useSseFeed } from "@/components/sse-feed-provider";
import { sourceBackendLabel } from "@/lib/source-backend";

/**
 * Live-streaming attack ticker for the home page hero.
 *
 * Reads from the shared SseFeedProvider (one EventSource for the whole app).
 * On each new snapshot, diffs incoming primitives against a seenIds ref and
 * slides any new ones in from the top with a fade-up + brief green-glow flash.
 *
 * Renders 5 rows max, anything older just falls off the bottom. Each row is
 * a tinted-severity card with title, family, source backend, and a clickable
 * link to the source.
 */
export function LiveAttackTicker({
  initialAttacks,
}: {
  initialAttacks: AttackPrimitive[];
}) {
  const { primitives, snapshotAt } = useSseFeed();
  const [attacks, setAttacks] = useState<AttackPrimitive[]>(initialAttacks);
  const [pulseKey, setPulseKey] = useState<string | null>(null);
  const seenIds = useRef<Set<string>>(
    new Set(initialAttacks.map((a) => a.primitive_id)),
  );

  useEffect(() => {
    if (!snapshotAt) return;
    const newOnes = primitives.filter(
      (p) => !seenIds.current.has(p.primitive_id),
    );
    if (newOnes.length > 0) {
      newOnes.forEach((p) => seenIds.current.add(p.primitive_id));
      setAttacks((prev) => [...newOnes, ...prev].slice(0, 6));
      setPulseKey(newOnes[0].primitive_id);
      const t = window.setTimeout(() => setPulseKey(null), 1500);
      return () => window.clearTimeout(t);
    }
    // Cold-start: server had data but we passed in empty initialAttacks.
    if (attacks.length === 0 && primitives.length > 0) {
      const seed = primitives.slice(0, 6);
      seed.forEach((p) => seenIds.current.add(p.primitive_id));
      setAttacks(seed);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [primitives, snapshotAt]);

  if (!attacks || attacks.length === 0) {
    return (
      <div className="border border-border rounded-lg p-6 bg-card/40 backdrop-blur-sm font-mono text-xs text-muted-foreground">
        {"// waiting for live feed... (run scripts/harvest/harvest_once.py to seed)"}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green flex items-center gap-2">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-rogue-green animate-rogue-pulse-green" />
          live · streaming
        </p>
        <p className="font-mono text-[10px] text-muted-foreground">
          {attacks.length} most-recent
        </p>
      </div>
      <ul className="space-y-1.5">
        {attacks.slice(0, 5).map((a) => (
          <TickerRow
            key={a.primitive_id}
            attack={a}
            pulse={pulseKey === a.primitive_id}
          />
        ))}
      </ul>
    </div>
  );
}

function TickerRow({
  attack,
  pulse,
}: {
  attack: AttackPrimitive;
  pulse: boolean;
}) {
  const sev = (attack.base_severity || "medium").toLowerCase();
  const sevDot = {
    critical: "bg-rogue-red animate-rogue-pulse-critical",
    high: "bg-orange-400",
    medium: "bg-yellow-400",
    low: "bg-blue-400",
  }[sev] ?? "bg-muted-foreground";

  const product = attack.sources?.[0]?.bright_data_product;
  const sourceUrl = attack.sources?.[0]?.url;

  return (
    <li
      className={`rogue-card border rounded-md px-3 py-2 bg-card/40 backdrop-blur-sm transition-all duration-700 ${
        pulse
          ? "border-rogue-green shadow-[0_0_24px_var(--rogue-green-dim)]"
          : "border-border"
      }`}
      style={{ animation: pulse ? "rogue-fade-up 0.5s ease-out" : undefined }}
    >
      <div className="flex items-center gap-3">
        <span className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${sevDot}`} />
        <div className="flex-1 min-w-0">
          <p className="text-sm leading-tight truncate" title={attack.title}>
            {attack.title}
          </p>
          <p className="text-[10px] font-mono text-muted-foreground truncate">
            {attack.family} · {attack.vector}
            {product && (
              <span className="ml-2 text-rogue-green/80 uppercase tracking-wider">
                {sourceBackendLabel(product)}
              </span>
            )}
          </p>
        </div>
        {sourceUrl && (
          <a
            href={sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[10px] font-mono text-muted-foreground hover:text-rogue-green transition-colors flex-shrink-0"
          >
            ↗
          </a>
        )}
      </div>
    </li>
  );
}

/**
 * Marker for the live-counter chip on the home hero.
 */
export function LiveCount({ value }: { value: number }) {
  return <span className="tabular-nums">{value}</span>;
}

/**
 * Compact pill rendered above the ticker, "X attacks in the last 24h".
 * Reads from the shared SseFeedProvider; falls back to initialCount until
 * the first snapshot arrives.
 */
export function LiveAttackCountPill({
  initialCount,
}: {
  initialCount: number;
}) {
  const { count24h, snapshotAt } = useSseFeed();
  return <LiveCount value={snapshotAt ? count24h : initialCount} />;
}
