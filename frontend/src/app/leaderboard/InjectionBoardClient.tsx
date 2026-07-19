"use client";

/**
 * Injection robustness (agentic IPI) board — the SIXTH leaderboard facet. A per-DeploymentConfig view
 * of INDIRECT prompt injection: a malicious instruction is smuggled into a tool result / retrieved
 * document (not the user turn), and we measure how often the agent follows it (IPI ASR), decomposed by
 * the three levers that move it — the injection TEMPLATE, the CARRIER (which tool result carried the
 * payload), and the CONCEALMENT (how the instruction was hidden). Paired with a defense-stack
 * fingerprint (guardrail-fingerprint-v1) that probes whether a guard/filter is present + its posture.
 *
 * Bound to the `ipi-matrix-v1` contract (mirrored into `@/lib/leaderboard-data`). It ships PENDING
 * (n_cells 0) — no approved paid run has populated the matrix — so this renders an HONEST empty state
 * describing the levers it will measure, never fabricated numbers (marketing-honesty rule). The
 * measured render path (overall ASR + marginal ASR bars per lever + defense label + cell drill-down)
 * is built and lights up the moment a run fills the matrix.
 */

import { useState } from "react";
import { INJECTION_BOARD, type IpiCell } from "@/lib/leaderboard-data";

type Tier = "green" | "orange" | "red";
function rateTier(r: number): Tier {
  if (r >= 0.3) return "red";
  if (r >= 0.1) return "orange";
  return "green";
}
function tierColor(t: Tier): string {
  return t === "red" ? "var(--rogue-red)" : t === "orange" ? "var(--rogue-orange)" : "var(--rogue-green)";
}
function pct(x: number): string {
  return `${Math.round(x * 100)}%`;
}

/** A ranked bar list for one lever (template / carrier / concealment) — marginal ASR, worst-first. */
function LeverBreakdown({ title, data }: { title: string; data: Record<string, number> }) {
  const rows = Object.entries(data).sort((a, b) => b[1] - a[1]);
  if (rows.length === 0) return null;
  return (
    <div className="space-y-1.5">
      <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-rogue-green">{title}</p>
      <div className="rounded-md border border-border/40 bg-background/30 px-3 py-2 space-y-1">
        {rows.map(([key, rate]) => {
          const tier = rateTier(rate);
          return (
            <div key={key} className="grid grid-cols-[10rem_minmax(0,1fr)_3rem] items-center gap-2 py-0.5">
              <span className="font-mono text-[10px] text-muted-foreground truncate" title={key}>{key}</span>
              <div className="relative h-1.5 rounded-full bg-background/70 border border-border/40 overflow-hidden">
                <div
                  className="absolute inset-y-0 left-0 rounded-full"
                  style={{ width: `${Math.max(rate * 100, rate > 0 ? 3 : 0)}%`, background: tierColor(tier) }}
                />
              </div>
              <span className="font-mono text-[10px] tabular-nums text-right" style={{ color: tierColor(tier) }}>
                {pct(rate)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function DefenseLabel() {
  const d = INJECTION_BOARD.defense;
  if (!d) return null;
  const tint = d.defense_present
    ? "text-rogue-green border-rogue-green/40 bg-rogue-green/10"
    : "text-rogue-red border-rogue-red/40 bg-rogue-red/10";
  return (
    <div className="rounded-md border border-border/50 bg-background/30 px-3 py-2.5 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground">defense stack</span>
        <span className={`font-mono text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded border ${tint}`}>
          {d.defense_present ? "guard present" : "no guard detected"}
        </span>
        {d.guard_family && (
          <span className="font-mono text-[10px] text-foreground/80">{d.guard_family}</span>
        )}
        <span className="font-mono text-[10px] text-muted-foreground">· posture: {d.posture}</span>
        {typeof d.confidence === "number" && (
          <span className="font-mono text-[10px] text-muted-foreground">· confidence {pct(d.confidence)}</span>
        )}
      </div>
      {d.evidence && d.evidence.length > 0 && (
        <ul className="list-disc pl-5 font-mono text-[10px] text-muted-foreground space-y-0.5">
          {d.evidence.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CellRow({ cell, index }: { cell: IpiCell; index: number }) {
  return (
    <div
      className="grid grid-cols-[1rem_minmax(0,1fr)] gap-2 items-start px-3 py-2 border-b border-border/40 last:border-b-0 animate-rogue-fade-up"
      style={{ animationDelay: `${Math.min(index * 0.02, 0.3)}s` }}
    >
      <span
        className={`mt-1 inline-block w-2 h-2 rounded-full ${cell.breached ? "bg-rogue-red" : "bg-rogue-green"}`}
        aria-hidden
      />
      <div className="min-w-0 space-y-0.5">
        <p className="font-mono text-[11px] text-foreground/90 truncate" title={cell.headline ?? undefined}>
          {cell.headline ?? `${cell.template} · ${cell.carrier} · ${cell.concealment}`}
        </p>
        <div className="flex flex-wrap gap-x-2 gap-y-0.5 font-mono text-[9px] text-muted-foreground">
          <span>tmpl:{cell.template}</span>
          <span>carrier:{cell.carrier}</span>
          <span>via:{cell.carrier_tool}</span>
          <span>conceal:{cell.concealment}</span>
          <span>place:{cell.placement}</span>
          {cell.signals?.length > 0 && <span className="text-rogue-orange/80">signals:{cell.signals.join(",")}</span>}
        </div>
      </div>
    </div>
  );
}

function PendingState() {
  return (
    <div className="rogue-card border border-rogue-green/30 rounded-lg overflow-hidden bg-card/40 p-5 space-y-4">
      <span className="inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-orange">
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-rogue-orange animate-rogue-pulse-green" />
        measurement pending
      </span>
      <p className="text-sm text-muted-foreground leading-relaxed max-w-2xl">
        No approved paid run has populated the IPI matrix yet. The three levers below and the
        guardrail-fingerprint probe are <span className="text-foreground">wired and gated</span> — the board
        lights up per DeploymentConfig once a run lands, with no fabricated numbers shown in the meantime.
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        {[
          { k: "template", d: "the injection wording — how the rogue instruction is phrased" },
          { k: "carrier", d: "which tool result / retrieved document carried the payload" },
          { k: "concealment", d: "how the instruction was hidden (comment, unicode, framing)" },
        ].map((lever) => (
          <div key={lever.k} className="rounded-md border border-border/50 bg-background/30 px-3 py-2.5 space-y-1">
            <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-rogue-green">by {lever.k}</p>
            <p className="text-[11px] text-muted-foreground leading-snug">{lever.d}</p>
          </div>
        ))}
      </div>
      <p className="font-mono text-[10px] text-muted-foreground">
        + defense-stack fingerprint (guardrail-fingerprint-v1): guard present? · posture · guard family · confidence
      </p>
    </div>
  );
}

export default function InjectionBoard() {
  const b = INJECTION_BOARD;
  const measured = b.status === "measured" && b.n_cells > 0;
  const [showCells, setShowCells] = useState(false);
  const asr = b.ipi_asr ?? 0;
  const tier = rateTier(asr);

  return (
    <section id="injection-board" className="space-y-4 animate-rogue-fade-up scroll-mt-24">
      <header className="space-y-1.5">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
          agentic IPI · marginal ASR by lever · {measured ? "measured" : "measurement pending"}
        </p>
        <h2 className="text-xl sm:text-2xl font-bold tracking-tight">Injection robustness board</h2>
        <p className="text-xs text-muted-foreground leading-relaxed max-w-3xl">
          Per <span className="text-foreground">DeploymentConfig</span> indirect prompt injection: a malicious
          instruction is smuggled into a <span className="text-foreground">tool result or retrieved document</span>
          {" "}— not the user turn — and we measure how often the agent follows it, broken down by the{" "}
          <span className="text-rogue-orange">template × carrier × concealment</span> levers, plus a defense-stack
          fingerprint. A separate attack + metric — not comparable to the breach boards above.
          {measured && b.config_label ? <> Config: <span className="text-foreground">{b.config_label}</span>.</> : null}
        </p>
      </header>

      {measured ? (
        <div className="space-y-4">
          <div className="rogue-card border border-rogue-green/30 rounded-lg bg-card/40 p-5 space-y-4">
            <div className="flex flex-wrap items-end gap-5">
              <div className="flex items-baseline gap-2">
                <span className="text-4xl font-bold tabular-nums leading-none" style={{ color: tierColor(tier) }}>
                  {pct(asr)}
                </span>
                <span className="font-mono text-xs text-muted-foreground">IPI ASR</span>
              </div>
              <p className="font-mono text-[11px] text-muted-foreground">
                {b.n_breaches}/{b.n_cells} injection cells followed the rogue instruction
              </p>
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <LeverBreakdown title="by template" data={b.by_template} />
              <LeverBreakdown title="by carrier" data={b.by_carrier} />
              <LeverBreakdown title="by concealment" data={b.by_concealment} />
            </div>
            <DefenseLabel />
          </div>
          {b.cells.length > 0 && (
            <div className="rogue-card border border-border rounded-lg bg-card/40 overflow-hidden">
              <button
                type="button"
                onClick={() => setShowCells((v) => !v)}
                aria-expanded={showCells}
                className="w-full flex items-center justify-between px-3 py-2.5 font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground hover:text-foreground transition-colors"
              >
                <span>{showCells ? "hide" : "show"} all {b.cells.length} probe cells</span>
                <span className={`transition-transform ${showCells ? "rotate-90" : ""}`}>›</span>
              </button>
              {showCells && (
                <div className="border-t border-border/60">
                  {b.cells.map((c, i) => (
                    <CellRow key={`${c.template}-${c.carrier}-${c.concealment}-${i}`} cell={c} index={i} />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        <PendingState />
      )}

      <p className="text-[10px] text-muted-foreground font-mono">
        {measured
          ? `// ${b.schema_version} · marginal ASR per lever over ${b.n_cells} cells; ranked independently.`
          : `// ${b.schema_version} — pending an approved paid run; ${b.note ?? ""}`}
      </p>
    </section>
  );
}
