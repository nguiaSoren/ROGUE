"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { SourceLogo } from "@/components/ui/source-logo";

/**
 * Auto-play first-visit intro — 4 panels of 4s each (16s total).
 *
 * Mounts client-side, checks localStorage gate (`rogue:intro-seen`), and if
 * unseen renders a fullscreen overlay above the home page. Auto-advances
 * through 4 panels with a progress bar; "Skip" button always visible top-
 * right; final panel auto-dismisses to reveal the actual dashboard.
 *
 * Audio is intentionally NOT used: browser autoplay policies block audio
 * without prior user interaction, so any narration would silently fail on
 * first visit (which IS the only visit this overlay ever shows on). The
 * visual narrative carries the same story in 16 seconds.
 *
 * On the home page only (mounted from app/page.tsx). Returning visitors —
 * or anyone who clicks Skip — never see it again on the same browser.
 */
const STORAGE_KEY = "rogue:intro-seen-v1";
const PANEL_MS = 4000;
const FADE_MS = 600;

type Panel = {
  eyebrow: string;
  headline: React.ReactNode;
  body: React.ReactNode;
  tint: string; // radial-gradient inner color
  side: React.ReactNode;
};

const PANELS: Panel[] = [
  {
    eyebrow: "01 · the problem",
    headline: (
      <>
        Your AI is being{" "}
        <span className="text-rogue-red">jailbroken</span> right now.
      </>
    ),
    body: (
      <>
        Every day, attackers and researchers publish new ways to make
        ChatGPT, Claude, and Llama do things they shouldn&apos;t — on
        Reddit, X, GitHub, arXiv. Most security teams don&apos;t find out
        until a customer screenshots the breach.
      </>
    ),
    tint: "rgba(255, 0, 60, 0.18)",
    side: <ProblemVisual />,
  },
  {
    eyebrow: "02 · the harvest",
    headline: (
      <>
        ROGUE watches the open web{" "}
        <span className="text-rogue-green">continuously.</span>
      </>
    ),
    body: (
      <>
        All 5 Bright Data products, fanning out across 19 open-web sources.
        A self-tuning bandit decides where to spend the next dollar so the
        most-novel attacks get found first.
      </>
    ),
    tint: "rgba(0, 255, 136, 0.15)",
    side: <HarvestVisual />,
  },
  {
    eyebrow: "03 · the test",
    headline: (
      <>
        Every attack ran against{" "}
        <span className="text-cyan-300">your exact stack.</span>
      </>
    ),
    body: (
      <>
        Every deployment config × 5 trials × 5 stress tests. Persona wraps,
        multi-turn escalation, wording mutations — and an iterative
        attacker that keeps refining until it breaks.
      </>
    ),
    tint: "rgba(34, 211, 238, 0.16)",
    side: <TestVisual />,
  },
  {
    eyebrow: "04 · the brief",
    headline: (
      <>
        And ships a brief your{" "}
        <span className="text-yellow-300">CISO can read.</span>
      </>
    ),
    body: (
      <>
        Markdown, JSON, Slack — every finding carries 95% confidence
        intervals. Plus an MCP server Claude Desktop can query directly,
        so your assistant always knows what&apos;s breaching today.
      </>
    ),
    tint: "rgba(251, 191, 36, 0.16)",
    side: <BriefVisual />,
  },
];

type Stage = "ssr" | "hidden" | "showing" | "exiting" | "done";

export function IntroOverlay() {
  const [stage, setStage] = useState<Stage>("ssr");
  const [index, setIndex] = useState(0);
  const dismissTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (dismissTimerRef.current !== null) {
        window.clearTimeout(dismissTimerRef.current);
      }
    };
  }, []);

  // Single mount-time decision: read localStorage and transition out of the
  // SSR-safe "ssr" stage into the real one. This is the canonical pattern
  // for SSR-safe localStorage-gated rendering — the alternative
  // (useSyncExternalStore for localStorage detection) is heavier for a
  // first-paint flash that resolves in <16ms anyway.
  useEffect(() => {
    let seen = false;
    let force = false;
    try {
      seen = window.localStorage.getItem(STORAGE_KEY) === "1";
      // `?intro` in the URL force-replays it (handy for demos / verifying changes).
      force = new URLSearchParams(window.location.search).has("intro");
    } catch {
      /* localStorage blocked — fall through to showing */
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStage(seen && !force ? "done" : "showing");
  }, []);

  const dismiss = useCallback(() => {
    setStage("exiting");
    try {
      window.localStorage.setItem(STORAGE_KEY, "1");
    } catch {
      /* swallow */
    }
    if (dismissTimerRef.current !== null) {
      window.clearTimeout(dismissTimerRef.current);
    }
    dismissTimerRef.current = window.setTimeout(
      () => setStage("done"),
      FADE_MS,
    );
  }, []);

  // Auto-advance — only when actively showing
  useEffect(() => {
    if (stage !== "showing") return;
    if (index >= PANELS.length - 1) {
      const t = window.setTimeout(dismiss, PANEL_MS);
      return () => window.clearTimeout(t);
    }
    const t = window.setTimeout(() => setIndex((i) => i + 1), PANEL_MS);
    return () => window.clearTimeout(t);
  }, [stage, index, dismiss]);

  if (stage === "ssr" || stage === "done") return null;
  const exiting = stage === "exiting";

  const panel = PANELS[index];
  const progress = ((index + 1) / PANELS.length) * 100;

  return (
    <div
      className={`fixed inset-0 z-[100] flex items-center justify-center transition-opacity ease-out ${
        exiting ? "opacity-0" : "opacity-100"
      }`}
      style={{ transitionDuration: `${FADE_MS}ms` }}
      aria-modal="true"
      role="dialog"
      aria-label="Welcome to ROGUE — 16-second intro"
    >
      {/* Background — animated gradient mesh + grid overlay */}
      <div
        className="absolute inset-0 transition-all duration-1000"
        style={{
          background: `
            radial-gradient(1100px 600px at 20% 30%, ${panel.tint}, transparent 60%),
            radial-gradient(800px 500px at 80% 70%, ${panel.tint}, transparent 60%),
            #050508
          `,
        }}
      />
      <div
        className="absolute inset-0 opacity-40 pointer-events-none"
        style={{
          backgroundImage:
            "linear-gradient(rgba(0, 255, 136, 0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(0, 255, 136, 0.04) 1px, transparent 1px)",
          backgroundSize: "80px 80px",
        }}
      />

      {/* Skip button */}
      <button
        type="button"
        onClick={dismiss}
        className="absolute top-4 right-4 sm:top-6 sm:right-6 z-10 min-h-[44px] px-4 py-2 rounded-md border border-border bg-card/40 backdrop-blur-md font-mono text-[11px] uppercase tracking-[0.2em] text-muted-foreground hover:text-rogue-green hover:border-rogue-green transition-colors"
      >
        skip intro →
      </button>

      {/* Panel content */}
      <div className="relative z-[1] max-w-6xl mx-auto px-6 py-12 w-full grid grid-cols-1 lg:grid-cols-[1.3fr_1fr] gap-10 items-center">
        <div
          key={`text-${index}`}
          className="space-y-5 animate-rogue-reveal"
        >
          <p className="font-mono text-[11px] uppercase tracking-[0.25em] text-rogue-green">
            {panel.eyebrow}
          </p>
          <h2 className="text-4xl md:text-6xl lg:text-7xl font-bold tracking-tight leading-[1.05]">
            {panel.headline}
          </h2>
          <p className="text-lg md:text-xl text-muted-foreground leading-relaxed max-w-2xl">
            {panel.body}
          </p>
        </div>
        <div key={`vis-${index}`} className="animate-rogue-reveal" style={{ animationDelay: "0.2s" }}>
          {panel.side}
        </div>
      </div>

      {/* Bottom progress bar */}
      <div className="absolute bottom-0 inset-x-0 z-10">
        <div className="px-6 pb-3 flex items-center justify-between">
          <div className="flex items-center gap-3 font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
            <span>{String(index + 1).padStart(2, "0")}</span>
            <span className="text-muted-foreground/40">
              / {String(PANELS.length).padStart(2, "0")}
            </span>
            <span className="text-muted-foreground/60">· 16s intro</span>
          </div>
          <div className="flex gap-1.5">
            {PANELS.map((_, i) => (
              <button
                key={i}
                type="button"
                onClick={() => setIndex(i)}
                className={`h-1 rounded-full transition-all ${
                  i === index
                    ? "w-12 bg-rogue-green"
                    : i < index
                      ? "w-6 bg-rogue-green/40"
                      : "w-6 bg-card/60 hover:bg-card"
                }`}
                aria-label={`Go to panel ${i + 1}`}
              />
            ))}
          </div>
        </div>
        <div
          className="h-0.5 bg-rogue-green/70 transition-all"
          style={{
            width: `${progress}%`,
            boxShadow: "0 0 12px var(--rogue-green-dim)",
            transitionDuration: `${PANEL_MS}ms`,
          }}
        />
      </div>
    </div>
  );
}

// --- Side visuals ----------------------------------------------------------
// Pure-CSS visual accents that reinforce each panel's mood. Lightweight so
// the overlay stays under 30kb gzipped.

function ProblemVisual() {
  const fakeAttacks = [
    "DAN 2024.12 — roleplay bypass",
    "agent prompt-smuggle via Markdown",
    "L1B3RT4S system-prompt leak",
    "Crescendo 3-turn — Claude 3.5 Sonnet",
    "PAP authority-frame on GPT-4o",
    "tool-injection via memory recall",
  ];
  return (
    <div className="space-y-1.5 font-mono text-xs">
      {fakeAttacks.map((a, i) => (
        <div
          key={a}
          className="flex items-center gap-2 px-3 py-1.5 rounded-md border border-rogue-red/30 bg-rogue-red/5 animate-rogue-fade-up"
          style={{ animationDelay: `${0.3 + i * 0.12}s` }}
        >
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-rogue-red animate-rogue-pulse-critical" />
          <span className="text-foreground/90">{a}</span>
          <span className="text-muted-foreground ml-auto text-[10px]">
            {i + 1}h ago
          </span>
        </div>
      ))}
    </div>
  );
}

function HarvestVisual() {
  const sources = ["Reddit", "X", "GitHub", "HuggingFace", "arXiv", "leak mirrors"];
  const products = [
    "Web Scraper API",
    "SERP API",
    "Web Unlocker",
    "Scraping Browser",
    "MCP Server",
  ];
  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
          5 Bright Data products
        </p>
        <div className="flex flex-wrap gap-1.5">
          {products.map((p, i) => (
            <span
              key={p}
              className="px-2.5 py-1 rounded-md border border-rogue-green/40 bg-rogue-green/5 font-mono text-[11px] text-rogue-green animate-rogue-fade-up"
              style={{ animationDelay: `${0.2 + i * 0.08}s` }}
            >
              {p}
            </span>
          ))}
        </div>
      </div>
      <div className="space-y-1.5">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
          19 open-web sources
        </p>
        <div className="flex flex-wrap gap-1.5">
          {sources.map((s, i) => (
            <span
              key={s}
              className="px-2 py-1 rounded-md border border-border bg-card/40 font-mono text-[11px] animate-rogue-fade-up inline-flex items-center gap-1.5"
              style={{ animationDelay: `${0.6 + i * 0.07}s` }}
            >
              <SourceLogo source={s} className="text-foreground/70" />
              {s}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function TestVisual() {
  // 5 × 5 grid of cells, some lit (representing trials × configs).
  const cells = Array.from({ length: 25 });
  return (
    <div className="space-y-2">
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-cyan-300">
        every config × 5 trials each
      </p>
      <div className="grid grid-cols-5 gap-1.5 max-w-[260px]">
        {cells.map((_, i) => {
          // Mix: red (breach), orange (partial), green (defended), some empty
          const states = ["red", "orange", "green", "green", "muted", "red"];
          const state = states[i % states.length];
          const cls =
            state === "red"
              ? "bg-rogue-red/40 border-rogue-red/60"
              : state === "orange"
                ? "bg-orange-500/40 border-orange-500/60"
                : state === "green"
                  ? "bg-rogue-green/30 border-rogue-green/50"
                  : "bg-card/40 border-border";
          return (
            <div
              key={i}
              className={`aspect-square rounded-sm border ${cls} animate-rogue-cell-pop`}
              style={{ animationDelay: `${0.2 + i * 0.03}s` }}
            />
          );
        })}
      </div>
      <p className="font-mono text-[10px] text-muted-foreground pt-1">
        each cell = one attack × one config × one trial
      </p>
    </div>
  );
}

function BriefVisual() {
  return (
    <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/5 p-4 space-y-2 font-mono text-[11px] animate-rogue-fade-up">
      <p className="text-yellow-300 uppercase tracking-[0.2em] text-[10px]">
        threat brief · today
      </p>
      <p className="text-foreground">
        <span className="text-rogue-red">3 new CRITICAL</span> breaches
        across customer-chat config
      </p>
      <p className="text-muted-foreground">
        PAIR refined &quot;DAN-2024.12&quot; until 4/5 trials breached on
        turn 2 (95% CI: 51–93%)
      </p>
      <div className="flex gap-2 pt-1">
        <span className="px-2 py-0.5 border border-border rounded-sm text-muted-foreground">
          ↓ .md
        </span>
        <span className="px-2 py-0.5 border border-border rounded-sm text-muted-foreground">
          ↓ .json
        </span>
        <span className="px-2 py-0.5 border border-rogue-green/40 text-rogue-green rounded-sm">
          MCP → Claude Desktop
        </span>
      </div>
    </div>
  );
}
