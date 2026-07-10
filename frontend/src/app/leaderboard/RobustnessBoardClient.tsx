"use client";

/**
 * Long-context robustness board — CLIENT component (the parent /leaderboard page is a server
 * component with a Metadata export, so the expandable drill-down lives here).
 *
 * Each row is clickable: it expands to the per-token-level ladder (ASR at 2K→128K) AND a REAL
 * captured attack at the breaking level (payload + response excerpt) — the robustness equivalent of
 * the breach board's /matrix/cell drill-down ("click a cell to see the attacks in detail"). All data
 * is the real sweep (`data/robustness/leaderboard_qwen3_judged.json` + `responses.jsonl`), baked into
 * `@/lib/leaderboard-data` so the static page and the CLI cite identical numbers.
 */

import { useState } from "react";
import {
  LEADERBOARD_ROBUSTNESS_MODELS,
  LEADERBOARD_ROBUSTNESS_MEASURED,
  LEADERBOARD_ROBUSTNESS_METHOD,
  type RobustnessLevel,
  type RobustnessModel,
} from "@/lib/leaderboard-data";

type Tier = "green" | "orange" | "red";
function rateTier(r: number): Tier {
  if (r >= 0.3) return "red";
  if (r >= 0.1) return "orange";
  return "green";
}
function tierColor(t: Tier): string {
  return t === "red" ? "var(--rogue-red)" : t === "orange" ? "var(--rogue-orange)" : "var(--rogue-green)";
}
function fmtTokens(n: number | null): string {
  if (n == null) return "held";
  return n >= 1000 ? `${Math.round(n / 1000)}K` : String(n);
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

function Bar({ rate, tier }: { rate: number; tier: Tier }) {
  const pct = Math.max(rate * 100, rate > 0 ? 2 : 0);
  const fill = tierColor(tier);
  return (
    <div className="flex items-center gap-2.5">
      <div className="relative h-2.5 flex-1 rounded-full bg-background/70 border border-border/50 overflow-hidden">
        <div
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ width: `${pct}%`, background: fill, boxShadow: `0 0 8px ${fill}` }}
        />
      </div>
      <span className="font-mono text-xs tabular-nums w-9 text-right" style={{ color: fill }}>
        {Math.round(rate * 100)}%
      </span>
    </div>
  );
}

/** One rung of the ladder: token level + ASR bar + breach/n count. */
function LadderRow({ lvl }: { lvl: RobustnessLevel }) {
  const asr = lvl.n > 0 ? lvl.breach / lvl.n : 0;
  const tier = rateTier(asr);
  return (
    <div className="grid grid-cols-[3.5rem_minmax(0,1fr)_3rem] items-center gap-2 py-0.5">
      <span className="font-mono text-[10px] text-muted-foreground tabular-nums">~{fmtTokens(lvl.tokens)}</span>
      <div className="relative h-1.5 rounded-full bg-background/70 border border-border/40 overflow-hidden">
        <div
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ width: `${Math.max(asr * 100, asr > 0 ? 3 : 0)}%`, background: tierColor(tier) }}
        />
      </div>
      <span className="font-mono text-[10px] tabular-nums text-right" style={{ color: tierColor(tier) }}>
        {lvl.breach}/{lvl.n}
      </span>
    </div>
  );
}

function RobustnessRow({ row, rank, index }: { row: RobustnessModel; rank: number; index: number }) {
  const [open, setOpen] = useState(false);
  const tier = rateTier(row.breach_rate);
  const style = { animationDelay: `${Math.min(index * 0.03, 0.4)}s` };
  const robust = row.first_break_tokens != null && row.first_break_tokens >= 64000;
  const panelId = `robustness-detail-${rank}`;
  return (
    <div className="border-b border-border/50 last:border-b-0 animate-rogue-fade-up" style={style}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        className="w-full grid grid-cols-[1.75rem_minmax(0,1fr)_1rem] gap-3 items-start px-3 py-3 text-left transition-colors hover:bg-rogue-green/5 focus:outline-none focus-visible:bg-rogue-green/5"
      >
        <div className="flex items-center justify-center pt-0.5">
          <RankBadge rank={rank} />
        </div>
        <div className="min-w-0 space-y-1.5">
          <div className="flex items-center gap-2 min-w-0">
            <p className="font-mono text-sm font-semibold truncate">{row.model_label}</p>
            <span
              className={`shrink-0 font-mono text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded ${
                robust ? "text-rogue-green bg-rogue-green/10" : "text-rogue-red bg-rogue-red/10"
              }`}
            >
              breaks {fmtTokens(row.first_break_tokens)}
            </span>
          </div>
          <Bar rate={row.breach_rate} tier={tier} />
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-[10px] text-muted-foreground">
            <span className="text-foreground/80">{(row.breach_rate * 100).toFixed(1)}% breach @long-ctx</span>
            <span className="opacity-60">· n={row.n}</span>
            <span className="opacity-60">· {open ? "hide" : "show"} attacks by token level</span>
          </div>
        </div>
        <div className="flex items-center justify-center pt-1.5">
          <svg
            width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"
            className={`text-muted-foreground transition-transform ${open ? "rotate-90" : ""}`}
          >
            <path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
      </button>
      {open && (
        <div id={panelId} className="px-3 pb-4 pl-[3.25rem] space-y-3 animate-rogue-fade-up">
          <div className="space-y-1">
            <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-rogue-green">
              breach rate by context length
            </p>
            <div className="rounded-md border border-border/40 bg-background/30 px-3 py-2">
              {row.by_level.map((lvl) => (
                <LadderRow key={lvl.tokens} lvl={lvl} />
              ))}
            </div>
            <p className="font-mono text-[9px] text-muted-foreground">
              breaches / trials at each token rung — the ladder behind &ldquo;breaks at {fmtTokens(row.first_break_tokens)}&rdquo;.
            </p>
          </div>
          {row.sample && (
            <div className="space-y-1.5">
              <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-rogue-green">
                a real attack at ~{fmtTokens(row.sample.tokens)} tokens
                <span
                  className={`ml-2 px-1.5 py-0.5 rounded ${
                    row.sample.broke ? "text-rogue-red bg-rogue-red/10" : "text-rogue-green bg-rogue-green/10"
                  }`}
                >
                  {row.sample.broke ? "breached" : "held"}
                </span>
              </p>
              <div className="rounded-md border border-rogue-red/20 bg-rogue-red/[0.03] px-3 py-2 space-y-1">
                <p className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground">attack payload (tail)</p>
                <p className="font-mono text-[10px] leading-relaxed text-foreground/70 break-all">{row.sample.attack_excerpt}</p>
              </div>
              <div className="rounded-md border border-border/40 bg-background/30 px-3 py-2 space-y-1">
                <p className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground">model response</p>
                <p className="font-mono text-[10px] leading-relaxed text-foreground/70">{row.sample.response_excerpt}</p>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function RobustnessBoard() {
  const rows = [...LEADERBOARD_ROBUSTNESS_MODELS].sort((a, b) => a.breach_rate - b.breach_rate);
  if (rows.length === 0) return null;
  return (
    <section id="robustness-board" className="space-y-4 animate-rogue-fade-up scroll-mt-24">
      <header className="space-y-1.5">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
          long-context robustness · breaks at N tokens · measured {LEADERBOARD_ROBUSTNESS_MEASURED}
        </p>
        <h2 className="text-xl sm:text-2xl font-bold tracking-tight">Long-context robustness board</h2>
        <p className="text-xs text-muted-foreground leading-relaxed max-w-3xl">
          Many-shot / long-context attacks flood the context until a model caves. Each model is swept over a{" "}
          <span className="text-foreground">token ladder (2K→128K)</span> to find the{" "}
          <span className="text-rogue-green">threshold where it breaks</span> — the metric nobody else
          publishes. Ranked by long-context breach rate (lower = more robust). A{" "}
          <span className="text-foreground">separate attack + metric</span> — not comparable to the breach
          boards above. <span className="text-foreground/80">Click a model to see the attacks by token level.</span>
        </p>
      </header>
      <div className="rogue-card border border-rogue-green/30 rounded-lg overflow-hidden bg-card/40">
        {rows.map((row, i) => (
          <RobustnessRow key={row.model_label} row={row} rank={i + 1} index={i} />
        ))}
      </div>
      <p className="text-[10px] text-muted-foreground font-mono">
        {`// ${LEADERBOARD_ROBUSTNESS_METHOD} — measured ${LEADERBOARD_ROBUSTNESS_MEASURED}. Directional (small per-model n); a first robustness-threshold facet, ranked independently.`}
      </p>
    </section>
  );
}
