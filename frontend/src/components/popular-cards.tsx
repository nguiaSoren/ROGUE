"use client";

import { useState } from "react";

import {
  LEADERBOARD_MODELS,
  LEADERBOARD_OSS_MODELS,
  type LeaderboardModel,
} from "@/lib/leaderboard-data";
import { track } from "@/lib/analytics";
import { cn } from "@/lib/utils";

/**
 * Zero-input, zero-cost "see a popular model's breach card" picker for /scan.
 *
 * Client component, but it makes NO network calls and hits NO backend: every
 * chip points at a STATIC, pre-rendered breach card PNG that already lives in
 * `frontend/public/cards/<slug>.png`. Clicking a chip just swaps the displayed
 * <img>. This is the "no endpoint?" path — a visitor with no model endpoint /
 * key still has something to do on /scan instead of bouncing.
 *
 * The slug for a card filename = `model_label.toLowerCase().replace(/\//g,"-")`
 * — the SAME mapping the /leaderboard page and /m/<slug> routes use
 * (`slugFor` in app/leaderboard/page.tsx). The numbers/labels are derived from
 * the bundled `@/lib/leaderboard-data` snapshot, never hardcoded here.
 *
 * The Share-on-X intent + leaderboard link mirror `public-scan.tsx`.
 */

// The leaderboard is the public landing target for a shared breach card —
// same constant the live-scan result view uses.
const SHARE_URL = "https://rogue-eosin.vercel.app/leaderboard";

/** slug for the static card filename — identical to leaderboard `slugFor`. */
function slugFor(modelLabel: string): string {
  return modelLabel.toLowerCase().replace(/\//g, "-");
}

/**
 * The curated picker set — ~8 recognizable names with a DRAMATIC breach-rate
 * spread, from the most-resistant frontier model to an abliterated open-weight
 * shock. Pulled BY LABEL out of the two bundled snapshots so the rates + worst
 * family stay in sync with /leaderboard; every entry's `<slug>.png` is verified
 * to exist under public/cards/.
 */
const CURATED_LABELS: readonly string[] = [
  "claude-opus-4-8", // most resistant (production)
  "claude-haiku-4-5", // production
  "gpt-5.4-nano", // production
  "llama-3.1-8b-instruct", // production
  "DeepSeek-R1-Distill-Llama-70B", // OSS
  "Qwen2.5-72B-Instruct", // OSS
  "Mistral-Nemo-Instruct-2407", // OSS
  "Meta-Llama-3.1-8B-Instruct-abliterated", // OSS — the shock (~73%)
] as const;

// Index both snapshots by label, then resolve the curated set in order. Skipping
// any label that isn't found keeps this resilient to a snapshot rename.
const BY_LABEL = new Map<string, LeaderboardModel>(
  [...LEADERBOARD_MODELS, ...LEADERBOARD_OSS_MODELS].map((m) => [m.model_label, m]),
);

const CURATED: LeaderboardModel[] = CURATED_LABELS.flatMap((label) => {
  const m = BY_LABEL.get(label);
  return m ? [m] : [];
});

// Resistance order (lowest breach rate first) so the spread reads dramatically
// left-to-right / top-to-bottom: resistant → breached.
CURATED.sort((a, b) => a.mean_breach_rate - b.mean_breach_rate);

type Tier = "green" | "orange" | "red";
function rateTier(r: number): Tier {
  if (r >= 0.3) return "red";
  if (r >= 0.1) return "orange";
  return "green";
}
function tierColor(tier: Tier): string {
  return tier === "red"
    ? "var(--rogue-red)"
    : tier === "orange"
      ? "var(--rogue-orange)"
      : "var(--rogue-green)";
}

const secondaryButton = cn(
  "inline-flex items-center gap-2 rounded-md border px-4 py-2",
  "font-mono text-xs uppercase tracking-[0.15em]",
  "transition-colors",
);

export function PopularCards() {
  const [selected, setSelected] = useState<LeaderboardModel>(CURATED[0]);

  function pick(model: LeaderboardModel) {
    setSelected(model);
    track("popular_card_view", {
      model: model.model_label,
      rate: Math.round(model.mean_breach_rate * 100),
    });
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
          no endpoint? · zero install
        </p>
        <h2 className="text-2xl sm:text-3xl font-bold tracking-tight">
          See how the popular models score →
        </h2>
        <p className="text-sm text-muted-foreground max-w-2xl leading-relaxed">
          No key, no setup — pick a recognizable model and see its{" "}
          <span className="text-foreground">already-measured breach card</span> instantly. These are
          ROGUE&apos;s real standings; the full ranking lives on the{" "}
          <a href="/leaderboard" className="text-rogue-green hover:underline">
            leaderboard
          </a>
          .
        </p>
      </div>

      {/* The curated chips — click to swap the displayed card. */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2.5">
        {CURATED.map((m) => {
          const tier = rateTier(m.mean_breach_rate);
          const ratePct = Math.round(m.mean_breach_rate * 100);
          const active = m.model_label === selected.model_label;
          return (
            <button
              key={m.model_label}
              type="button"
              onClick={() => pick(m)}
              aria-pressed={active}
              title={m.target_model}
              className={cn(
                "rogue-card group rounded-lg border px-3 py-2.5 text-left transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rogue-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                active
                  ? "border-rogue-green/60 bg-rogue-green/[0.06]"
                  : "border-border bg-card/40 hover:bg-card/60 hover:border-rogue-green/30",
              )}
            >
              <span className="block min-w-0 truncate font-mono text-xs font-semibold text-foreground">
                {m.model_label}
              </span>
              <span
                className="mt-1 block font-mono text-[11px] tabular-nums"
                style={{ color: tierColor(tier) }}
              >
                {ratePct}% breach
              </span>
            </button>
          );
        })}
      </div>

      <CardPreview model={selected} />
    </div>
  );
}

/**
 * The selected model's static, pre-rendered breach card + download / share. No
 * fetch — the <img> src is a same-origin static asset. `key` on the wrapper
 * re-triggers the fade-up when the selection changes.
 */
function CardPreview({ model }: { model: LeaderboardModel }) {
  const slug = slugFor(model.model_label);
  const src = `/cards/${slug}.png`;
  const ratePct = Math.round(model.mean_breach_rate * 100);
  const tier = rateTier(model.mean_breach_rate);

  const shareText = `${model.model_label} breaches at ${ratePct}% — see how every model ranks against ROGUE's open-web attack corpus:`;
  const shareHref = `https://twitter.com/intent/tweet?text=${encodeURIComponent(
    shareText,
  )}&url=${encodeURIComponent(SHARE_URL)}`;

  return (
    <div key={slug} className="space-y-4 animate-rogue-fade-up">
      <p className="font-mono text-sm text-muted-foreground">
        <span className="text-foreground">{model.model_label}</span> ·{" "}
        <span className="tabular-nums" style={{ color: tierColor(tier) }}>
          {ratePct}%
        </span>{" "}
        mean breach
        <span className="block opacity-70 mt-0.5">
          worst family: {model.worst_family} ({Math.round(model.worst_breach_rate * 100)}%) · n=
          {model.n_trials.toLocaleString()}
        </span>
      </p>

      <div className="overflow-hidden rounded-lg border border-border bg-card/40">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={src}
          alt={`ROGUE breach card for ${model.model_label} — ${ratePct}% mean breach rate against ROGUE's open-web attack corpus, graded by the calibrated v3 judge`}
          className="h-auto w-full"
        />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <a
          href={src}
          download={`rogue-breach-card-${slug}.png`}
          onClick={() => track("popular_card_download", { model: model.model_label })}
          className={cn(secondaryButton, "border-rogue-green/50 text-rogue-green hover:bg-rogue-green/10")}
        >
          ↓ Download card
        </a>
        <a
          href={shareHref}
          target="_blank"
          rel="noopener noreferrer"
          onClick={() => track("popular_card_share_x", { model: model.model_label, rate: ratePct })}
          className={cn(secondaryButton, "border-border text-foreground hover:bg-card/60")}
        >
          Share on X
        </a>
        <a
          href="/leaderboard"
          className={cn(secondaryButton, "border-border text-muted-foreground hover:bg-card/60")}
        >
          See the full ranking →
        </a>
      </div>

      <p className="font-mono text-[10px] text-muted-foreground leading-relaxed">
        {"// pre-measured snapshot · no scan run · for the full per-family × config breakdown see the "}
        <a href="/leaderboard" className="text-rogue-green hover:underline">
          leaderboard
        </a>
      </p>
    </div>
  );
}
