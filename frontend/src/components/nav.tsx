"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Menu, X } from "lucide-react";
import { useSseFeed } from "@/components/sse-feed-provider";
import { COMMERCIAL } from "@/lib/flags";

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
  const [menuOpen, setMenuOpen] = useState(false);

  // Close the mobile menu on route change. Deferred via rAF so this isn't a
  // synchronous setState in the effect body (avoids the cascading-render lint).
  useEffect(() => {
    const id = requestAnimationFrame(() => setMenuOpen(false));
    return () => cancelAnimationFrame(id);
  }, [pathname]);

  const closeMenu = () => setMenuOpen(false);

  useEffect(() => {
    let alive = true;
    const pingHealth = () => {
      // 8s timeout (< the 15s ping interval) so a held socket during a Render
      // cold boot resolves to "down" instead of leaving the status dot stale.
      fetch(`${API_BASE}/api/health`, {
        cache: "no-store",
        signal: AbortSignal.timeout(8000),
      })
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
    <header className="sticky top-0 z-40 border-b border-border bg-background/90">
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
        <nav className="flex items-center gap-3 md:gap-5 text-xs uppercase tracking-widest">
          {/* Threat-intel links, hidden on small screens */}
          <span className="hidden lg:flex items-center gap-5">
            <NavLink href="/feed" active={pathname === "/feed"}>/feed</NavLink>
            <NavLink href="/matrix" active={pathname === "/matrix"}>/matrix</NavLink>
            <NavLink href="/analytics" active={pathname === "/analytics"}>/analytics</NavLink>
            <NavLink href="/brief" active={pathname === "/brief"}>/brief</NavLink>
            <NavLink href="/research" active={pathname === "/research"}>research</NavLink>
          </span>
          {/* Commercial links */}
          <span className="hidden md:flex items-center gap-5">
            <NavLink href="/product" active={pathname === "/product"}>product</NavLink>
            {COMMERCIAL && <NavLink href="/pricing" active={pathname === "/pricing"}>pricing</NavLink>}
            {COMMERCIAL && <NavLink href="/enterprise" active={pathname === "/enterprise"}>enterprise</NavLink>}
            {COMMERCIAL && <NavLink href="/security" active={pathname === "/security"}>security</NavLink>}
            <NavLink href="/resources" active={pathname === "/resources"}>resources</NavLink>
            <NavLink href="/about" active={pathname === "/about"}>about</NavLink>
          </span>
          <LivePill count={count} dbUp={dbUp} />
          <Link
            href="/scans"
            className="hidden sm:inline-block rounded border border-rogue-green/50 px-3 py-1 text-rogue-green transition-colors hover:bg-rogue-green/10"
          >
            dashboard
          </Link>
          <Link
            href={COMMERCIAL ? "/request-demo" : "/early-access"}
            className="rounded bg-rogue-green px-3 py-1 font-semibold text-[#050508] transition-opacity hover:opacity-90"
          >
            {COMMERCIAL ? "request demo" : "early access"}
          </Link>
          {/* Hamburger, only below md, where the inline link groups are hidden */}
          <button
            type="button"
            onClick={() => setMenuOpen((o) => !o)}
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            aria-expanded={menuOpen}
            aria-controls="mobile-nav"
            className="md:hidden inline-flex items-center justify-center rounded border border-rogue-green/50 p-2 text-rogue-green transition-colors hover:bg-rogue-green/10"
          >
            {menuOpen ? (
              <X className="w-5 h-5" />
            ) : (
              <Menu className="w-5 h-5" />
            )}
          </button>
        </nav>
      </div>

      {/* Mobile panel, full nav destinations, only rendered below md */}
      {menuOpen && (
        <nav
          id="mobile-nav"
          className="md:hidden border-t border-border bg-background/95 font-mono"
        >
          <div className="max-w-7xl mx-auto px-6 py-2 flex flex-col text-xs uppercase tracking-widest">
            <MobileLink href="/feed" active={pathname === "/feed"} onClick={closeMenu}>/feed</MobileLink>
            <MobileLink href="/matrix" active={pathname === "/matrix"} onClick={closeMenu}>/matrix</MobileLink>
            <MobileLink href="/analytics" active={pathname === "/analytics"} onClick={closeMenu}>/analytics</MobileLink>
            <MobileLink href="/brief" active={pathname === "/brief"} onClick={closeMenu}>/brief</MobileLink>
            <MobileLink href="/research" active={pathname === "/research"} onClick={closeMenu}>research</MobileLink>
            <div className="my-1 border-t border-border" />
            <MobileLink href="/product" active={pathname === "/product"} onClick={closeMenu}>product</MobileLink>
            {COMMERCIAL && <MobileLink href="/pricing" active={pathname === "/pricing"} onClick={closeMenu}>pricing</MobileLink>}
            {COMMERCIAL && <MobileLink href="/enterprise" active={pathname === "/enterprise"} onClick={closeMenu}>enterprise</MobileLink>}
            {COMMERCIAL && <MobileLink href="/security" active={pathname === "/security"} onClick={closeMenu}>security</MobileLink>}
            <MobileLink href="/resources" active={pathname === "/resources"} onClick={closeMenu}>resources</MobileLink>
            <MobileLink href="/about" active={pathname === "/about"} onClick={closeMenu}>about</MobileLink>
            <div className="my-1 border-t border-border" />
            <MobileLink href="/scans" active={pathname === "/scans"} onClick={closeMenu}>dashboard</MobileLink>
            <Link
              href={COMMERCIAL ? "/request-demo" : "/early-access"}
              onClick={closeMenu}
              className="mt-2 mb-1 rounded bg-rogue-green px-3 py-3 text-center font-semibold text-[#050508] transition-opacity hover:opacity-90"
            >
              {COMMERCIAL ? "request demo" : "early access"}
            </Link>
          </div>
        </nav>
      )}
    </header>
  );
}

function MobileLink({
  href,
  active,
  onClick,
  children,
}: {
  href: string;
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      onClick={onClick}
      data-active={active}
      className={`block py-3 transition-colors ${
        active
          ? "text-rogue-green"
          : "text-muted-foreground hover:text-foreground"
      }`}
    >
      {children}
    </Link>
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
