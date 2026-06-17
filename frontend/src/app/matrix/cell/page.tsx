import { CellView } from "@/components/cell-view";

/**
 * /matrix/cell?family=&config=&date=, every breaching primitive in one
 * (family × config) cell.
 *
 * The matrix grid collapses a cell to its single worst-offending primitive;
 * this page expands it into the full list (>0% any-breach, worst-first), each
 * card in the same format as the cell drawer. Reached from the drawer's
 * "see all breaching primitives in this cell →" link and the /matrix
 * "worst attacker today" callout.
 *
 * This is a dynamic route (reads ?family/config/date), so it deliberately does
 * NO server-side API fetch, a transient Render cold-cycle would otherwise
 * render a hard "502 / cell unavailable" with no recovery. The data is fetched
 * client-side by `CellView` (retry + timeout + a "waking up, retry" state), so
 * the page shell renders instantly and an API blip retries instead of erroring.
 */
export default async function CellPage({
  searchParams,
}: {
  searchParams: Promise<{
    family?: string;
    config?: string;
    date?: string;
    scope?: string;
    attacker?: string;
    from?: string;
  }>;
}) {
  const { family, config, date, scope, attacker, from } = await searchParams;
  const initialScope = scope === "all-time" ? "all-time" : "this-run";
  const initialAttacker = attacker === "augmented" ? "augmented" : "baseline";

  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 py-10 space-y-4">
        {!family || !config ? (
          <div className="border border-rogue-red/40 rounded-lg p-6 font-mono text-sm text-rogue-red bg-rogue-red/5">
            {"// missing ?family= and ?config= query params"}
          </div>
        ) : (
          <CellView
            family={family}
            config={config}
            date={date}
            initialScope={initialScope}
            initialAttacker={initialAttacker}
            from={from}
          />
        )}
      </div>
    </main>
  );
}
