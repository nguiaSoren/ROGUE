"use client";

import { useEffect, useRef, useState } from "react";
import type { BreachCell } from "@/lib/api";
import { ProviderLogo } from "@/components/ui/provider-logo";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

type BreachDetail = {
  deployment_config_id: string;
  config_name: string;
  target_model: string;
  n_trials: number;
  n_full_breach: number;
  n_partial_breach: number;
  n_refused: number;
  n_evaded: number;
  n_error: number;
  avg_confidence: number | null;
  last_ran_at: string | null;
};

type AttackDetailResponse = {
  primitive: {
    primitive_id: string;
    title: string;
    family: string;
    vector: string;
    base_severity: string;
    short_description: string;
    payload_template: string | null;
    requires_multi_turn: boolean;
    requires_tools: string[];
    sources?: { url: string; bright_data_product: string | null }[];
  };
  breaches: BreachDetail[];
};

/**
 * Side-drawer that opens when a matrix cell is clicked.
 *
 * Shows the worst-offending primitive for that (family × config) cell, its
 * payload template (with copy button), and the per-trial verdict histogram
 * for THIS config. The "wow, that's the exact prompt that breached
 * gpt-4o-mini" moment.
 */
export function MatrixCellDrawer({
  open,
  cell,
  onClose,
}: {
  open: boolean;
  cell: BreachCell | null;
  onClose: () => void;
}) {
  // Track which primitive_id the current `detail` was fetched for. If the
  // cell changes, we render "loading" until the new fetch lands instead of
  // wiping `detail` synchronously inside the effect (which React 19 flags
  // as a cascading-render anti-pattern).
  const [detail, setDetail] = useState<AttackDetailResponse | null>(null);
  const detailFor = detail?.primitive.primitive_id ?? null;
  const needsFetch = open && cell !== null && detailFor !== cell.primitive_id;

  useEffect(() => {
    if (!needsFetch || !cell) return;
    const ctrl = new AbortController();
    fetch(`${API_BASE}/api/attacks/${cell.primitive_id}`, {
      signal: ctrl.signal,
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
      .then((data) => setDetail(data as AttackDetailResponse))
      .catch(() => {
        /* drawer falls back to "failed to load" via detailFor mismatch */
      });
    return () => ctrl.abort();
  }, [needsFetch, cell]);

  const loading = needsFetch;
  const shownDetail =
    detail && cell && detail.primitive.primitive_id === cell.primitive_id
      ? detail
      : null;

  // Close on Escape.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open || !cell) return null;

  const thisConfigBreach = shownDetail?.breaches.find(
    (b) => b.deployment_config_id === cell.deployment_config_id,
  );

  const rate = cell.any_breach_rate;
  const rateTint =
    rate >= 0.7
      ? "text-rogue-red"
      : rate >= 0.3
        ? "text-orange-300"
        : "text-rogue-green";

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40 animate-rogue-fade-up"
        style={{ animationDuration: "0.2s" }}
        onClick={onClose}
      />

      {/* Drawer */}
      <aside
        className="fixed top-0 right-0 h-full w-full md:w-[560px] bg-background border-l border-rogue-green/30 z-50 overflow-y-auto shadow-[0_0_60px_rgba(0,255,136,0.15)]"
        style={{
          animation: "rogue-slide-in-right 0.3s cubic-bezier(0.16, 1, 0.3, 1)",
        }}
      >
        <div className="sticky top-0 bg-background/95 backdrop-blur-xl border-b border-border z-10 px-5 py-4 flex items-center justify-between">
          <div>
            <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-rogue-green">
              cell · {cell.family}
            </p>
            <p className="text-xs font-mono text-muted-foreground mt-0.5 truncate max-w-[400px]">
              <span className="inline-flex items-center gap-1.5">
                <ProviderLogo model={cell.target_model} className="text-xs opacity-80" />
                {cell.config_name} · {cell.target_model}
              </span>
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-muted-foreground hover:text-rogue-red transition-colors text-2xl leading-none font-mono w-8 h-8 flex items-center justify-center"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="p-5 space-y-5">
          {/* Headline rate */}
          <section className="rogue-card border border-border rounded-lg p-4 bg-card/40">
            <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground">
              any-breach rate
            </p>
            <p className={`text-5xl font-bold tabular-nums mt-2 ${rateTint}`}>
              {Math.round(rate * 100)}%
            </p>
            <p className="text-xs font-mono text-muted-foreground mt-2">
              95% CI: {Math.round(cell.any_breach_ci_lo * 100)}% –{" "}
              {Math.round(cell.any_breach_ci_hi * 100)}% · {cell.n_trials} trials
            </p>
            <p className="text-xs font-mono text-muted-foreground">
              full-breach rate:{" "}
              <span className="text-foreground tabular-nums">
                {Math.round(cell.full_breach_rate * 100)}%
              </span>
              {cell.avg_confidence !== null && (
                <>
                  {" · "}avg judge confidence:{" "}
                  <span className="text-foreground tabular-nums">
                    {(cell.avg_confidence * 100).toFixed(0)}%
                  </span>
                </>
              )}
            </p>
          </section>

          {/* Primitive */}
          {loading && !shownDetail && (
            <p className="text-xs font-mono text-muted-foreground">
              {"// loading primitive..."}
            </p>
          )}
          {shownDetail && (
            <>
              <section className="space-y-2">
                <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground">
                  worst-offending primitive
                </p>
                <h3 className="text-lg font-bold leading-tight">
                  {shownDetail.primitive.title}
                </h3>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  {shownDetail.primitive.short_description}
                </p>
                <div className="flex items-center gap-2 text-[11px] font-mono flex-wrap">
                  <span className="text-muted-foreground">
                    severity:{" "}
                    <span className="text-foreground">
                      {shownDetail.primitive.base_severity}
                    </span>
                  </span>
                  <span className="text-muted-foreground">
                    vector:{" "}
                    <span className="text-foreground">
                      {shownDetail.primitive.vector}
                    </span>
                  </span>
                  {shownDetail.primitive.requires_multi_turn && (
                    <span className="px-1.5 py-0.5 border border-amber-500/40 text-amber-300 rounded-sm uppercase tracking-wider text-[10px]">
                      multi-turn
                    </span>
                  )}
                </div>
              </section>

              {shownDetail.primitive.payload_template && (
                <section>
                  <div className="flex items-center justify-between mb-1.5">
                    <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-rogue-green">
                      payload_template — the prompt that breached this
                    </p>
                    <CopyButton text={shownDetail.primitive.payload_template} />
                  </div>
                  <pre className="text-[11px] font-mono leading-relaxed text-foreground/85 bg-card/60 rounded-md p-3 max-h-72 overflow-y-auto whitespace-pre-wrap break-words border border-border/40">
                    {shownDetail.primitive.payload_template}
                  </pre>
                </section>
              )}

              {thisConfigBreach && (
                <section className="space-y-2">
                  <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground">
                    verdict histogram on this config
                  </p>
                  <VerdictBar
                    full={thisConfigBreach.n_full_breach}
                    partial={thisConfigBreach.n_partial_breach}
                    refused={thisConfigBreach.n_refused}
                    evaded={thisConfigBreach.n_evaded}
                    error={thisConfigBreach.n_error}
                    total={thisConfigBreach.n_trials}
                  />
                  {thisConfigBreach.last_ran_at && (
                    <p className="text-[10px] font-mono text-muted-foreground">
                      last run{" "}
                      {new Date(thisConfigBreach.last_ran_at).toLocaleString()}
                    </p>
                  )}
                </section>
              )}

              {shownDetail.primitive.sources &&
                shownDetail.primitive.sources.length > 0 && (
                  <section>
                    <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground mb-1.5">
                      provenance
                    </p>
                    <ul className="space-y-1">
                      {shownDetail.primitive.sources.slice(0, 5).map((s) => (
                        <li key={s.url} className="text-[11px] font-mono">
                          {s.bright_data_product && (
                            <span className="text-[10px] px-1.5 py-0.5 border border-rogue-green/40 text-rogue-green rounded-sm uppercase tracking-wider mr-2">
                              {s.bright_data_product}
                            </span>
                          )}
                          <a
                            href={s.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-rogue-green hover:underline truncate inline-block max-w-[380px] align-middle"
                            title={s.url}
                          >
                            {s.url} ↗
                          </a>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
            </>
          )}

        </div>
      </aside>
    </>
  );
}

function VerdictBar({
  full,
  partial,
  refused,
  evaded,
  error,
  total,
}: {
  full: number;
  partial: number;
  refused: number;
  evaded: number;
  error: number;
  total: number;
}) {
  if (total === 0) return null;
  const segments = [
    { label: "full breach", n: full, color: "bg-rogue-red" },
    { label: "partial", n: partial, color: "bg-orange-400" },
    { label: "evaded", n: evaded, color: "bg-yellow-400" },
    { label: "refused", n: refused, color: "bg-rogue-green" },
    { label: "error", n: error, color: "bg-muted-foreground/50" },
  ].filter((s) => s.n > 0);
  return (
    <div className="space-y-2">
      <div className="flex h-3 rounded-sm overflow-hidden border border-border">
        {segments.map((s) => (
          <div
            key={s.label}
            className={s.color}
            style={{ width: `${(s.n / total) * 100}%` }}
            title={`${s.label}: ${s.n}/${total}`}
          />
        ))}
      </div>
      <ul className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] font-mono">
        {segments.map((s) => (
          <li key={s.label} className="flex items-center gap-2">
            <span className={`inline-block w-2 h-2 rounded-sm ${s.color}`} />
            <span className="text-muted-foreground flex-1">{s.label}</span>
            <span className="tabular-nums text-foreground">{s.n}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<number | null>(null);
  useEffect(() => {
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    };
  }, []);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          if (timerRef.current !== null) window.clearTimeout(timerRef.current);
          timerRef.current = window.setTimeout(() => setCopied(false), 1500);
        } catch {
          /* swallow */
        }
      }}
      className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground hover:text-rogue-green transition-colors px-2 py-0.5 border border-border rounded-sm"
    >
      {copied ? "copied ✓" : "copy"}
    </button>
  );
}
