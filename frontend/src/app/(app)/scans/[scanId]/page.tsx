import Link from "next/link";
import { redirect } from "next/navigation";
import { platformApi, type ScanRecord } from "@/lib/platform-api";
import { getApiKey } from "@/lib/session";
import { ScanProgress } from "@/components/scan-progress";

/**
 * /scans/{scanId} — the scan DETAIL page.
 *
 * Server shell: it owns the route + the initial `ScanRecord` fetch, then hands the
 * live state off to the `"use client"` `ScanProgress` component, which polls
 * `getScan` every ~2s until terminal and links through to the report
 * (docs/platform/dashboard/live-scan-ux.md). The server fetch seeds the client so
 * the first paint is real data, not a spinner.
 *
 * Auth: `(app)/layout.tsx` gates the session; we re-read the key here (server-only)
 * and thread the bearer into the seed fetch. The client poller never sees it — it
 * polls the same-origin `/api/scans/{id}` route, which re-attaches the bearer.
 */
export const dynamic = "force-dynamic"; // tenant data — never statically cached

export default async function ScanDetailPage({
  params,
}: {
  // Next.js 16: route params are async.
  params: Promise<{ scanId: string }>;
}) {
  const { scanId } = await params;

  const key = await getApiKey();
  if (!key) redirect("/sign-in");

  let record: ScanRecord | null = null;
  let loadError: string | null = null;
  try {
    record = await platformApi.getScan(scanId, key);
  } catch (e) {
    loadError = e instanceof Error ? e.message : "Failed to load this scan.";
  }

  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-3xl mx-auto px-6 py-10 space-y-8">
        <header className="space-y-2 animate-rogue-fade-up">
          <Link
            href="/scans"
            className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green hover:underline"
          >
            ← /scans
          </Link>
          <h1 className="text-3xl font-bold tracking-tight font-mono break-all">
            {scanId}
          </h1>
          {record && (
            <p className="text-sm text-muted-foreground font-mono">
              {targetLabel(record)} · {record.pack} pack · {record.n_tests} tests planned
            </p>
          )}
        </header>

        {loadError ? (
          <div className="rounded-lg border border-rogue-red/40 bg-rogue-red/10 p-6 font-mono text-sm text-rogue-red">
            <p className="font-bold">Couldn&apos;t load this scan</p>
            <p className="mt-1 text-xs opacity-80">{loadError}</p>
            <Link
              href="/scans"
              className="mt-3 inline-flex text-xs uppercase tracking-[0.15em] hover:underline"
            >
              ← back to scans
            </Link>
          </div>
        ) : record ? (
          <ScanProgress initial={record} />
        ) : null}
      </div>
    </main>
  );
}

function targetLabel(s: ScanRecord): string {
  const t = s.target ?? {};
  return t.model || t.provider || t.endpoint || "unknown target";
}
