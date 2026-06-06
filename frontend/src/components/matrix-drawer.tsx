"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
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
    requires_multimodal?: boolean;
    has_image?: boolean;
    sources?: { url: string; bright_data_product: string | null }[];
  };
  breaches: BreachDetail[];
};

// --------------------------------------------------------------------------
// Shared attack-detail cache, keyed by primitive_id. Shared between the heatmap
// (hover prefetch) and the drawer (on open), so:
//   • hovering a cell warms the fetch — by the time it's clicked the detail is
//     usually already in hand and the drawer opens straight to content;
//   • re-opening any previously-viewed cell is instant;
//   • a transient 502/503/504 from a Render cold boot is retried (1.6s/2.4s)
//     instead of leaving the drawer stuck on "loading primitive..." forever.
// --------------------------------------------------------------------------
const detailCache = new Map<string, Promise<AttackDetailResponse>>();

async function fetchAttackDetailWithRetry(
  url: string,
): Promise<AttackDetailResponse> {
  for (let attempt = 0; ; attempt++) {
    try {
      // Per-attempt timeout: a Render cold boot can HOLD the socket instead of
      // returning a clean 502, which would otherwise hang the drawer on
      // "loading primitive…" indefinitely. Abort at 12s and let the loop retry.
      const r = await fetch(url, { signal: AbortSignal.timeout(12_000) });
      const gateway = r.status === 502 || r.status === 503 || r.status === 504;
      if (gateway && attempt < 2) {
        await new Promise((res) => setTimeout(res, 800 * (attempt + 1)));
        continue;
      }
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      return (await r.json()) as AttackDetailResponse;
    } catch (e) {
      if (attempt < 2) {
        await new Promise((res) => setTimeout(res, 800 * (attempt + 1)));
        continue;
      }
      throw e;
    }
  }
}

export function fetchAttackDetail(
  primitiveId: string,
): Promise<AttackDetailResponse> {
  const cached = detailCache.get(primitiveId);
  if (cached) return cached;
  const p = fetchAttackDetailWithRetry(`${API_BASE}/api/attacks/${primitiveId}`);
  // Evict on failure so a later hover/click can retry from scratch.
  p.catch(() => detailCache.delete(primitiveId));
  detailCache.set(primitiveId, p);
  return p;
}

/** Warm the cache for a cell the user is hovering (fire-and-forget). */
export function prefetchAttackDetail(primitiveId: string): void {
  void fetchAttackDetail(primitiveId).catch(() => {});
}

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
  date,
  scope,
  attacker,
  onClose,
}: {
  open: boolean;
  cell: BreachCell | null;
  /** Matrix run-date — threads into the "see all primitives" cell-page link. */
  date?: string;
  /** Matrix SCOPE toggle — threaded through so the cell page opens in the same
   *  scope you clicked from (an all-time cell that breached on another day would
   *  otherwise open to an empty day-scoped page). */
  scope?: "this-run" | "all-time";
  /** Matrix ATTACKER toggle — same idea on the other axis, so an augmented-only
   *  breach doesn't open to an empty baseline page. */
  attacker?: "baseline" | "augmented";
  onClose: () => void;
}) {
  // Track which primitive_id the current `detail` was fetched for. If the
  // cell changes, we render "loading" until the new fetch lands instead of
  // wiping `detail` synchronously inside the effect (which React 19 flags
  // as a cascading-render anti-pattern).
  const [detail, setDetail] = useState<AttackDetailResponse | null>(null);
  const [errorFor, setErrorFor] = useState<string | null>(null);
  const detailFor = detail?.primitive.primitive_id ?? null;
  const needsFetch = open && cell !== null && detailFor !== cell.primitive_id;

  useEffect(() => {
    if (!needsFetch || !cell) return;
    const id = cell.primitive_id;
    let cancelled = false;
    // Goes through the shared cache: a cell hovered before clicking is usually
    // already loaded, re-opens are instant, and cold-boot 502s are retried.
    fetchAttackDetail(id)
      .then((data) => {
        if (!cancelled) setDetail(data);
      })
      .catch(() => {
        if (!cancelled) setErrorFor(id);
      });
    return () => {
      cancelled = true;
    };
  }, [needsFetch, cell]);

  const shownDetail =
    detail && cell && detail.primitive.primitive_id === cell.primitive_id
      ? detail
      : null;
  // Show an error (not an infinite "loading…") if the fetch ultimately failed
  // for the cell currently on screen.
  const errored = cell !== null && errorFor === cell.primitive_id && !shownDetail;
  const loading = needsFetch && !errored;

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
        <div className="sticky top-0 bg-background/95 backdrop-blur-xl border-b border-border z-10 px-5 py-4 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-rogue-green">
              cell · {cell.family}
            </p>
            <p className="text-xs font-mono text-muted-foreground mt-0.5 truncate max-w-full sm:max-w-[400px]">
              <span className="inline-flex items-center gap-1.5">
                <ProviderLogo model={cell.target_model} className="text-xs opacity-80" />
                {cell.config_name} · {cell.target_model}
              </span>
            </p>
            {cell.refused && (
              <span
                className="mt-1 inline-flex items-center gap-1 rounded border border-rogue-red/30 bg-rogue-red/10 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-rogue-red"
                title="The primary judge (Claude Sonnet) refused to grade a trial in this cell, so it was graded by the secondary judge — flagged as lower-trust provenance."
              >
                judge refused → fallback
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 text-muted-foreground hover:text-rogue-red transition-colors text-2xl leading-none font-mono w-8 h-8 flex items-center justify-center"
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

          {/* See every breaching primitive in this (family × config) cell. */}
          <Link
            href={`/matrix/cell?family=${encodeURIComponent(cell.family)}&config=${encodeURIComponent(
              cell.deployment_config_id,
            )}${date ? `&date=${encodeURIComponent(date)}` : ""}${
              scope ? `&scope=${scope}` : ""
            }${attacker ? `&attacker=${attacker}` : ""}`}
            className="block rounded-md border border-rogue-green/30 bg-rogue-green/5 px-4 py-2.5 text-xs font-mono text-rogue-green hover:bg-rogue-green/10 transition-colors"
          >
            see all breaching primitives in this cell →
          </Link>

          {/* Primitive */}
          {loading && !shownDetail && (
            <p className="text-xs font-mono text-muted-foreground">
              {"// loading primitive..."}
            </p>
          )}
          {errored && (
            <p className="text-xs font-mono text-rogue-red">
              {"// couldn't load this primitive (the API may be waking up) — close and reopen to retry"}
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

              {shownDetail.primitive.has_image && (
                <PayloadImage primitiveId={shownDetail.primitive.primitive_id} />
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
                            className="text-rogue-green hover:underline truncate inline-block max-w-full sm:max-w-[380px] align-middle"
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

/**
 * Renders the primitive's real image — the §11.8 fetched carrier OR the
 * Feature-A verbatim-ingested payload image — from /api/attacks/{id}/image.
 * Hides itself entirely if the route 404s (the deployed API only has the bytes
 * when the harvest that cached them ran on its filesystem).
 */
export function PayloadImage({ primitiveId }: { primitiveId: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return (
    <section className="space-y-1.5">
      <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-rogue-green">
        payload image — sent verbatim to the vision panel
      </p>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={`${API_BASE}/api/attacks/${primitiveId}/image`}
        alt="attack payload / carrier image"
        onError={() => setFailed(true)}
        className="max-h-80 w-auto rounded-md border border-border/60 bg-card/40"
      />
    </section>
  );
}

export function VerdictBar({
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

export function CopyButton({ text }: { text: string }) {
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
