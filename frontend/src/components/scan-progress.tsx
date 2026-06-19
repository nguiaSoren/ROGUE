"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { isTerminal, type ScanRecord } from "@/lib/platform-api";
import { StatusBadge, ScoreBadge } from "@/components/score-badge";

/**
 * Live scan-progress card (docs/platform/dashboard/live-scan-ux.md).
 *
 * Renders the spec's progress line:
 *
 *     ████████ 67%   32/50 tests complete   Current attack: Crescendo
 *
 * Transport is Option A, poll the same-origin `GET /api/scans/{id}` proxy every
 * ~2s while non-terminal (live-scan-ux.md §2). This is a client component, so it
 * MUST NOT read the session or hold the bearer; the proxy route re-reads the
 * httpOnly cookie server-side and forwards the key. The "one connection, many
 * consumers" discipline (frontend/src/components/sse-feed-provider.tsx) is honored:
 * this component owns EXACTLY ONE poll loop for the page; every sub-readout (bar,
 * counter, cost, badge) reads the single `record` state, never its own fetcher.
 * Option B (the SSE `/v1/scans/{id}/events` stream) slots in behind this same seam
 * later.
 */

const POLL_INTERVAL_MS = 2_000;

export function ScanProgress({ initial }: { initial: ScanRecord }) {
  const [record, setRecord] = useState<ScanRecord>(initial);
  const [error, setError] = useState<string | null>(null);

  const scanId = initial.scan_id;
  // Whether to poll at all is decided once from the server-seeded record; after
  // mount the live `record` is the source of truth and the loop reads each fetched
  // status to decide whether to reschedule.
  const startedTerminal = isTerminal(initial.status);

  // The effect's identity is the scan, not its status (single-effect, single
  // connection, mirrors the SSE provider's [] / [scanId]-deps discipline).
  useEffect(() => {
    if (startedTerminal) return; // already done, never poll

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const tick = async () => {
      try {
        const r = await fetch(`/api/scans/${encodeURIComponent(scanId)}`, {
          cache: "no-store",
        });
        if (cancelled) return;
        if (!r.ok) throw new Error(`scan poll → ${r.status}`);
        const next = (await r.json()) as ScanRecord;
        if (cancelled) return;
        setRecord(next);
        setError(null);
        if (isTerminal(next.status)) return; // stop on terminal, no reschedule
      } catch (e) {
        if (cancelled) return;
        // Cold start / transient gateway blip: keep showing progress, don't paint
        // the scan as broken (live-scan-ux.md §7). The loop simply continues.
        setError(e instanceof Error ? e.message : "connection blip, retrying");
      }
      if (!cancelled) timer = setTimeout(tick, POLL_INTERVAL_MS);
    };

    timer = setTimeout(tick, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [scanId, startedTerminal]);

  const onCancel = useCallback(async () => {
    if (typeof window !== "undefined") {
      const ok = window.confirm(
        "Stop this scan? Tests already run still count toward the report.",
      );
      if (!ok) return;
    }
    try {
      // POST the same-origin cancel proxy (bearer attached server-side); it returns
      // the updated ScanRecord. The poll loop reconciles any drift afterward.
      const r = await fetch(`/api/scans/${encodeURIComponent(scanId)}/cancel`, {
        method: "POST",
        cache: "no-store",
      });
      if (!r.ok) throw new Error(`cancel → ${r.status}`);
      const next = (await r.json()) as ScanRecord;
      setRecord(next);
    } catch {
      /* swallow, the poll loop will reconcile */
    }
  }, [scanId]);

  const { status } = record;
  const terminal = isTerminal(status);
  const showCounter = status === "running" || status === "completed";
  const etaMinutes =
    status === "running" && record.progress > 0
      ? estimateEtaMinutes(record)
      : null;

  return (
    <section className="rogue-card rounded-lg border border-border p-6 space-y-5">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <StatusBadge status={status} />
          {record.score !== null && record.score !== undefined && (
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground font-mono">
              risk <ScoreBadge score={record.score} />
            </span>
          )}
        </div>
        {!terminal && (
          <button
            type="button"
            onClick={onCancel}
            className="font-mono text-xs uppercase tracking-[0.15em] text-rogue-red border border-rogue-red/40 rounded-md px-3 py-1 hover:bg-rogue-red/10 transition-colors"
          >
            Cancel scan
          </button>
        )}
      </div>

      {/* Progress bar, indeterminate-ish while queued, determinate once running. */}
      <div className="space-y-2">
        <div className="h-3 w-full overflow-hidden rounded-full bg-card/40 border border-border">
          <div
            className={`h-full rounded-full transition-[width] duration-500 ${
              status === "failed"
                ? "bg-rogue-red"
                : "bg-rogue-green"
            }`}
            style={{
              width: `${status === "completed" ? 100 : Math.max(0, Math.min(100, record.progress))}%`,
            }}
          />
        </div>
        <div className="flex items-center justify-between gap-4 flex-wrap font-mono text-xs text-muted-foreground tabular-nums">
          <span className="text-foreground font-bold">
            {status === "queued" ? ", " : `${Math.round(record.progress)}%`}
          </span>
          {showCounter && (
            <span>
              {record.n_completed}/{record.n_tests} tests complete
            </span>
          )}
          {record.top_attack && (
            <span>
              Current attack:{" "}
              <span className="text-foreground">{record.top_attack}</span>
            </span>
          )}
        </div>
      </div>

      {/* Running readouts: breaches, cost, ETA. */}
      <div className="flex items-center gap-6 flex-wrap font-mono text-xs">
        <span
          className={record.n_breaches > 0 ? "text-rogue-red" : "text-rogue-green"}
        >
          {record.n_breaches} breaches so far
        </span>
        <span className="text-muted-foreground">
          ~{formatUsd(record.cost_usd)} spent
          <span className="opacity-60"> (estimate)</span>
        </span>
        {etaMinutes !== null && (
          <span className="text-muted-foreground">~{etaMinutes} min remaining</span>
        )}
      </div>

      {/* Terminal framing. */}
      {status === "queued" && (
        <p className="text-xs text-muted-foreground">Queued, waiting for a worker.</p>
      )}
      {status === "failed" && record.error && (
        <p className="rounded-md border border-rogue-red/40 bg-rogue-red/10 p-3 text-xs text-rogue-red font-mono">
          {record.error}
        </p>
      )}
      {status === "canceled" && (
        <p className="text-xs text-muted-foreground">
          Scan canceled, partial progress above is real and counts toward any report.
        </p>
      )}
      {status === "completed" && (
        <Link
          href={`/scans/${encodeURIComponent(scanId)}/report`}
          className="inline-flex items-center gap-2 font-mono text-xs uppercase tracking-[0.15em] text-rogue-green border border-rogue-green/40 rounded-md px-3 py-1.5 hover:bg-rogue-green/10 transition-colors"
        >
          View report →
        </Link>
      )}

      {error && !terminal && (
        <p className="text-[10px] text-muted-foreground/70 font-mono">
          {/* transient, the loop keeps retrying */}
          {error}
        </p>
      )}
    </section>
  );
}

/** Linear ETA projection: elapsed × (100 − progress) / progress (live-scan-ux.md §4). */
function estimateEtaMinutes(record: ScanRecord): number | null {
  if (!record.started_at || record.progress <= 0) return null;
  const startedMs = Date.parse(record.started_at);
  if (!Number.isFinite(startedMs)) return null;
  const elapsedMs = Date.now() - startedMs;
  if (elapsedMs <= 0) return null;
  const remainingMs = (elapsedMs * (100 - record.progress)) / record.progress;
  return Math.max(1, Math.round(remainingMs / 60_000));
}

/** Mirrors `_fmt_usd` (src/rogue/report.py:37): 2 decimals at/above a cent, 4 below. */
function formatUsd(x: number): string {
  if (x >= 0.01) return `$${x.toFixed(2)}`;
  if (x > 0) return `$${x.toFixed(4)}`;
  return "$0.00";
}
