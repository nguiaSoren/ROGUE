/**
 * research-figures.tsx — paper-grade, dark-native data visualizations for the
 * /research page. Pure presentational server components: no charting library,
 * no canvas — just styled divs. The only motion is the page's existing
 * `animate-rogue-fade-up`, applied by the page where each figure is dropped in.
 *
 * Conventions matching the "rogue" aesthetic:
 *  - rogue-green for the ROGUE / "after" series
 *  - muted gray (bg-muted / text-muted-foreground) for baselines / "before"
 *  - rogue-red ONLY for the worse / "before" ROGUE state
 *  - mono uppercase micro-labels, rogue-card surfaces (border + bg-card/40)
 * All numbers are verbatim from the operator's brief.
 */

type Tone = "green" | "muted" | "red";

const TRACK_FILL: Record<Tone, string> = {
  green: "bg-rogue-green",
  muted: "bg-muted",
  red: "bg-rogue-red",
};

const VALUE_TEXT: Record<Tone, string> = {
  green: "text-rogue-green",
  muted: "text-muted-foreground",
  red: "text-rogue-red",
};

/** Shared figure shell: rogue-card surface + caption slot. */
function Figure({
  caption,
  children,
}: {
  caption?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <figure className="rogue-card border border-border rounded-xl p-5 md:p-6 bg-card/40 backdrop-blur-sm not-prose">
      {children}
      {caption && (
        <figcaption className="mt-4 text-xs text-muted-foreground leading-relaxed">
          {caption}
        </figcaption>
      )}
    </figure>
  );
}

/** A mono-eyebrow "Method —" rigor note, restrained and muted. */
export function MethodNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground/80 leading-relaxed">
      {children}
    </p>
  );
}

// --------------------------------------------------------------------------
// Fig 1 — Judge agreement vs the field (% agreement with the human majority)
// --------------------------------------------------------------------------

type RankedBar = {
  label: string;
  value: number;
  tone: Tone;
  emphasis?: boolean;
};

/** Horizontal % bars, scale 0–100, drawn in the order given (sorted ascending). */
export function JudgeAgreementFig() {
  const rows: RankedBar[] = [
    { label: "ROGUE v1", value: 70.3, tone: "red" },
    { label: "HarmBench", value: 78.3, tone: "muted" },
    { label: "LlamaGuard-2", value: 87.7, tone: "muted" },
    { label: "ROGUE v3", value: 89.3, tone: "green", emphasis: true },
    { label: "GPT-4", value: 90.3, tone: "muted" },
    { label: "Llama-3", value: 90.7, tone: "muted" },
  ];

  return (
    <Figure caption="Recalibration moved ROGUE from last of five to 3rd, tied with the frontier classifiers.">
      <figcaption className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green mb-4">
        Judge agreement with human majority — JBB judge_comparison
      </figcaption>
      <div className="space-y-2.5">
        {rows.map((r) => (
          <div
            key={r.label}
            className="grid grid-cols-[7.5rem_1fr_3rem] items-center gap-3"
          >
            <span
              className={`font-mono text-[11px] truncate ${
                r.emphasis ? "text-foreground font-medium" : "text-muted-foreground"
              }`}
            >
              {r.label}
            </span>
            <div
              className="relative h-5 w-full rounded-sm bg-border/40 overflow-hidden"
              role="img"
              aria-label={`${r.label}: ${r.value}% agreement`}
            >
              <div
                className={`h-full rounded-sm ${TRACK_FILL[r.tone]} ${
                  r.emphasis ? "ring-1 ring-rogue-green/60" : ""
                }`}
                style={{ width: `${r.value}%` }}
              />
            </div>
            <span
              className={`text-right tabular-nums text-sm font-medium ${
                VALUE_TEXT[r.tone]
              }`}
            >
              {r.value}%
            </span>
          </div>
        ))}
      </div>
      <p className="mt-3 font-mono text-[9px] uppercase tracking-[0.16em] text-muted-foreground/70">
        scale 0–100% · sorted ascending
      </p>
    </Figure>
  );
}

// --------------------------------------------------------------------------
// Fig 2 — Scheduling, before → after (single-variable controlled experiment)
// --------------------------------------------------------------------------

type BeforeAfter = {
  metric: string;
  before: { display: string; frac: number };
  after: { display: string; frac: number };
  /** Which direction is better. */
  better: "lower" | "higher";
  /** Optional delta tag on the "after" bar. */
  delta?: string;
};

/** Three before/after pairs; each pair shares a normalized 0–1 scale. */
export function SchedulingFig() {
  // Each metric is normalized within its own pair so the longer bar is the
  // larger raw magnitude; the "better" arrow tells the reader the direction.
  const pairs: BeforeAfter[] = [
    {
      metric: "Median winner-rank",
      better: "lower",
      before: { display: "22", frac: 22 / 22 },
      after: { display: "11", frac: 11 / 22 },
    },
    {
      metric: "Attack-success-rate",
      better: "higher",
      before: { display: "50%", frac: 50 / 60 },
      after: { display: "60%", frac: 60 / 60 },
    },
    {
      metric: "Cost per success",
      better: "lower",
      delta: "−41%",
      before: { display: "$1.25", frac: 1.25 / 1.25 },
      after: { display: "$0.74", frac: 0.74 / 1.25 },
    },
  ];

  return (
    <Figure caption="Single-variable controlled experiment — only the ladder order changed.">
      <figcaption className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green mb-4">
        Scheduling, before → after
      </figcaption>
      <div className="space-y-5">
        {pairs.map((p) => (
          <div key={p.metric} className="space-y-1.5">
            <div className="flex items-baseline justify-between">
              <span className="font-mono text-[11px] text-foreground/90">
                {p.metric}
              </span>
              <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-muted-foreground/70">
                {p.better === "lower" ? "lower is better ↓" : "higher is better ↑"}
              </span>
            </div>

            {/* before */}
            <div
              className="grid grid-cols-[3.5rem_1fr_3.5rem] items-center gap-3"
              role="img"
              aria-label={`${p.metric} before: ${p.before.display}`}
            >
              <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-muted-foreground">
                before
              </span>
              <div className="h-4 w-full rounded-sm bg-border/40 overflow-hidden">
                <div
                  className="h-full rounded-sm bg-muted"
                  style={{ width: `${p.before.frac * 100}%` }}
                />
              </div>
              <span className="text-right tabular-nums text-sm text-muted-foreground">
                {p.before.display}
              </span>
            </div>

            {/* after */}
            <div
              className="grid grid-cols-[3.5rem_1fr_3.5rem] items-center gap-3"
              role="img"
              aria-label={`${p.metric} after: ${p.after.display}`}
            >
              <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-rogue-green">
                after
              </span>
              <div className="h-4 w-full rounded-sm bg-border/40 overflow-hidden">
                <div
                  className="h-full rounded-sm bg-rogue-green"
                  style={{ width: `${p.after.frac * 100}%` }}
                />
              </div>
              <span className="text-right tabular-nums text-sm font-medium text-rogue-green">
                {p.after.display}
                {p.delta && (
                  <span className="block font-mono text-[9px] text-rogue-green/80">
                    {p.delta}
                  </span>
                )}
              </span>
            </div>
          </div>
        ))}
      </div>
    </Figure>
  );
}

// --------------------------------------------------------------------------
// Fig 3 — The 5 false-positive modes (20-row audit, 9 FPs), by count
// --------------------------------------------------------------------------

export function FalsePositiveModesFig() {
  const modes: { label: string; count: number }[] = [
    { label: "Acknowledgment-as-compliance", count: 3 },
    { label: "Persona/format acceptance", count: 2 },
    { label: "Meta-discussion of the attack", count: 2 },
    { label: "Fiction/nonsense credited", count: 1 },
    { label: "Intent-anchoring on a benign render", count: 1 },
  ];
  const max = 3;

  return (
    <Figure caption="All 9 false positives = engaged with the frame, transferred no harmful content.">
      <figcaption className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green mb-4">
        False-positive modes — 20-row audit, 9 FPs
      </figcaption>
      <div className="space-y-2.5">
        {modes.map((m) => (
          <div
            key={m.label}
            className="grid grid-cols-[1fr_2rem] items-center gap-3"
          >
            <div
              className="flex items-center gap-3"
              role="img"
              aria-label={`${m.label}: ${m.count}`}
            >
              <div className="h-4 rounded-sm bg-border/40 overflow-hidden grow">
                <div
                  className="h-full rounded-sm bg-rogue-red/80"
                  style={{ width: `${(m.count / max) * 100}%` }}
                />
              </div>
            </div>
            <span className="text-right tabular-nums text-sm font-medium text-rogue-red">
              {m.count}
            </span>
            <span className="col-span-2 -mt-1 font-mono text-[10px] text-muted-foreground">
              {m.label}
            </span>
          </div>
        ))}
      </div>
    </Figure>
  );
}

// --------------------------------------------------------------------------
// Fig 4 — Breach matrix, before vs after the v3 re-judge
// --------------------------------------------------------------------------

export function BreachRejudgeFig() {
  const before = 2429;
  const after = 1371;
  const max = before;

  return (
    <Figure caption="Re-judging corrected the over-reporting.">
      <figcaption className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green mb-4">
        Breach matrix — before vs after the v3 re-judge
      </figcaption>
      <div className="space-y-3">
        <div
          className="grid grid-cols-[3.5rem_1fr_4rem] items-center gap-3"
          role="img"
          aria-label={`Before re-judge: ${before} breach cells`}
        >
          <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-muted-foreground">
            before
          </span>
          <div className="h-5 w-full rounded-sm bg-border/40 overflow-hidden">
            <div
              className="h-full rounded-sm bg-muted"
              style={{ width: `${(before / max) * 100}%` }}
            />
          </div>
          <span className="text-right tabular-nums text-sm text-muted-foreground">
            2,429
          </span>
        </div>
        <div
          className="grid grid-cols-[3.5rem_1fr_4rem] items-center gap-3"
          role="img"
          aria-label={`After re-judge: ${after} breach cells`}
        >
          <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-rogue-green">
            after
          </span>
          <div className="h-5 w-full rounded-sm bg-border/40 overflow-hidden">
            <div
              className="h-full rounded-sm bg-rogue-green"
              style={{ width: `${(after / max) * 100}%` }}
            />
          </div>
          <span className="text-right tabular-nums text-sm font-medium text-rogue-green">
            1,371
          </span>
        </div>
      </div>
      <p className="mt-3 font-mono text-[11px] uppercase tracking-[0.18em] text-rogue-green">
        −43.6%
      </p>
    </Figure>
  );
}

// --------------------------------------------------------------------------
// Fig 5 — The null result (mini forest plot), OR axis ~0.5–2, line at OR=1
// --------------------------------------------------------------------------

export function NullResultForestFig() {
  const rows: { label: string; or: number }[] = [
    { label: "authority_frame", or: 1.05 },
    { label: "language_shift", or: 1.0 },
    { label: "encoding_obfuscation", or: 1.1 },
    { label: "structured_output", or: 1.0 },
  ];
  // Axis: OR 0.5 → 2.0, mapped linearly to 0–100%.
  const AXIS_MIN = 0.5;
  const AXIS_MAX = 2.0;
  const pos = (or: number) =>
    ((or - AXIS_MIN) / (AXIS_MAX - AXIS_MIN)) * 100;
  const onePos = pos(1);

  return (
    <Figure caption="Family-mirror nodes showed OR 3–4.5× but were flagged circular and excluded; striking pre-FDR synergies (OR up to 16.8) survived 0 of 4 controls.">
      <figcaption className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green mb-4">
        Grammar-component predictive power — odds ratios
      </figcaption>
      <div className="space-y-3">
        {rows.map((r) => (
          <div
            key={r.label}
            className="grid grid-cols-[8.5rem_1fr_3rem] items-center gap-3"
          >
            <span className="font-mono text-[11px] text-muted-foreground truncate">
              {r.label}
            </span>
            <div
              className="relative h-5"
              role="img"
              aria-label={`${r.label}: odds ratio ${r.or}, not significant`}
            >
              {/* OR = 1 reference line */}
              <div
                className="absolute top-0 bottom-0 w-px bg-rogue-green/50"
                style={{ left: `${onePos}%` }}
                aria-hidden
              />
              {/* marker dot */}
              <div
                className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-muted-foreground ring-2 ring-background"
                style={{ left: `${pos(r.or)}%` }}
                aria-hidden
              />
            </div>
            <span className="text-right font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground/80">
              n.s.
            </span>
          </div>
        ))}
      </div>
      {/* axis ticks */}
      <div className="grid grid-cols-[8.5rem_1fr_3rem] gap-3 mt-1">
        <span />
        <div className="relative h-4">
          <span
            className="absolute -translate-x-1/2 font-mono text-[9px] text-muted-foreground/70"
            style={{ left: `${pos(0.5)}%` }}
          >
            0.5
          </span>
          <span
            className="absolute -translate-x-1/2 font-mono text-[9px] text-rogue-green/80"
            style={{ left: `${onePos}%` }}
          >
            1 (no effect)
          </span>
          <span
            className="absolute -translate-x-1/2 font-mono text-[9px] text-muted-foreground/70"
            style={{ left: `${pos(2.0)}%` }}
          >
            2.0
          </span>
        </div>
        <span />
      </div>
    </Figure>
  );
}
