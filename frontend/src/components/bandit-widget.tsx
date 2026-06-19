import type { BanditStatsResponse } from "@/lib/api";
import { ExplainerHeader } from "@/components/explainer";
import { AUGMENTATION_COPY } from "@/components/augmentation-meta";

/**
 * §11.6 ε-greedy bandit sidebar tile on /feed.
 *
 * Extracted from the inline definition in feed/page.tsx so each arm row can
 * own its own hover-card with the full per-arm breakdown (pulls, novel,
 * cost, mean yield). Hover-card is pure CSS, no state, no client boundary.
 */
export function BanditWidget({
  bandit,
}: {
  bandit: BanditStatsResponse | null;
}) {
  return (
    <div className="rogue-card rogue-accent-bandit border border-border rounded-lg p-4 bg-card/40 backdrop-blur-sm space-y-3 rogue-scan-line">
      <ExplainerHeader
        accentTextClass="rogue-accent-bandit-text"
        eyebrow={AUGMENTATION_COPY.bandit.eyebrow}
        shortSubhead={AUGMENTATION_COPY.bandit.shortSubhead}
        whatItIs={AUGMENTATION_COPY.bandit.whatItIs}
        whyItMatters={AUGMENTATION_COPY.bandit.whyItMatters}
      />
      {bandit?.n_warm_arms ? (
        <>
          <div>
            <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground mb-1.5">
              top 3 arms · hover for detail
            </p>
            <ul className="space-y-1">
              {bandit.top_arms.map((a) => (
                <BanditRow key={a.arm_id} arm={a} tint="green" />
              ))}
            </ul>
          </div>
          {bandit.bottom_arms.length > 0 && (
            <div>
              <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground mb-1.5">
                bottom 3 arms · hover for detail
              </p>
              <ul className="space-y-1">
                {bandit.bottom_arms.map((a) => (
                  <BanditRow key={a.arm_id} arm={a} tint="muted" />
                ))}
              </ul>
            </div>
          )}
          <div className="pt-2 border-t border-border space-y-0.5">
            <p className="text-[10px] text-muted-foreground font-mono">
              {bandit.n_arms} arms · {bandit.n_warm_arms} warm
            </p>
            <p className="text-[10px] text-muted-foreground font-mono">
              {bandit.seeded_from_corpus_at
                ? `seeded ${bandit.seeded_from_corpus_at.slice(0, 10)}`
                : "no seed"}
              {" · "}
              {bandit.last_live_pulled_at
                ? `last live ${bandit.last_live_pulled_at.slice(0, 10)}`
                : "no live pulls"}
            </p>
          </div>
        </>
      ) : (
        <p className="text-xs font-mono text-muted-foreground">
          {`// ${bandit?.note ?? "no warm arms yet"}`}
        </p>
      )}
    </div>
  );
}

/**
 * Single arm row with a CSS-only hover-card. The hover-card opens below the
 * row (in-flow) so it never clips against the sidebar's right edge or
 * neighboring widgets.
 */
function BanditRow({
  arm,
  tint,
}: {
  arm: { arm_id: string; pulls: number; total_novel: number; total_cost_usd: number; mean_yield: number };
  tint: "green" | "muted";
}) {
  const isWarm = arm.pulls > 0;
  return (
    <li className="group relative">
      <div className="flex items-center justify-between text-xs font-mono cursor-default px-1 py-0.5 rounded-sm hover:bg-card/60 transition-colors">
        <span
          className={`truncate ${tint === "green" ? "text-foreground" : "text-muted-foreground"}`}
          title={arm.arm_id}
        >
          {arm.arm_id}
        </span>
        <span
          className={`tabular-nums ${tint === "green" ? "text-rogue-green" : "text-muted-foreground"}`}
        >
          {arm.mean_yield.toFixed(1)}/$
        </span>
      </div>

      {/* Hover-card, pure CSS, opens below the row. */}
      <div className="hidden group-hover:block absolute left-0 right-0 z-30 mt-1 p-3 rounded-md border border-rogue-green/40 bg-black/90 backdrop-blur-md shadow-[0_8px_32px_rgba(0,0,0,0.6)] space-y-2 animate-rogue-fade-up">
        <p
          className={`text-[10px] font-mono uppercase tracking-[0.18em] ${
            isWarm ? "text-rogue-green" : "text-muted-foreground"
          }`}
        >
          arm · {isWarm ? "warm" : "cold"}
        </p>
        <p className="text-[11px] font-mono text-foreground break-words">
          {arm.arm_id}
        </p>
        <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 pt-1 border-t border-border/50">
          <ArmStat label="pulls" value={arm.pulls.toString()} />
          <ArmStat label="novel found" value={arm.total_novel.toString()} />
          <ArmStat
            label="BD spend"
            value={`$${arm.total_cost_usd.toFixed(4)}`}
          />
          <ArmStat
            label="yield"
            value={`${arm.mean_yield.toFixed(2)} / $`}
            highlight
          />
        </div>
        <p className="text-[10px] text-muted-foreground/80 font-mono leading-snug pt-1 border-t border-border/50">
          {isWarm
            ? "// next pull biased by ε-greedy: 90% pick the hottest arm, 10% explore."
            : "// untested arm, guaranteed at least one cold-start pull before ε-greedy kicks in."}
        </p>
      </div>
    </li>
  );
}

function ArmStat({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div>
      <p className="text-[9px] font-mono uppercase tracking-wider text-muted-foreground/70">
        {label}
      </p>
      <p
        className={`text-xs font-mono tabular-nums ${
          highlight ? "text-rogue-green" : "text-foreground"
        }`}
      >
        {value}
      </p>
    </div>
  );
}
