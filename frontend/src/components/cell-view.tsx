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
 * so server-rendering it would fetch the API on every request, and a transient
 * Render cold-cycle would surface a hard "502 / cell unavailable" with no
 * recovery. Fetching here lets us retry gateway blips + cap each attempt with a
 * timeout, and show a "waking up, retry" state instead of a dead error. The
 * page shell + loading.tsx render instantly regardless of API state.
 */
type Scope = "this-run" | "all-time";
type Attacker = "baseline" | "augmented";

async function fetchCell(
  family: string,
  config: string,
  date: string | undefined,
  scope: Scope,
  attacker: Attacker,
): Promise<BreachCellResponse> {
  const q = new URLSearchParams({ family, config, scope, attacker });
  // `date` only narrows the this-run scope; all-time merges every day.
  if (date && scope === "this-run") q.set("date", date);
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
  initialScope,
  initialAttacker,
}: {
  family: string;
  config: string;
  date?: string;
  initialScope: Scope;
  initialAttacker: Attacker;
}) {
  // SCOPE × ATTACKER mirror the matrix 2×2: the page opens in whatever quadrant
  // you clicked from (so a cell that's red all-time / augmented but empty in this
  // run's baseline doesn't open empty), and the toggles flip either axis in place.
  const [scope, setScope] = useState<Scope>(initialScope);
  const [attacker, setAttacker] = useState<Attacker>(initialAttacker);
  const [state, setState] = useState<State>({ status: "loading" });
  const [retryNonce, setRetryNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchCell(family, config, date, scope, attacker)
      .then((data) => {
        if (!cancelled) setState({ status: "ok", data });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [family, config, date, scope, attacker, retryNonce]);

  function flipScope(next: Scope) {
    if (next === scope) return;
    setScope(next);
    setState({ status: "loading" });
  }

  function flipAttacker(next: Attacker) {
    if (next === attacker) return;
    setAttacker(next);
    setState({ status: "loading" });
  }

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
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
            /matrix/cell · {scope === "all-time" ? "all-time" : data.target_date} ·{" "}
            {attacker === "augmented" ? "+augmentations" : "baseline"}
          </p>
          <div className="flex items-center gap-x-4 gap-y-2 flex-wrap">
            <ScopeToggle scope={scope} onChange={flipScope} />
            <AttackerToggle attacker={attacker} onChange={flipAttacker} />
          </div>
        </div>
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
          worst-first · {scope === "all-time" ? "every run day merged" : "this run's day"} ·{" "}
          {attacker === "augmented"
            ? "worst across baseline / persona / PAIR"
            : "raw single-shot"}
          .
        </p>
        <Link
          href="/matrix"
          className="inline-block font-mono text-xs text-rogue-green hover:underline"
        >
          ← back to matrix
        </Link>
      </header>

      <div className="mt-8">
        {data.primitives.length === 0 ? (
          <div className="border border-border rounded-lg p-6 font-mono text-sm text-muted-foreground">
            {`// no breaching primitives in ${
              scope === "all-time" ? "all-time" : "this run's day"
            } · ${attacker === "augmented" ? "+augmentations" : "baseline"} for this cell.`}
            {(scope === "this-run" || attacker === "baseline") && (
              <>
                {" Try "}
                {scope === "this-run" && (
                  <button
                    type="button"
                    onClick={() => flipScope("all-time")}
                    className="text-rogue-green hover:underline"
                  >
                    all-time
                  </button>
                )}
                {scope === "this-run" && attacker === "baseline" && " or "}
                {attacker === "baseline" && (
                  <button
                    type="button"
                    onClick={() => flipAttacker("augmented")}
                    className="text-orange-300 hover:underline"
                  >
                    + augmentations
                  </button>
                )}
                .
              </>
            )}
          </div>
        ) : (
          <CellPrimitiveList primitives={data.primitives} />
        )}
      </div>
    </>
  );
}

function ScopeToggle({
  scope,
  onChange,
}: {
  scope: Scope;
  onChange: (next: Scope) => void;
}) {
  return (
    <div className="inline-flex items-center gap-2">
      <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground">
        scope:
      </span>
      <div className="inline-flex rounded-md border border-border overflow-hidden font-mono text-[10px] uppercase tracking-wider">
        <button
          type="button"
          onClick={() => onChange("this-run")}
          className={`px-3 py-1.5 transition-colors ${
            scope === "this-run"
              ? "bg-rogue-green/15 text-rogue-green"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          This run
        </button>
        <button
          type="button"
          onClick={() => onChange("all-time")}
          className={`px-3 py-1.5 border-l border-border transition-colors ${
            scope === "all-time"
              ? "bg-rogue-green/15 text-rogue-green"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          All-time
        </button>
      </div>
    </div>
  );
}

function AttackerToggle({
  attacker,
  onChange,
}: {
  attacker: Attacker;
  onChange: (next: Attacker) => void;
}) {
  return (
    <div className="inline-flex items-center gap-2">
      <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground">
        attacker:
      </span>
      <div className="inline-flex rounded-md border border-border overflow-hidden font-mono text-[10px] uppercase tracking-wider">
        <button
          type="button"
          onClick={() => onChange("baseline")}
          className={`px-3 py-1.5 transition-colors ${
            attacker === "baseline"
              ? "bg-rogue-green/15 text-rogue-green"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Baseline
        </button>
        <button
          type="button"
          onClick={() => onChange("augmented")}
          className={`px-3 py-1.5 border-l border-border transition-colors ${
            attacker === "augmented"
              ? "bg-rogue-red/15 text-rogue-red"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          + Augmentations
        </button>
      </div>
    </div>
  );
}
