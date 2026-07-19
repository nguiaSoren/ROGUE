"use client";

/**
 * Safeguard / over-refusal board — the FIFTH leaderboard facet (a helpfulness-cost companion to the
 * breach-rate + long-context robustness boards). Where those measure "does the model comply with
 * harm?", this measures the opposite failure: "does the model wrongly REFUSE a benign look-alike?"
 * — the False Refusal Rate (FRR = benign prompts wrongly refused / benign prompts scored). Lower is
 * better.
 *
 * Bound to the `data/safeguard/board.json` contract (mirrored into `@/lib/leaderboard-data`). It
 * ships STATUS "pending": the metric, panel and benign denominators are wired + gated but NO approved
 * paid run has populated the board — so this renders an HONEST "measurement pending" state (never
 * fabricated zeros, per the marketing-honesty rule). The measured render path (ranked FRR + CI bars,
 * all-errored last, per-benign-set drill-down) is built and lights up the moment a run fills the
 * board.
 */

import { useState } from "react";
import { SAFEGUARD_BOARD, type SafeguardModelRow } from "@/lib/leaderboard-data";

type Tier = "green" | "orange" | "red";
// Lower FRR = better, so the tier scale reads the SAME direction as the breach/leak boards
// (low = green/good, high = red/bad).
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

function RankBadge({ rank }: { rank: number }) {
  const top = rank <= 3;
  return (
    <span
      className={
        "inline-flex h-7 w-7 items-center justify-center rounded-md font-mono text-sm font-bold tabular-nums " +
        (top
          ? "text-rogue-green border border-rogue-green/40 bg-rogue-green/10"
          : "text-muted-foreground border border-border/60 bg-background/40")
      }
    >
      {rank}
    </span>
  );
}

/** FRR bar with its Wilson-CI whisker overlaid (lower fill = more helpful). */
function FrrBar({ frr, ci }: { frr: number; ci: [number, number] }) {
  const tier = rateTier(frr);
  const fill = tierColor(tier);
  const pctFill = Math.max(frr * 100, frr > 0 ? 2 : 0);
  const ciLo = Math.max(ci[0] * 100, 0);
  const ciHi = Math.min(ci[1] * 100, 100);
  return (
    <div className="flex items-center gap-2.5">
      <div className="relative h-2.5 flex-1 rounded-full bg-background/70 border border-border/50 overflow-hidden">
        {/* Wilson 95% CI band */}
        <div
          className="absolute inset-y-0 rounded-full bg-foreground/10"
          style={{ left: `${ciLo}%`, width: `${Math.max(ciHi - ciLo, 0)}%` }}
        />
        <div
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ width: `${pctFill}%`, background: fill, boxShadow: `0 0 8px ${fill}` }}
        />
      </div>
      <span className="font-mono text-xs tabular-nums w-9 text-right" style={{ color: fill }}>
        {pct(frr)}
      </span>
    </div>
  );
}

/** One measured row (ranked). All-errored rows (frr === null) render greyed + unranked-last. */
function SafeguardRow({
  label,
  row,
  rank,
  index,
}: {
  label: string;
  row: SafeguardModelRow;
  rank: number | null;
  index: number;
}) {
  const [open, setOpen] = useState(false);
  const sets = Object.entries(row.by_set ?? {});
  const hasDetail = sets.length > 0 || row.sample != null;
  const style = { animationDelay: `${Math.min(index * 0.03, 0.4)}s` };
  const errored = row.frr == null;
  const panelId = `safeguard-detail-${index}`;
  return (
    <div className="border-b border-border/50 last:border-b-0 animate-rogue-fade-up" style={style}>
      <button
        type="button"
        onClick={() => hasDetail && setOpen((v) => !v)}
        aria-expanded={hasDetail ? open : undefined}
        aria-controls={hasDetail ? panelId : undefined}
        disabled={!hasDetail}
        className="w-full grid grid-cols-[1.75rem_minmax(0,1fr)_1rem] gap-3 items-start px-3 py-3 text-left transition-colors enabled:hover:bg-rogue-green/5 focus:outline-none focus-visible:bg-rogue-green/5 disabled:cursor-default"
      >
        <div className="flex items-center justify-center pt-0.5">
          {rank != null ? (
            <RankBadge rank={rank} />
          ) : (
            <span className="inline-flex h-7 w-7 items-center justify-center rounded-md font-mono text-xs text-muted-foreground border border-border/60 bg-background/40">
              —
            </span>
          )}
        </div>
        <div className="min-w-0 space-y-1.5">
          <div className="flex items-center gap-2 min-w-0">
            <p className="font-mono text-sm font-semibold truncate">{label}</p>
            {errored && (
              <span className="shrink-0 font-mono text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded text-rogue-orange bg-rogue-orange/10">
                all-errored
              </span>
            )}
          </div>
          {errored ? (
            <p className="font-mono text-[11px] text-muted-foreground">
              no scorable denominator — {row.n_errors}/{row.n_fired} prompts errored
            </p>
          ) : (
            <FrrBar frr={row.frr as number} ci={row.wilson_ci} />
          )}
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-[10px] text-muted-foreground">
            {!errored && (
              <>
                <span className="text-foreground/80">{pct(row.frr as number)} false-refusal</span>
                <span className="opacity-60">
                  Wilson {pct(row.wilson_ci[0])}–{pct(row.wilson_ci[1])}
                </span>
                <span className="opacity-60">
                  · boot {pct(row.bootstrap_ci[0])}–{pct(row.bootstrap_ci[1])}
                </span>
                <span className="opacity-60">· {row.n_refused}/{row.n} refused</span>
              </>
            )}
            <span className="opacity-60">· n={row.n}</span>
            {hasDetail && <span className="opacity-60">· {open ? "hide" : "show"} by benign set</span>}
          </div>
        </div>
        <div className="flex items-center justify-center pt-1.5">
          {hasDetail && (
            <svg
              width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"
              className={`text-muted-foreground transition-transform ${open ? "rotate-90" : ""}`}
            >
              <path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
        </div>
      </button>
      {open && hasDetail && (
        <div id={panelId} className="px-3 pb-4 pl-[3.25rem] space-y-3 animate-rogue-fade-up">
          {sets.length > 0 && (
            <div className="space-y-1">
              <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-rogue-green">
                false-refusal rate by benign set
              </p>
              <div className="rounded-md border border-border/40 bg-background/30 px-3 py-2 space-y-1">
                {sets.map(([setName, s]) => {
                  const r = typeof s.frr === "number" ? s.frr : 0;
                  const tier = rateTier(r);
                  return (
                    <div key={setName} className="grid grid-cols-[8rem_minmax(0,1fr)_3rem] items-center gap-2 py-0.5">
                      <span className="font-mono text-[10px] text-muted-foreground truncate">{setName}</span>
                      <div className="relative h-1.5 rounded-full bg-background/70 border border-border/40 overflow-hidden">
                        <div
                          className="absolute inset-y-0 left-0 rounded-full"
                          style={{ width: `${Math.max(r * 100, r > 0 ? 3 : 0)}%`, background: tierColor(tier) }}
                        />
                      </div>
                      <span className="font-mono text-[10px] tabular-nums text-right" style={{ color: tierColor(tier) }}>
                        {typeof s.frr === "number" ? pct(s.frr) : "—"}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          {row.sample && (row.sample.prompt || row.sample.response) && (
            <div className="space-y-1.5">
              <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-rogue-orange">
                a wrongly-refused benign prompt
                {row.sample.benign_set && (
                  <span className="ml-2 px-1.5 py-0.5 rounded text-muted-foreground bg-foreground/5">{row.sample.benign_set}</span>
                )}
              </p>
              {row.sample.prompt && (
                <div className="rounded-md border border-border/40 bg-background/30 px-3 py-2 space-y-1">
                  <p className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground">benign prompt</p>
                  <p className="font-mono text-[10px] leading-relaxed text-foreground/70">{row.sample.prompt}</p>
                </div>
              )}
              {row.sample.response && (
                <div className="rounded-md border border-rogue-orange/20 bg-rogue-orange/[0.03] px-3 py-2 space-y-1">
                  <p className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground">model refusal</p>
                  <p className="font-mono text-[10px] leading-relaxed text-foreground/70">{row.sample.response}</p>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Honest empty state — the metric is wired + gated, but no paid run has populated it. Never zeros. */
function PendingState() {
  const b = SAFEGUARD_BOARD;
  return (
    <div className="rogue-card border border-rogue-green/30 rounded-lg overflow-hidden bg-card/40">
      <div className="grid gap-6 p-5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
        <div className="space-y-3">
          <span className="inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-orange">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-rogue-orange animate-rogue-pulse-green" />
            measurement pending
          </span>
          <p className="text-sm text-muted-foreground leading-relaxed max-w-lg">
            No approved paid run has populated this board yet. The metric, panel and benign denominators
            are <span className="text-foreground">wired and gated</span> — the board lights up the moment a
            run lands, with no fabricated numbers shown in the meantime.
          </p>
          <div className="rounded-md border border-border/50 bg-background/30 px-3 py-2 font-mono text-[11px] text-foreground/80">
            FRR = (benign prompts wrongly refused) / (benign prompts scored)
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 font-mono text-[10px] text-muted-foreground">
            <span className="uppercase tracking-wider opacity-70">benign sets wired:</span>
            {b.benign_sets.map((s) => (
              <span key={s} className="inline-flex items-center gap-1 text-foreground/80">
                <span className="text-rogue-green">·</span> {s}
              </span>
            ))}
          </div>
          <p className="font-mono text-[10px] text-muted-foreground">
            detector: over-block judge (pending) · Wilson + bootstrap CI
          </p>
        </div>
        {/* The pending share card (itself an honest "MEASUREMENT PENDING" artifact). */}
        <a
          href="/cards/safeguard-leaderboard.png"
          target="_blank"
          rel="noopener noreferrer"
          className="block shrink-0 overflow-hidden rounded-md border border-border/60 bg-background/40 transition-colors hover:border-rogue-green/50"
          title="Open the safeguard board card"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/cards/safeguard-leaderboard.svg"
            alt="ROGUE safeguard / over-refusal board — measurement pending"
            width={320}
            height={180}
            loading="lazy"
            className="h-auto w-full max-w-[320px]"
          />
        </a>
      </div>
    </div>
  );
}

export default function SafeguardBoard() {
  const b = SAFEGUARD_BOARD;
  const entries = Object.entries(b.board);
  const measured = b.status === "measured" && entries.length > 0;

  // Rank: lowest FRR = most helpful = best. all-errored (frr === null) sink to the bottom, unranked.
  const ranked = entries.slice().sort((a, b2) => {
    const fa = a[1].frr;
    const fb = b2[1].frr;
    if (fa == null && fb == null) return 0;
    if (fa == null) return 1;
    if (fb == null) return -1;
    return fa - fb;
  });
  let rankCounter = 0;

  return (
    <section id="safeguard-board" className="space-y-4 animate-rogue-fade-up scroll-mt-24">
      <header className="space-y-1.5">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
          safeguard · over-refusal (FRR) · {measured ? `measured ${b.measured_at ?? ""}` : "measurement pending"}
        </p>
        <h2 className="text-xl sm:text-2xl font-bold tracking-tight">Safeguard board</h2>
        <p className="text-xs text-muted-foreground leading-relaxed max-w-3xl">
          The <span className="text-foreground">helpfulness cost</span> companion to the breach boards: rather
          than &ldquo;does the model comply with harm?&rdquo;, it measures how often a model{" "}
          <span className="text-rogue-orange">wrongly refuses a benign look-alike</span> — the false-refusal
          rate on safe prompts that merely resemble unsafe ones. <span className="text-foreground">Lower is
          better.</span> A separate metric — not comparable to the breach boards above.
          {measured && b.detector ? <> Detector: {b.detector}.</> : null}
        </p>
      </header>

      {measured ? (
        <div className="rogue-card border border-rogue-green/30 rounded-lg overflow-hidden bg-card/40">
          {ranked.map(([label, row], i) => {
            const rank = row.frr == null ? null : ++rankCounter;
            return <SafeguardRow key={label} label={label} row={row} rank={rank} index={i} />;
          })}
        </div>
      ) : (
        <PendingState />
      )}

      <p className="text-[10px] text-muted-foreground font-mono">
        {measured
          ? `// FRR = benign wrongly-refused / benign scored, over ${b.benign_sets.join(" + ")}; Wilson + bootstrap 95% CI. Ranked independently (lower = more helpful).`
          : `// source data/safeguard/board.json (${b.benign_sets.join(", ")}) — pending an approved paid run; ${b.note ?? ""}`}
      </p>
    </section>
  );
}
