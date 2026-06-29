/**
 * Maps a harvest-backend identifier to a neutral capability label for display.
 *
 * ROGUE's harvest is scraper-agnostic: a `Fetcher` registry picks the best
 * backend per capability (search / fetch / render / scrape) and any scraper or
 * proxy slots in behind one env var. Provenance is shown by what a backend
 * *does*, never by vendor — so a metered backend reads the same as a keyless one.
 */
const BACKEND_LABELS: Record<string, string> = {
  serp_api: "search",
  web_unlocker: "fetch",
  scraping_browser: "render",
  web_scraper_api: "scrape",
  mcp_server: "MCP",
};

/** Neutral capability label for a source's harvest backend; "direct" when none. */
export function sourceBackendLabel(p: string | null | undefined): string {
  if (!p) return "direct";
  return BACKEND_LABELS[p] ?? p.replace(/_/g, " ");
}
