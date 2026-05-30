import Link from "next/link";
import { api } from "@/lib/api";
import { CellPrimitiveList } from "@/components/cell-primitive-list";
import { ProviderLogo } from "@/components/ui/provider-logo";

/**
 * /matrix/cell?family=&config=&date= — every breaching primitive in one
 * (family × config) cell.
 *
 * The matrix grid collapses a cell to its single worst-offending primitive;
 * this page expands it into the full list (>0% any-breach, worst-first), each
 * card in the same format as the cell drawer. Reached from the drawer's
 * "see all breaching primitives in this cell →" link.
 */
export default async function CellPage({
  searchParams,
}: {
  searchParams: Promise<{ family?: string; config?: string; date?: string }>;
}) {
  const { family, config, date } = await searchParams;

  if (!family || !config) {
    return (
      <CellShell title="Cell breakdown">
        <div className="border border-rogue-red/40 rounded-lg p-6 font-mono text-sm text-rogue-red bg-rogue-red/5">
          {"// missing ?family= and ?config= query params"}
        </div>
      </CellShell>
    );
  }

  let data: Awaited<ReturnType<typeof api.breachCell>> | null = null;
  let error: string | null = null;
  try {
    data = await api.breachCell(family, config, date);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  if (error || !data) {
    return (
      <CellShell title="Cell breakdown">
        <div className="border border-rogue-red/40 rounded-lg p-6 font-mono text-sm text-rogue-red bg-rogue-red/5">
          {`// cell unavailable: ${error ?? "no data"}`}
        </div>
      </CellShell>
    );
  }

  return (
    <CellShell title={`${data.family} × ${data.config_name}`}>
      <header className="space-y-2 animate-rogue-fade-up">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
          /matrix/cell · {data.target_date}
        </p>
        <h1 className="text-3xl font-bold tracking-tight">{data.family}</h1>
        <p className="text-sm text-muted-foreground inline-flex items-center gap-1.5 font-mono">
          {data.target_model && <ProviderLogo model={data.target_model} className="text-xs opacity-80" />}
          {data.config_name}
          {data.target_model ? ` · ${data.target_model}` : ""}
        </p>
        <p className="text-sm text-muted-foreground">
          <span className="text-foreground">{data.n_primitives}</span> breaching{" "}
          {data.n_primitives === 1 ? "primitive" : "primitives"} (&gt;0% any-breach),
          worst-first.
        </p>
        <Link
          href="/matrix"
          className="inline-block font-mono text-xs text-rogue-green hover:underline"
        >
          ← back to matrix
        </Link>
      </header>

      <div className="mt-8">
        <CellPrimitiveList primitives={data.primitives} />
      </div>
    </CellShell>
  );
}

function CellShell({ children }: { title?: string; children: React.ReactNode }) {
  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-4xl mx-auto px-6 py-10 space-y-4">{children}</div>
    </main>
  );
}
