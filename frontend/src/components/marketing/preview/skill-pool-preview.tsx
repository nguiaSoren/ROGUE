import { ShieldCheck, ShieldAlert, Lock, KeyRound } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * SkillPoolPreview, a pixel-faithful, NON-functional native preview of ROGUE's
 * skill-pool audit panel (the v2 Surface-3 idea), framed in a faux app-window
 * for the marketing site. It mirrors the real shared-skill-pool red-team in
 * `src/rogue/memory/` (leakage of planted canaries, verified promotion before a
 * skill spreads, combination-risk quarantine of dangerous co-invocations, a
 * signed pool attestation) using the same house vocabulary, `.rogue-card`, the
 * rogue-green/red/orange banding, Geist / Geist Mono, so it reads as a genuine
 * product screenshot, not a mockup. All data is illustrative and hard-coded;
 * the metric readouts are example numbers, not validated claims.
 *
 * Server component (no client interactivity). Drop into any marketing section;
 * responsive from ~600px to full width. Optional `className` for layout.
 */

type SkillStatus = "active" | "quarantined" | "candidate";

const STATUS_CLASS: Record<SkillStatus, string> = {
  active: "border-rogue-green/40 bg-rogue-green/10 text-rogue-green",
  quarantined: "border-rogue-red/40 bg-rogue-red/10 text-rogue-red",
  candidate: "border-border bg-card/30 text-muted-foreground",
};

const STATUS_LABEL: Record<SkillStatus, string> = {
  active: "active · verified",
  quarantined: "quarantined",
  candidate: "candidate",
};

interface Skill {
  name: string;
  status: SkillStatus;
  /** Tiny note shown after the skill name. */
  note: string;
}

// ── Example data, illustrative only, not a real pool. ───────────────────────
const SKILLS: Skill[] = [
  { name: "secure-code-review", status: "active", note: "promoted, 18/18 trials" },
  { name: "rotating-proxy-scraper", status: "active", note: "promoted, lift confirmed" },
  { name: "pii-redactor", status: "quarantined", note: "dangerous co-invocation" },
  { name: "auto-shell-runner", status: "candidate", note: "no measured lift yet" },
  { name: "doc-summarizer", status: "candidate", note: "awaiting re-verification" },
];

const READOUTS = {
  leakage: { canaries: 17, total: 20, controlFp: 0 },
  promotion: { earned: 1, of: 4 },
  combinationQuarantined: 1,
};

export function SkillPoolPreview({ className }: { className?: string }) {
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
          <span className="opacity-50"> · skill pool / </span>
          <span className="text-foreground/80">audit</span>
        </div>
        <span className="hidden shrink-0 items-center gap-1.5 rounded-md border border-rogue-green/30 bg-rogue-green/5 px-2 py-0.5 font-mono text-[9px] uppercase tracking-[0.15em] text-rogue-green/80 sm:inline-flex">
          Example pool · illustrative
        </span>
      </div>

      {/* ---- panel body ------------------------------------------------- */}
      <div className="bg-rogue-bg-deep">
        <div className="space-y-5 p-4 sm:p-7">
          {/* header */}
          <div className="min-w-0 space-y-1">
            <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
              ← /skill-pool/audit
            </p>
            <h2 className="text-xl font-bold tracking-tight text-foreground sm:text-2xl">
              Audit the skill pool before it spreads.
            </h2>
            <p className="font-mono text-xs text-muted-foreground">
              {SKILLS.length} skills · shared agent-skill pool
            </p>
          </div>

          {/* three readouts */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Readout
              label="Extraction leakage"
              value={`${READOUTS.leakage.canaries}/${READOUTS.leakage.total}`}
              suffix="canaries"
              note={`${READOUTS.leakage.controlFp} control FP`}
              tint="text-rogue-red"
            />
            <Readout
              label="Verified promotion"
              value={`${READOUTS.promotion.earned} of ${READOUTS.promotion.of}`}
              suffix="skills"
              note="earn promotion"
            />
            <Readout
              label="Combination risk"
              value={String(READOUTS.combinationQuarantined)}
              suffix="quarantined"
              note="neighborhood flagged"
              tint="text-rogue-red"
            />
          </div>

          {/* skill list with status badges */}
          <section className="rogue-card space-y-3 rounded-lg border border-border bg-card/40 p-4 sm:p-6">
            <h3 className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
              Pool · skills
            </h3>
            <ul className="space-y-2">
              {SKILLS.map((s) => (
                <li
                  key={s.name}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border/60 bg-card/20 px-3 py-2.5"
                >
                  <div className="flex min-w-0 items-center gap-2">
                    {s.status === "quarantined" ? (
                      <ShieldAlert
                        className="h-3.5 w-3.5 shrink-0 text-rogue-red"
                        aria-hidden
                      />
                    ) : (
                      <ShieldCheck
                        className={cn(
                          "h-3.5 w-3.5 shrink-0",
                          s.status === "active"
                            ? "text-rogue-green"
                            : "text-muted-foreground",
                        )}
                        aria-hidden
                      />
                    )}
                    <code className="truncate font-mono text-xs text-foreground sm:text-[13px]">
                      {s.name}
                    </code>
                    <span className="hidden truncate font-mono text-[10px] text-muted-foreground sm:inline">
                      {s.note}
                    </span>
                  </div>
                  <span
                    className={cn(
                      "shrink-0 rounded-md border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.15em]",
                      STATUS_CLASS[s.status],
                    )}
                  >
                    {STATUS_LABEL[s.status]}
                  </span>
                </li>
              ))}
            </ul>
          </section>

          {/* signed attestation badge + honest footnote */}
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card/30 p-4 sm:p-5">
            <span className="inline-flex items-center gap-2 rounded-md border border-rogue-green/40 bg-rogue-green/5 px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.15em] text-rogue-green">
              <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
              signed · pool attestation
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

function Readout({
  label,
  value,
  suffix,
  note,
  tint,
}: {
  label: string;
  value: string;
  suffix: string;
  note: string;
  tint?: string;
}) {
  return (
    <div className="space-y-1.5 rounded-md border border-border bg-card/30 px-4 py-3">
      <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted-foreground">
        {label}
      </p>
      <p className="flex items-baseline gap-1.5">
        <span className={cn("text-2xl font-bold tabular-nums", tint)}>
          {value}
        </span>
        <span className="font-mono text-[11px] text-muted-foreground">
          {suffix}
        </span>
      </p>
      <p className="font-mono text-[10px] text-muted-foreground">{note}</p>
    </div>
  );
}
