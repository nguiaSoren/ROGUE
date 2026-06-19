import { track as vercelTrack } from "@vercel/analytics";

/**
 * Thin wrapper around Vercel Analytics custom-event tracking.
 *
 * A single import for the whole app so call sites stay terse:
 *   track("request_demo_submitted")
 *   track("sample_report_download", { source: "footer" })
 *   track("pricing_cta_click", { plan: "team" })
 *
 * Guarded so it no-ops safely on the server (no `window`) and never throws
 * if analytics is unavailable (ad-blockers, dev, etc.), instrumentation
 * must never break a user flow.
 */
export function track(event: string, props?: Record<string, unknown>): void {
  if (typeof window === "undefined") return;
  try {
    // Vercel's `track` accepts string | number | boolean | null values.
    vercelTrack(event, props as Record<string, string | number | boolean | null>);
  } catch {
    // swallow, analytics is best-effort
  }
}
