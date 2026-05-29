"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useSseFeed } from "@/components/sse-feed-provider";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

/**
 * Top nav. Sticky, semi-transparent, blurred backdrop. Active-link styling
 * via the `.rogue-nav-link[data-active="true"]` CSS hook.
 *
 * The right-side "DB · UP · N 24h" pill reads from the shared SseFeedProvider
 * (the single /api/sse/feed connection for the whole app) plus an independent
 * /api/health poll for the up/down dot.
 */
export function Nav() {
  const pathname = usePathname();
  const { count24h, snapshotAt } = useSseFeed();
  const count = snapshotAt ? count24h : null;
  const [dbUp, setDbUp] = useState<boolean | null>(null);

  useEffect(() => {
    let alive = true;
    const pingHealth = () => {
      fetch(`${API_BASE}/api/health`, { cache: "no-store" })
        .then((r) => r.json())
        .then((d: { db?: string }) => {
          if (alive) setDbUp(d.db === "up");
        })
        .catch(() => alive && setDbUp(false));
    };
    pingHealth();
    const interval = window.setInterval(pingHealth, 15000);
    return () => {
      alive = false;
      window.clearInterval(interval);
    };
  }, []);

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/70 backdrop-blur-xl">
      <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between font-mono">
        <Link
          href="/"
          className="text-sm font-bold tracking-tight flex items-center gap-2 group"
        >
          <span className="inline-block w-2 h-2 rounded-full bg-rogue-green animate-rogue-pulse-green" />
          <span className="text-rogue-green group-hover:rogue-glitch">ROGUE</span>
          <span className="text-muted-foreground hidden sm:inline">
            · open-web threat intel
          </span>
        </Link>
        <nav className="flex items-center gap-4 md:gap-6 text-xs uppercase tracking-widest">
          <NavLink href="/feed" active={pathname === "/feed"}>/feed</NavLink>
          <NavLink href="/matrix" active={pathname === "/matrix"}>/matrix</NavLink>
          <NavLink href="/brief" active={pathname === "/brief"}>/brief</NavLink>
          <LivePill count={count} dbUp={dbUp} />
        </nav>
      </div>
    </header>
  );
}

function NavLink({
  href,
  active,
  children,
}: {
  href: string;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      data-active={active}
      className={`rogue-nav-link transition-colors ${
        active ? "text-rogue-green" : "text-muted-foreground hover:text-foreground"
      }`}
    >
      {children}
    </Link>
  );
}

function LivePill({
  count,
  dbUp,
}: {
  count: number | null;
  dbUp: boolean | null;
}) {
  const tint =
    dbUp === false
      ? "border-rogue-red/40 text-rogue-red bg-rogue-red/10"
      : "border-rogue-green/40 text-rogue-green bg-rogue-green/10";
  const dotClass =
    dbUp === false
      ? "bg-rogue-red"
      : "bg-rogue-green animate-rogue-pulse-green";

  return (
    <span
      className={`hidden md:inline-flex items-center gap-1.5 px-2.5 py-1 border rounded-md text-[10px] tracking-wider ${tint}`}
      title="Live status from /api/health and /api/sse/feed"
    >
      <span className={`inline-block w-1.5 h-1.5 rounded-full ${dotClass}`} />
      {dbUp === false ? "db down" : "live"}
      {count !== null && (
        <span className="text-muted-foreground ml-1 tabular-nums">
          · {count} 24h
        </span>
      )}
    </span>
  );
}
