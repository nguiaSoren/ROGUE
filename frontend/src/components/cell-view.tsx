"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { BreachCellResponse } from "@/lib/api";
import { CellPrimitiveList } from "@/components/cell-primitive-list";
import { ProviderLogo } from "@/components/ui/provider-logo";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

/**
 * Client-side, resilient renderer for one (family × config) cell breakdown.
 *
 * Why client-side: /matrix/cell is a dynamic route (it reads ?family/config/date),
 * so server-rendering it would fetch the API on every request — and a transient
 * Render cold-cycle would surface a hard "502 / cell unavailable" with no
 * recovery. Fetching here lets us retry gateway blips + cap each attempt with a
 * timeout, and show a "waking up — retry" state instead of a dead error. The
 * page shell + loading.tsx render instantly regardless of API state.
 */
async function fetchCell(
  family: string,
  config: string,
  date: string | undefined,
): Promise<BreachCellResponse> {
  const q = new URLSearchParams({ family, config });
  if (date) q.set("date", date);
  const url = `${API_BASE}/api/breaches/cell?${q.toString()}`;
  // Patient retry (1s/2s/3s) so a free-tier cold boot is ridden out rather than
  // shown as an error; each attempt is timeout-capped so a held socket can't hang.
  for (let attempt = 0; ; attempt++) {
    try {
      const r = await fetch(url, { signal: AbortSignal.timeout(12_000) });
      const gateway = r.status === 502 || r.status === 503 || r.status === 504;
      if (gateway && attempt < 3) {
        await new Promise((res) => setTimeout(res, 1000 * (attempt + 1)));
        continue;
      }
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      return (await r.json()) as BreachCellResponse;
    } catch (e) {
      if (attempt < 3) {
        await new Promise((res) => setTimeout(res, 1000 * (attempt + 1)));
        continue;
      }
      throw e;
    }
  }
}

type State =
  | { status: "loading" }
  | { status: "ok"; data: BreachCellResponse }
  | { status: "error" };

export function CellView({
  family,
  config,
  date,
}: {
  family: string;
  config: string;
  date?: string;
}) {
  const [state, setState] = useState<State>({ status: "loading" });
  const [retryNonce, setRetryNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchCell(family, config, date)
      .then((data) => {
        if (!cancelled) setState({ status: "ok", data });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [family, config, date, retryNonce]);

  if (state.status === "loading") {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="h-9 w-2/3 rounded bg-card/60" />
        <div className="h-4 w-1/3 rounded bg-card/40" />
        <div className="mt-8 space-y-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="rounded-lg border border-border bg-card/30 p-5 space-y-3">
              <div className="h-5 w-1/2 rounded bg-card/60" />
              <div className="h-3 w-full rounded bg-card/40" />
              <div className="h-16 w-full rounded bg-card/40" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="space-y-4">
        <Link
          href="/matrix"
          className="inline-block font-mono text-xs text-rogue-green hover:underline"
        >
          ← back to matrix
        </Link>
        <div className="border border-rogue-red/40 rounded-lg p-6 font-mono text-sm text-rogue-red bg-rogue-red/5 space-y-3">
          <p>{"// the API didn't respond (it may be waking up from idle)"}</p>
          <button
            type="button"
            onClick={() => {
              setState({ status: "loading" });
              setRetryNonce((n) => n + 1);
            }}
            className="px-3 py-1.5 border border-rogue-green/40 text-rogue-green rounded-md uppercase tracking-wider text-[10px] hover:bg-rogue-green/10 transition-colors"
          >
            retry
          </button>
        </div>
      </div>
    );
  }

  const data = state.data;
  return (
    <>
      <header className="space-y-2 animate-rogue-fade-up">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
          /matrix/cell · {data.target_date}
        </p>
        <h1 className="text-3xl font-bold tracking-tight">{data.family}</h1>
        <p className="text-sm text-muted-foreground inline-flex items-center gap-1.5 font-mono">
          {data.target_model && (
            <ProviderLogo model={data.target_model} className="text-xs opacity-80" />
          )}
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
    </>
  );
}
