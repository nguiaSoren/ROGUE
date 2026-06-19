"use client";

import { useState } from "react";

/**
 * Shared "What this is / Why it matters" header used on every augmentation
 * widget + the cinematic showcase.
 *
 * Two sizes:
 *   - "compact" (sidebar widgets): eyebrow + one-line subhead + (i) popover.
 *   - "hero"    (showcase cards):  eyebrow + plain-English headline + body.
 *
 * The whole point of this primitive: a non-technical visitor (CISO, judge)
 * can land on any tile and answer "what is this and why should I care?" in
 * under 5 seconds.
 */
export function ExplainerHeader({
  accentBorderClass,
  accentTextClass,
  eyebrow,
  shortSubhead,
  whatItIs,
  whyItMatters,
  size = "compact",
}: {
  accentBorderClass?: string; // unused inside header (parent owns the border)
  accentTextClass: string;
  eyebrow: React.ReactNode;
  shortSubhead: React.ReactNode;
  whatItIs: React.ReactNode;
  whyItMatters: React.ReactNode;
  size?: "compact" | "hero";
}) {
  void accentBorderClass;
  const [open, setOpen] = useState(false);

  if (size === "hero") {
    return (
      <header className="space-y-2">
        <p
          className={`text-[11px] font-mono uppercase tracking-[0.22em] ${accentTextClass}`}
        >
          {eyebrow}
        </p>
        <p className="text-xl md:text-2xl font-semibold leading-snug max-w-xl">
          {whatItIs}
        </p>
        <p className="text-sm text-muted-foreground leading-relaxed max-w-xl">
          {whyItMatters}
        </p>
      </header>
    );
  }

  return (
    <header className="relative">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p
            className={`text-[10px] font-mono uppercase tracking-[0.2em] ${accentTextClass}`}
          >
            {eyebrow}
          </p>
          <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
            {shortSubhead}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-label="What is this?"
          className={`shrink-0 w-5 h-5 rounded-full border border-border text-[10px] font-mono leading-none flex items-center justify-center transition-colors hover:border-rogue-green hover:text-rogue-green ${
            open ? "border-rogue-green text-rogue-green" : "text-muted-foreground"
          }`}
        >
          ?
        </button>
      </div>
      {open && (
        <div className="mt-2 p-3 rounded-md bg-black/40 border border-border space-y-1.5 text-[11px] leading-relaxed animate-rogue-fade-up">
          <div>
            <p className="font-mono uppercase tracking-wider text-[9px] text-muted-foreground">
              what this is
            </p>
            <p className="text-foreground/90">{whatItIs}</p>
          </div>
          <div>
            <p className="font-mono uppercase tracking-wider text-[9px] text-muted-foreground">
              why it matters
            </p>
            <p className="text-foreground/90">{whyItMatters}</p>
          </div>
        </div>
      )}
    </header>
  );
}
