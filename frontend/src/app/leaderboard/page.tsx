import type { Metadata } from "next";
import type { ReactNode } from "react";
import Link from "next/link";
import MODEL_CARDS from "@/data/model-cards.json";
import {
  LEADERBOARD_MODELS,
  LEADERBOARD_TOTAL_TRIALS,
  LEADERBOARD_OSS_MODELS,
  LEADERBOARD_OSS_MEASURED,
  LEADERBOARD_OSS_METHOD,
} from "@/lib/leaderboard-data";

/**
 * /leaderboard, the public model-resistance board (VIRAL_LAUNCH_SPEC Decision #4).
 *
 * Ranks every model ROGUE tests by resistance — lower mean any-breach rate ranks
 * HIGHER. It renders from the bundled ALL-TIME snapshot (`@/lib/leaderboard-data`,
 * a mirror of src/rogue/data/demo_stats.json: 11,973 calibrated-judge trials),
 * NOT the live thin current-run matrix — so the board shows the robust standings
 * AND cites numbers IDENTICAL to the `rogue try` CLI overlay (same source).
 *
 * The closed (production) and open-source boards sit SIDE-BY-SIDE on desktop and
 * stack on mobile, but are NEVER one merged ranking: production runs the deep
 * escalation+PAIR pipeline (~2,000 trials/model, calibrated v3 judge); open-source
 * runs the lighter single-shot jailbreak pack (~40 trials/model). They are not
 * directly comparable, so each panel carries its own methodology and ranks within
 * itself.
 *
 * Displayed numbers come from the static snapshot. The ONLY live call is a
 * best-effort `target_model → deployment_config_id` lookup so the production
 * "worst family" cell can deep-link into the (redacted) /matrix/cell drill-down;
 * if the API is unreachable at build/revalidate, that link degrades to plain text
 * and the board still renders. 1-day revalidate — config ids rarely change.
 *
 * "Submit your model" is present but DISABLED (coming soon); the intake route
 * `/api/leaderboard/submit` is gated inert behind ROGUE_LEADERBOARD_SUBMISSIONS.
 */
export const revalidate = 86400;

export const metadata: Metadata = {
  title: "Leaderboard, ROGUE — models ranked by jailbreak resistance",
  description:
    "Every model ROGUE red-teams, ranked by resistance — a periodic measured snapshot (as of 2026-06-07), not a live-updating feed. Lower breach rate = higher rank, measured against ROGUE's open-web attack corpus and scored by a calibrated judge ([withheld — under anonymized review]). Reproducible and signed.",
  openGraph: {
    title: "ROGUE Leaderboard — models ranked by jailbreak resistance",
    description:
      "Lower breach rate = higher rank. Models ranked against ROGUE's open-web attack corpus, scored by a calibrated judge.",
    url: "/leaderboard",
    siteName: "ROGUE",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "ROGUE Leaderboard — models ranked by jailbreak resistance",
    description: "Lower breach rate = higher rank. Scored by a calibrated judge against ROGUE's open-web attack corpus.",
  },
};

// --------------------------------------------------------------------------

/** One ranked row, derived from all (family × config) cells for a single model. */
type ModelRow = {
  config_id: string;
  model_label: string;
  config_name: string;
  /** Provider-prefixed model id (e.g. anthropic/claude-opus-4-8) — the join key to the live config id. */
  target_model: string;
  /** Mean any-breach rate across the model's family cells — the ranking key. */
  mean_breach_rate: number;
  /** Highest single-cell any-breach rate (the model's worst case). */
  worst_breach_rate: number;
  /** The family behind the worst case. */
  worst_family: string | null;
  /** Total trials summed across the model's cells. */
  n_trials: number;
  /** Families that breached this model at all (rate > 0). */
  n_breached_families: number;
};

/** Roll the bundled all-time snapshot up to one ranked row per model. */
function buildRows(): ModelRow[] {
  const rows: ModelRow[] = LEADERBOARD_MODELS.map((m) => ({
    config_id: m.target_model,
    model_label: m.model_label,
    config_name: m.target_model,
    target_model: m.target_model,
    mean_breach_rate: m.mean_breach_rate,
    worst_breach_rate: m.worst_breach_rate,
    worst_family: m.worst_breach_rate > 0 ? m.worst_family : null,
    n_trials: m.n_trials,
    n_breached_families: m.n_families,
  }));

  // Rank: lower mean breach rate = more resistant = higher rank. Tie-break on
  // the worst-case rate (a lower ceiling ranks better), then on trial count
  // (more evidence ranks better) so the order is deterministic.
  rows.sort(
    (a, b) =>
      a.mean_breach_rate - b.mean_breach_rate ||
      a.worst_breach_rate - b.worst_breach_rate ||
      b.n_trials - a.n_trials,
  );
  return rows;
}

/**
 * Roll the OSS open-weight snapshot up to ranked rows. SAME row shape + SAME
 * resistance sort as the main board so the row UI is reused verbatim — but these
 * are a SEPARATE, lighter methodology (single-shot jailbreak pack, ~40 trials
 * each) and are rendered in their own panel, never merged into the main rank.
 */
function buildOssRows(): ModelRow[] {
  const rows: ModelRow[] = LEADERBOARD_OSS_MODELS.map((m) => ({
    config_id: m.target_model,
    model_label: m.model_label,
    config_name: m.target_model,
    target_model: m.target_model,
    mean_breach_rate: m.mean_breach_rate,
    worst_breach_rate: m.worst_breach_rate,
    worst_family: m.worst_breach_rate > 0 ? m.worst_family : null,
    n_trials: m.n_trials,
    n_breached_families: m.n_families,
  }));
  rows.sort(
    (a, b) =>
      a.mean_breach_rate - b.mean_breach_rate ||
      a.worst_breach_rate - b.worst_breach_rate ||
      b.n_trials - a.n_trials,
  );
  return rows;
}

// --------------------------------------------------------------------------

/**
 * slug → {family, config} — the SAME static map `/m/<slug>` and the breach cards use. Every
 * leaderboard row deep-links to its CORRESPONDING /matrix/cell drill-down through it, which works
 * for the open-source rows too (their `fl-*` cells are persisted in the matrix), not just
 * production. Static + bundled, so the board needs no live API call to wire the links.
 */
type CardEntry = { family: string; config: string };
const CARD_MAP = MODEL_CARDS as Record<string, CardEntry>;

function slugFor(modelLabel: string): string {
  return modelLabel.toLowerCase().replace(/\//g, "-");
}

/** The /matrix/cell deep-link for a row's worst family × its config, or null if unmapped. */
function cellHrefFor(row: ModelRow): string | null {
  const entry = CARD_MAP[slugFor(row.model_label)];
  if (!entry) return null;
  const family = row.worst_family ?? entry.family;
  return `/matrix/cell?family=${encodeURIComponent(family)}&config=${encodeURIComponent(entry.config)}&scope=all-time&attacker=augmented&from=leaderboard`;
}

export default function LeaderboardPage() {
  return <Board />;
}

function Board() {
  const rows = buildRows();
  const ossRows = buildOssRows();
  const tested = rows.length;
  const mostResistant = rows[0] ?? null;
  const leastResistant = rows[rows.length - 1] ?? null;
  const totalTrials = LEADERBOARD_TOTAL_TRIALS;

  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-10 space-y-8">
        {/* Header */}
        <header className="flex items-start justify-between gap-6 flex-wrap animate-rogue-fade-up">
          <div className="space-y-2">
            <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
              /leaderboard · all-time · measured as of 2026-06-07
            </p>
            <h1 className="text-3xl sm:text-4xl font-bold tracking-tight">
              Model Resistance Leaderboard
            </h1>
            <p className="text-sm text-muted-foreground max-w-2xl leading-relaxed">
              Every model ROGUE red-teams, ranked by resistance.{" "}
              <span className="text-rogue-green">Lower breach rate</span> ={" "}
              <span className="text-foreground">higher rank</span>. Each model is hit with
              ROGUE&apos;s open-web attack corpus and graded by a calibrated judge.{" "}
              <span className="text-foreground">{tested} production</span> +{" "}
              <span className="text-foreground">{ossRows.length} open-source</span> models — a
              periodic measured snapshot (production as of{" "}
              <span className="text-foreground tabular-nums">2026-06-07</span>), not a live-updating
              feed.
            </p>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            {mostResistant && (
              <Capsule
                label="Most resistant"
                value={`${Math.round(mostResistant.mean_breach_rate * 100)}%`}
                sub={mostResistant.model_label}
                tint="green"
              />
            )}
            {leastResistant && tested > 1 && (
              <Capsule
                label="Most breached"
                value={`${Math.round(leastResistant.mean_breach_rate * 100)}%`}
                sub={leastResistant.model_label}
                tint={leastResistant.mean_breach_rate >= 0.3 ? "red" : "orange"}
              />
            )}
          </div>
        </header>

        {/* Compare CTA — drive readers to test their own model */}
        <SubmitCta />

        {/* Two boards, SIDE-BY-SIDE on desktop (stack on mobile) — deliberately separate
            methodologies, never one merged ranking (production = deep escalation+PAIR;
            open-source = single-shot pack). Each ranks within itself. */}
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground font-mono">
            {"// no breach data yet — the board fills as ROGUE reproduces attacks"}
          </p>
        ) : (
          <div className="grid gap-6 lg:grid-cols-2 items-start animate-rogue-fade-up">
            <MiniBoard
              kicker="closed · deep pipeline · measured 2026-06-07"
              kickerClass="text-rogue-green"
              borderClass="border-border"
              title="Production endpoints"
              blurb={
                <>
                  {tested} hosted models · deep escalation + PAIR pipeline · graded by the{" "}
                  <span className="text-rogue-green">calibrated v3 judge</span> (89.3% human
                  agreement). Snapshot as of 2026-06-07.
                </>
              }
              rows={rows}
            />
            <MiniBoard
              kicker={`open-weight · single-shot · measured ${LEADERBOARD_OSS_MEASURED}`}
              kickerClass="text-rogue-orange"
              borderClass="border-rogue-orange/30"
              title="Open-source models"
              blurb={
                <>
                  {ossRows.length} open-weight models · {LEADERBOARD_OSS_METHOD} · ~40 trials each. A{" "}
                  <span className="text-rogue-orange">lighter, separate methodology</span> —{" "}
                  <span className="text-foreground">not directly comparable</span> to the
                  deep-pipeline board.
                </>
              }
              rows={ossRows}
            />
          </div>
        )}

        {/* Method footnote — covers both boards */}
        <section
          className="text-xs text-muted-foreground font-mono space-y-1 animate-rogue-fade-up"
          style={{ animationDelay: "0.3s" }}
        >
          <p>{"// rank = mean any-breach rate across attack families (lower = more resistant), WITHIN each board"}</p>
          <p>{`// production: ROGUE all-time corpus, ${totalTrials.toLocaleString()} deep-pipeline trials, calibrated v3 judge ([withheld — under anonymized review]) — the same numbers \`rogue try\` prints`}</p>
          <p>{`// open-source: curated single-shot aggressive jailbreak pack (~40 trials each), primitive-level any-breach, measured ${LEADERBOARD_OSS_MEASURED}`}</p>
          <p>{"// the two boards are NOT directly comparable (different methodologies) and are ranked independently"}</p>
          <p>
            {"// periodic measured snapshot, not a live feed — for the live per-family × config breakdown, see the "}
            <Link href="/matrix" className="text-rogue-green hover:underline">
              breach matrix
            </Link>
          </p>
        </section>

        {/* The whole board in one shareable image (both panels, honestly separated). */}
        <ShareCard />
      </div>
    </main>
  );
}

/**
 * One ranked board panel (production OR open-source), compact enough to sit side-by-side with the
 * other on desktop (`lg:grid-cols-2`) and stack on mobile. The two panels are ALWAYS separate
 * methodologies — never one merged ranking — so each carries its own kicker + methodology blurb and
 * ranks within itself. Each row links to its CORRESPONDING /matrix/cell (via `cellHrefFor`), for
 * the open-source rows too — their `fl-*` cells are persisted in the matrix.
 */
function MiniBoard({
  kicker,
  kickerClass,
  borderClass,
  title,
  blurb,
  rows,
}: {
  kicker: string;
  kickerClass: string;
  borderClass: string;
  title: string;
  blurb: ReactNode;
  rows: ModelRow[];
}) {
  if (rows.length === 0) return null;
  return (
    <section className="space-y-4">
      <header className="space-y-1.5">
        <p className={`font-mono text-[10px] uppercase tracking-[0.2em] ${kickerClass}`}>{kicker}</p>
        <h2 className="text-xl sm:text-2xl font-bold tracking-tight">{title}</h2>
        <p className="text-xs text-muted-foreground leading-relaxed">{blurb}</p>
      </header>
      <div className={`rogue-card border ${borderClass} rounded-lg overflow-hidden bg-card/40`}>
        {rows.map((row, i) => (
          <CompactRow key={row.config_id} row={row} rank={i + 1} index={i} />
        ))}
      </div>
    </section>
  );
}

/**
 * One compact ranked row. The WHOLE row is the click target → the model's CORRESPONDING
 * /matrix/cell drill-down (which itself surfaces the breach card), with a chevron affordance so it
 * reads as interactive. Stacks the model name, the breach-rate bar, and a muted subline (worst
 * family · trials). Falls back to a non-interactive div if the model has no mapped cell.
 */
function CompactRow({ row, rank, index }: { row: ModelRow; rank: number; index: number }) {
  const tier = rateTier(row.mean_breach_rate);
  const cellHref = cellHrefFor(row);
  const cls =
    "group grid grid-cols-[1.75rem_minmax(0,1fr)_0.75rem] gap-3 items-start px-3 py-3 border-b border-border/50 last:border-b-0 hover:bg-card/60 transition-colors animate-rogue-fade-up";
  const style = { animationDelay: `${Math.min(index * 0.03, 0.4)}s` };
  const inner = (
    <>
      <div className="flex items-center justify-center pt-0.5">
        <RankBadge rank={rank} />
      </div>
      <div className="min-w-0 space-y-1.5">
        <p
          className="font-mono text-sm font-semibold truncate transition-colors group-hover:text-rogue-green"
          title={row.config_name}
        >
          {row.model_label}
        </p>
        <BreachBar mean={row.mean_breach_rate} tier={tier} />
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-[10px] text-muted-foreground min-w-0">
          {row.worst_family ? (
            <span className="inline-flex min-w-0 items-baseline gap-1 truncate" title={row.worst_family}>
              <span className="truncate text-foreground/80">{row.worst_family}</span>
              <span className="shrink-0 text-rogue-red/80">{Math.round(row.worst_breach_rate * 100)}%</span>
            </span>
          ) : (
            <span className="text-rogue-green">none breached</span>
          )}
          <span className="shrink-0 opacity-60">· n={row.n_trials.toLocaleString()}</span>
        </div>
      </div>
      <span
        aria-hidden
        className="self-center font-mono text-muted-foreground transition-colors group-hover:text-rogue-green"
      >
        ›
      </span>
    </>
  );
  return cellHref ? (
    <Link
      href={cellHref}
      className={cls}
      style={style}
      title={`Drill into ${row.model_label}'s breaches in the matrix`}
    >
      {inner}
    </Link>
  ) : (
    <div className={cls} style={style}>
      {inner}
    </div>
  );
}

/**
 * The composite "whole board in one image" share card — all 24 models in two methodology-separated
 * panels (production deep-pipeline + open-source single-shot), generated by
 * scripts/cards/generate_composite_card.py → /cards/breach-leaderboard.png. Shown inline +
 * downloadable. Deliberately NOT the page OG image: that's the correctly-sized 1200×630 dynamic
 * opengraph-image.tsx; this tall 1600×1500 card would crop badly as a social preview.
 */
function ShareCard() {
  const src = "/cards/breach-leaderboard.png";
  return (
    <section
      className="space-y-5 border-t border-border/60 pt-8 animate-rogue-fade-up"
      style={{ animationDelay: "0.4s" }}
    >
      <header className="space-y-2">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
          /leaderboard · share card
        </p>
        <h2 className="text-2xl sm:text-3xl font-bold tracking-tight">The whole board, one image</h2>
        <p className="text-sm text-muted-foreground max-w-2xl leading-relaxed">
          All 24 models in a single shareable card — production endpoints (deep escalation + PAIR)
          and open-source models (single-shot pack) in two clearly-separated panels.{" "}
          <span className="text-foreground">Not directly comparable</span>; each panel ranks within
          itself.
        </p>
      </header>

      <a
        href={src}
        target="_blank"
        rel="noopener noreferrer"
        className="block overflow-hidden rounded-lg border border-border bg-card/40 transition-colors hover:border-rogue-green/60"
        title="Open the full-size breach leaderboard card"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={src}
          alt="ROGUE breach leaderboard — 24 models ranked across two panels: open-source (single-shot pack) and production (deep escalation + PAIR)"
          width={1600}
          height={1500}
          loading="lazy"
          className="h-auto w-full"
        />
      </a>

      <div className="flex flex-wrap items-center gap-3">
        <a
          href={src}
          download
          className="inline-flex items-center gap-2 rounded-md border border-rogue-green/50 px-4 py-2 font-mono text-xs uppercase tracking-[0.15em] text-rogue-green transition-colors hover:bg-rogue-green/10"
        >
          ↓ Download the card
        </a>
        <span className="font-mono text-[10px] text-muted-foreground">
          1600×1500 · PNG · measured 2026-06-19
        </span>
      </div>
    </section>
  );
}

function RankBadge({ rank }: { rank: number }) {
  // Top-3 get a green-tinted medal feel; the rest are plain mono numerals.
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

/** Horizontal bar: filled to the model's mean breach rate. */
function BreachBar({ mean, tier }: { mean: number; tier: Tier }) {
  const meanPct = Math.max(mean * 100, mean > 0 ? 2 : 0); // floor so a non-zero rate is visible
  const fill = tier === "red" ? "var(--rogue-red)" : tier === "orange" ? "var(--rogue-orange)" : "var(--rogue-green)";
  return (
    <div className="flex items-center gap-2.5">
      <div className="relative h-2.5 flex-1 rounded-full bg-background/70 border border-border/50 overflow-hidden">
        <div
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ width: `${meanPct}%`, background: fill, boxShadow: `0 0 8px ${fill}` }}
        />
      </div>
      <span
        className="font-mono text-xs tabular-nums w-9 text-right"
        style={{ color: tier === "red" ? "var(--rogue-red)" : tier === "orange" ? "var(--rogue-orange)" : "var(--rogue-green)" }}
      >
        {Math.round(mean * 100)}%
      </span>
    </div>
  );
}

type Tier = "green" | "orange" | "red";
function rateTier(r: number): Tier {
  if (r >= 0.3) return "red";
  if (r >= 0.1) return "orange";
  return "green";
}

function Capsule({
  label,
  value,
  sub,
  tint,
}: {
  label: string;
  value: string;
  sub: string;
  tint: Tier;
}) {
  const tintClass =
    tint === "red"
      ? "text-rogue-red border-rogue-red/40 bg-rogue-red/10"
      : tint === "orange"
        ? "text-orange-300 border-orange-500/40 bg-orange-500/10"
        : "text-rogue-green border-rogue-green/40 bg-rogue-green/10";
  return (
    <div className={`px-3 py-2 border rounded-md ${tintClass} font-mono max-w-[220px]`}>
      <p className="text-[9px] uppercase tracking-[0.2em] opacity-70">{label}</p>
      <p className="text-lg font-bold tabular-nums leading-tight">{value}</p>
      <p className="text-[10px] opacity-80 leading-snug mt-0.5 truncate" title={sub}>
        {sub}
      </p>
    </div>
  );
}

/**
 * "Submit your model" CTA — present but DISABLED ("coming soon"). The intake
 * route `/api/leaderboard/submit` is built but gated inert behind
 * ROGUE_LEADERBOARD_SUBMISSIONS (returns 503 by default), pending owner
 * moderation/abuse review, so the button is intentionally non-interactive.
 */
function SubmitCta() {
  return (
    <div className="rogue-card border border-border rounded-lg p-5 bg-card/30 flex flex-col sm:flex-row sm:items-center justify-between gap-4 animate-rogue-fade-up">
      <div className="space-y-1 min-w-0">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
          submit your model
        </p>
        <p className="text-sm text-muted-foreground leading-relaxed max-w-xl">
          Want your own model on the board? Opt-in submissions will be re-verified against the same
          corpus and judge before they appear.
        </p>
      </div>
      <button
        type="button"
        disabled
        aria-disabled="true"
        title="Coming soon — submissions open after moderation review"
        className="shrink-0 inline-flex items-center gap-2 font-mono text-xs uppercase tracking-[0.15em] rounded-md border border-border/60 bg-background/40 px-4 py-2.5 text-muted-foreground cursor-not-allowed"
      >
        Submit · coming soon
      </button>
    </div>
  );
}
