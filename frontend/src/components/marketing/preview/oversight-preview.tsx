import { ShieldCheck, ShieldAlert, KeyRound, Lock } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * OversightPreview, a pixel-faithful, NON-functional native preview of ROGUE's
 * human-gate / oversight panel (the v2 Surface-2 idea), framed in a faux
 * app-window for the marketing site. It mirrors the real oversight loop in
 * `src/rogue/oversight/` (a gated case → a reviewer disposition → scored
 * against a provably-independent answer key → a false-approve rate → a signed
 * attestation) using the same house vocabulary, `.rogue-card`, the
 * rogue-green/red/orange banding, Geist / Geist Mono, so it reads as a genuine
 * product screenshot, not a mockup. All data is illustrative and hard-coded;
 * the metric readouts are example numbers, not validated claims.
 *
 * Server component (no client interactivity). Drop into any marketing section;
 * responsive from ~600px to full width. Optional `className` for layout.
 */

// ── Example data, illustrative only, not a real review. ─────────────────────
const CASE = {
  id: "case_4b91c",
  kind: "large_wire",
  facts: [
    "USD 248,000 to a new beneficiary",
    "request arrived via email from a look-alike domain",
    "no out-of-band callback to confirm the payee",
  ],
  reviewer: "APPROVE" as const,
  answerKey: "DENY" as const,
};

// Headline product readout: an illustrative false-approve rate + bootstrap CI.
const FALSE_APPROVE = {
  pct: 22,
  ciLow: 12,
  ciHigh: 31,
  nFalse: 11,
  nReviewed: 50,
};

export function OversightPreview({ className }: { className?: string }) {
  const isFalseApprove =
    CASE.reviewer === "APPROVE" && CASE.answerKey === "DENY";

  return (
    <div
      className={cn(
        "w-full overflow-hidden rounded-xl border border-border bg-card/40 shadow-2xl shadow-black/40",
        className,
      )}
    >
      {/* ---- window chrome ---------------------------------------------- */}
      <div className="flex items-center gap-3 border-b border-border bg-rogue-bg-mid/80 px-4 py-2.5">
        <div className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-full bg-rogue-red/70" />
          <span className="h-3 w-3 rounded-full bg-rogue-orange/70" />
          <span className="h-3 w-3 rounded-full bg-rogue-green/70" />
        </div>
        <div className="min-w-0 flex-1 truncate text-center font-mono text-[10px] sm:text-[11px] text-muted-foreground">
          <span className="text-rogue-green">app.rogue</span>
          <span className="opacity-50"> · oversight / </span>
          <span className="text-foreground/80">human gate</span>
        </div>
        <span className="hidden shrink-0 items-center gap-1.5 rounded-md border border-rogue-green/30 bg-rogue-green/5 px-2 py-0.5 font-mono text-[9px] uppercase tracking-[0.15em] text-rogue-green/80 sm:inline-flex">
          Example case · illustrative
        </span>
      </div>

      {/* ---- panel body ------------------------------------------------- */}
      <div className="bg-rogue-bg-deep">
        <div className="space-y-5 p-4 sm:p-7">
          {/* header */}
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 space-y-1">
              <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
                ← /oversight/{CASE.id}
              </p>
              <h2 className="text-xl font-bold tracking-tight text-foreground sm:text-2xl">
                Is the sign-off meaningful?
              </h2>
              <p className="font-mono text-xs text-muted-foreground">
                gated action · {CASE.kind}
              </p>
            </div>
          </div>

          {/* headline metric: false-approve rate + bootstrap CI */}
          <section className="rogue-card space-y-3 rounded-lg border border-border bg-card/40 p-4 sm:p-6">
            <div className="flex flex-wrap items-end gap-4 sm:gap-5">
              <div className="flex items-baseline gap-2">
                <span className="text-5xl font-bold leading-none tabular-nums text-rogue-red">
                  {FALSE_APPROVE.pct}%
                </span>
              </div>
              <div className="space-y-1.5">
                <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted-foreground">
                  False-approve rate
                </p>
                <span className="inline-flex items-center rounded-md border border-rogue-red/40 bg-rogue-red/10 px-2 py-0.5 font-mono text-xs font-bold tabular-nums text-rogue-red">
                  [{FALSE_APPROVE.ciLow}–{FALSE_APPROVE.ciHigh}%] 95% CI
                </span>
              </div>
              <div className="ml-auto min-w-0 space-y-1 text-right">
                <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted-foreground">
                  Cases reviewed
                </p>
                <p className="font-mono text-sm font-bold tabular-nums text-foreground">
                  {FALSE_APPROVE.nFalse}/{FALSE_APPROVE.nReviewed} approved a DENY
                </p>
              </div>
            </div>
            <p className="border-t border-border pt-3 text-xs leading-relaxed text-muted-foreground">
              Headline metric. The share of escalated cases the reviewer waved
              through that the answer key marks DENY, bootstrap CI over a
              held-out case corpus. Scored against a provably-independent answer
              key.
            </p>
          </section>

          {/* the one gated case, facts strip + disposition vs answer key */}
          <section className="rogue-card space-y-3 rounded-lg border border-border bg-card/40 p-4 sm:p-6">
            <h3 className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
              Gated case · facts
            </h3>
            <ul className="space-y-2">
              {CASE.facts.map((fact, i) => (
                <li
                  key={i}
                  className="flex items-start gap-2.5 text-sm leading-relaxed text-foreground/90"
                >
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-rogue-orange/70" />
                  {fact}
                </li>
              ))}
            </ul>

            {/* disposition vs answer key */}
            <div className="grid grid-cols-1 gap-3 border-t border-border pt-4 sm:grid-cols-2">
              <div className="space-y-1.5 rounded-md border border-border bg-card/30 px-4 py-3">
                <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted-foreground">
                  Reviewer decision
                </p>
                <p className="font-mono text-lg font-bold tabular-nums text-orange-300">
                  {CASE.reviewer}
                </p>
              </div>
              <div className="space-y-1.5 rounded-md border border-rogue-green/30 bg-rogue-green/5 px-4 py-3">
                <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted-foreground">
                  Independent answer key
                </p>
                <p className="font-mono text-lg font-bold tabular-nums text-rogue-green">
                  {CASE.answerKey}
                </p>
              </div>
            </div>

            {isFalseApprove && (
              <div className="flex items-center gap-2.5 rounded-md border border-rogue-red/40 bg-rogue-red/10 px-3 py-2.5">
                <ShieldAlert
                  className="h-4 w-4 shrink-0 text-rogue-red"
                  aria-hidden
                />
                <p className="text-sm leading-relaxed text-foreground/90">
                  <span className="font-mono text-xs font-bold uppercase tracking-[0.15em] text-rogue-red">
                    False-approve
                  </span>{" "}
                  — the reviewer approved an action the answer key denies. Scored
                  against a provably-independent answer key.
                </p>
              </div>
            )}
          </section>

          {/* signed attestation badge + honest footnote */}
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card/30 p-4 sm:p-5">
            <span className="inline-flex items-center gap-2 rounded-md border border-rogue-green/40 bg-rogue-green/5 px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.15em] text-rogue-green">
              <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
              signed · tamper-evident attestation
              <Lock className="h-3 w-3 opacity-70" aria-hidden />
            </span>
            <span className="inline-flex items-center gap-1.5 font-mono text-[10px] text-muted-foreground">
              <KeyRound className="h-3 w-3 shrink-0" aria-hidden />
              threat-informed assurance, not a safety guarantee
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
