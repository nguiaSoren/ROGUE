import Link from "next/link";
import { redirect } from "next/navigation";
import { LocalTime } from "@/components/local-time";
import { platformApi, type ScanRecord } from "@/lib/platform-api";
import { getApiKey } from "@/lib/session";
import { StatusBadge, ScoreBadge } from "@/components/score-badge";

/**
 * /scans — the scan LIST page (server component).
 *
 * Mirrors the `matrix/page.tsx` async-server-component shape, with the tenancy
 * differences from docs/platform/dashboard/pages-and-routes.md §4: tenant data is
 * per-request (`no-store`, set inside `platformApi`), NOT the 300s ISR the public
 * corpus uses, and a failed fetch renders an explicit error state rather than
 * silently serving stale cross-tenant HTML.
 *
 * Auth: the `(app)` group gates on a session in `(app)/layout.tsx`; we re-read the
 * key here (server-only) and pass the bearer to `listScans(key)`. The redirect is a
 * defensive belt-and-suspenders so TypeScript sees `key` as non-null below.
 */
export const dynamic = "force-dynamic"; // tenant data — never statically cached

export default async function ScansPage() {
  const key = await getApiKey();
  if (!key) redirect("/sign-in");

  let scans: ScanRecord[] = [];
  let loadError: string | null = null;
  try {
    const res = await platformApi.listScans(key, { limit: 50 });
    scans = res.scans;
  } catch (e) {
    loadError = e instanceof Error ? e.message : "Failed to load scans.";
  }

  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-10 space-y-8">
        <header className="flex items-start justify-between gap-4 sm:gap-6 flex-wrap animate-rogue-fade-up">
          <div className="space-y-2">
            <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
              /scans
            </p>
            <h1 className="text-3xl sm:text-4xl font-bold tracking-tight">Scans</h1>
            <p className="text-sm text-muted-foreground max-w-xl leading-relaxed">
              Every red-team scan your org has launched, newest first. Click a row to
              watch a running scan or open its report.
            </p>
          </div>
          <Link
            href="/scans/new"
            className="font-mono text-xs uppercase tracking-[0.15em] text-rogue-green border border-rogue-green/40 rounded-md px-4 py-2 hover:bg-rogue-green/10 transition-colors"
          >
            New scan
          </Link>
        </header>

        {loadError ? (
          <div className="rounded-lg border border-rogue-red/40 bg-rogue-red/10 p-6 font-mono text-sm text-rogue-red">
            <p className="font-bold">Couldn&apos;t load scans</p>
            <p className="mt-1 text-xs opacity-80">{loadError}</p>
          </div>
        ) : scans.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
                  <th className="px-4 py-3 font-medium">Scan</th>
                  <th className="px-4 py-3 font-medium">Target</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium text-right">Breaches</th>
                  <th className="px-4 py-3 font-medium text-right">Score</th>
                  <th className="px-4 py-3 font-medium text-right">Created</th>
                </tr>
              </thead>
              <tbody>
                {scans.map((s) => (
                  <tr
                    key={s.scan_id}
                    className="border-b border-border/50 last:border-0 hover:bg-card/40 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <Link
                        href={`/scans/${encodeURIComponent(s.scan_id)}`}
                        className="font-mono text-xs text-rogue-green hover:underline"
                      >
                        {s.scan_id}
                      </Link>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-muted-foreground max-w-[220px] truncate">
                      {targetLabel(s)}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={s.status} />
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums font-mono text-xs">
                      <span className={s.n_breaches > 0 ? "text-rogue-red" : "text-muted-foreground"}>
                        {s.n_breaches}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <ScoreBadge score={s.score} />
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs text-muted-foreground tabular-nums">
                      <LocalTime iso={s.created_at} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </main>
  );
}

function EmptyState() {
  return (
    <div className="rounded-lg border border-dashed border-border p-12 text-center space-y-3">
      <p className="font-mono text-sm text-muted-foreground">No scans yet.</p>
      <p className="text-xs text-muted-foreground/70 max-w-sm mx-auto">
        Launch your first red-team scan against a model endpoint to see breaches,
        a risk score, and a downloadable report here.
      </p>
      <Link
        href="/scans/new"
        className="inline-flex font-mono text-xs uppercase tracking-[0.15em] text-rogue-green border border-rogue-green/40 rounded-md px-4 py-2 hover:bg-rogue-green/10 transition-colors"
      >
        New scan
      </Link>
    </div>
  );
}

/** A human label for the redacted target snapshot (model > provider > endpoint). */
function targetLabel(s: ScanRecord): string {
  const t = s.target ?? {};
  return t.model || t.provider || t.endpoint || "—";
}
