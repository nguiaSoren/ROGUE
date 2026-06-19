"use client"; // Error boundaries must be Client Components

import { useEffect } from "react";
import Link from "next/link";

/**
 * Route-segment error boundary. Catches unexpected runtime errors thrown while
 * rendering a page (e.g. a backend fetch that exhausted its retries) and shows a
 * recoverable fallback in the site's dark/rogue terminal aesthetic.
 *
 * `unstable_retry` (Next 16.2+) re-fetches and re-renders the boundary's
 * children, the right primitive here because most failures are a transient
 * Render cold-boot, not a permanent fault.
 */
export default function Error({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  useEffect(() => {
    // Surface to the browser console / any error-reporting hook.
    console.error(error);
  }, [error]);

  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-2xl mx-auto px-6 py-24 md:py-32 text-center space-y-6">
        <p className="font-mono text-[11px] uppercase tracking-[0.25em] text-rogue-red">
          {"// runtime fault"}
        </p>
        <h1 className="text-3xl md:text-4xl font-bold tracking-tight">
          Something broke on our side.
        </h1>
        <p className="text-[17px] text-foreground leading-relaxed">
          This is usually a transient cold-boot of the threat-intel API. Give it
          a second and try again, if it persists, the backend is mid-restart.
        </p>
        {error.digest && (
          <p className="font-mono text-[11px] text-muted-foreground/60">
            ref: {error.digest}
          </p>
        )}
        <div className="flex flex-col sm:flex-row gap-3 justify-center items-center pt-2">
          <button
            type="button"
            onClick={() => unstable_retry()}
            className="inline-flex items-center justify-center rounded-lg px-6 py-3 bg-rogue-green text-black font-mono text-sm font-bold tracking-[0.15em] uppercase transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rogue-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            Try again
          </button>
          <Link
            href="/"
            className="font-mono text-xs uppercase tracking-[0.15em] text-muted-foreground transition-colors hover:text-rogue-green"
          >
            Back to home
          </Link>
        </div>
      </div>
    </main>
  );
}
