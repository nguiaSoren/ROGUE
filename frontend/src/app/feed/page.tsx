import { api } from "@/lib/api";
import { AttackRow } from "@/components/attack-row";
import { AugmentationStrip } from "@/components/augmentation-strip";
import { BanditWidget } from "@/components/bandit-widget";
import { CountUp } from "@/components/count-up";
import { EscalationWidget } from "@/components/escalation-widget";
import { MutationWidget } from "@/components/mutation-widget";
import { PersonaWidget } from "@/components/persona-widget";
import { StubbornnessWidget } from "@/components/stubbornness-widget";

/**
 * /feed — Live Feed.
 *
 * Layout: 4-tile KPI strip, the §10.7 augmentation A/B summary strip, then
 * a 3-column "war room" — sources/intel ribbon, attack list (expandable
 * rows with payload viewer + copy), augmentation sidebar (each widget now
 * carries a sparkline / bar chart).
 *
 * Spec: ROGUE_PLAN §11.1.
 */
export default async function FeedPage() {
  // `attacks` is the critical dataset (the feed list + KPIs). Fetch it WITHOUT
  // allSettled so a failure throws and propagates: Next + Vercel then keep
  // serving the last-good static feed instead of caching an empty one (an
  // allSettled-degraded empty render would otherwise be cached for the full ISR
  // window — the "feed is all empty" symptom). The 7 secondary widgets stay in
  // allSettled and degrade to null individually.
  const [attacks, secondary] = await Promise.all([
    api.attacks({ since_days: 7, limit: 50 }),
    Promise.allSettled([
      api.health(),
      api.banditStats(),
      api.brief(undefined, "json"),
      api.personaStats(),
      api.escalationStats(),
      api.mutationStats(),
      api.stubbornnessStats(),
    ]),
  ]);

  const [
    healthResult,
    banditResult,
    briefResult,
    personaResult,
    escalationResult,
    mutationResult,
    stubbornnessResult,
  ] = secondary;

  const health = healthResult.status === "fulfilled" ? healthResult.value : null;
  const bandit = banditResult.status === "fulfilled" ? banditResult.value : null;
  const brief = briefResult.status === "fulfilled" ? briefResult.value : null;
  const persona = personaResult.status === "fulfilled" ? personaResult.value : null;
  const escalation =
    escalationResult.status === "fulfilled" ? escalationResult.value : null;
  const mutation =
    mutationResult.status === "fulfilled" ? mutationResult.value : null;
  const stubbornness =
    stubbornnessResult.status === "fulfilled"
      ? stubbornnessResult.value
      : null;

  const briefSummary = (brief?.json as { summary?: Record<string, number> })?.summary;
  const newBreachesToday =
    (briefSummary?.new_critical ?? 0) + (briefSummary?.new_high ?? 0);

  // Family histogram for the left ribbon — "what's hot today" at a glance.
  const familyCounts: { family: string; n: number }[] = [];
  if (attacks?.attacks) {
    const m = new Map<string, number>();
    for (const a of attacks.attacks) {
      m.set(a.family, (m.get(a.family) ?? 0) + 1);
    }
    Array.from(m.entries())
      .sort(([, a], [, b]) => b - a)
      .slice(0, 8)
      .forEach(([family, n]) => familyCounts.push({ family, n }));
  }

  // Bright Data product histogram — which product surfaced the most.
  const productCounts: { product: string; n: number }[] = [];
  if (attacks?.attacks) {
    const m = new Map<string, number>();
    for (const a of attacks.attacks) {
      const p = a.sources?.[0]?.bright_data_product;
      if (p) m.set(p, (m.get(p) ?? 0) + 1);
    }
    Array.from(m.entries())
      .sort(([, a], [, b]) => b - a)
      .forEach(([product, n]) => productCounts.push({ product, n }));
  }

  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-7xl mx-auto px-6 py-10 space-y-8">
        {/* Header */}
        <header className="space-y-2 animate-rogue-fade-up">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green flex items-center gap-2">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-rogue-green animate-rogue-pulse-green" />
            /feed · live
          </p>
          <h1 className="text-4xl font-bold tracking-tight">Live Feed</h1>
          <p className="text-sm text-muted-foreground">
            Newest attack primitives surfaced from the open web — last 7 days.
          </p>
        </header>

        {/* KPI strip */}
        <section
          className="grid grid-cols-2 lg:grid-cols-4 gap-3 animate-rogue-fade-up"
          style={{ animationDelay: "0.1s" }}
        >
          <KpiTile
            label="Attacks (7d)"
            value={attacks?.count ?? null}
            sub="harvested + extracted"
            tint="green"
          />
          <KpiTile
            label="New breaches today"
            value={newBreachesToday}
            sub="CRITICAL + HIGH tier"
            tint="red"
            highlight={newBreachesToday > 0}
          />
          <KpiTile
            label="Configs tested"
            value={health?.n_configs ?? null}
            sub="model × system prompt"
            tint="green"
          />
          <KpiTile
            label="Total breach trials"
            value={health?.n_breaches ?? null}
            sub="across all primitives"
            tint="green"
          />
        </section>

        {/* §10.7 augmentation strip */}
        <AugmentationStrip
          persona={persona}
          escalation={escalation}
          mutation={mutation}
          stubbornness={stubbornness}
        />

        {/* 3-column war room */}
        <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr_300px] gap-6">
          {/* LEFT — intel ribbon: families + products distribution */}
          <aside className="space-y-4 lg:order-1">
            <IntelRibbon
              title="hot families · 7d"
              data={familyCounts.map((f) => ({ label: f.family, value: f.n }))}
              accent="var(--rogue-green)"
              empty="no recent attacks"
            />
            <IntelRibbon
              title="by Bright Data product"
              data={productCounts.map((p) => ({ label: p.product, value: p.n }))}
              accent="#22d3ee"
              empty="no provenance yet"
            />
          </aside>

          {/* CENTER — attack list */}
          <section className="space-y-2 lg:order-2 min-w-0">
            <div className="flex items-baseline justify-between">
              <h2 className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                newest attacks — click row to expand
              </h2>
              <p className="font-mono text-[10px] text-muted-foreground">
                {attacks?.attacks?.length ?? 0} shown
              </p>
            </div>
            {attacks?.attacks?.length ? (
              <ul className="space-y-2">
                {attacks.attacks.map((a, i) => (
                  <AttackRow key={a.primitive_id} attack={a} index={i} />
                ))}
              </ul>
            ) : (
              <div className="border border-border rounded-lg p-6 font-mono text-sm text-muted-foreground">
                {"// no attacks in last 7d. Run scripts/harvest_once.py to seed."}
              </div>
            )}
          </section>

          {/* RIGHT — augmentation sidebar */}
          <aside className="space-y-4 lg:order-3">
            <BanditWidget bandit={bandit} />
            <PersonaWidget persona={persona} />
            <EscalationWidget escalation={escalation} />
            <MutationWidget mutation={mutation} />
            <StubbornnessWidget stubbornness={stubbornness} />
            <SystemStatusWidget health={health} />
          </aside>
        </div>
      </div>
    </main>
  );
}

// ---------------------------------------------------------------------------

function KpiTile({
  label,
  value,
  sub,
  tint,
  highlight = false,
}: {
  label: string;
  value: number | null;
  sub: string;
  tint: "green" | "red";
  highlight?: boolean;
}) {
  const tintClass = tint === "green" ? "text-rogue-green" : "text-rogue-red";
  const cardClass = highlight
    ? "rogue-card rogue-card-critical animate-rogue-pulse-critical"
    : "rogue-card";
  return (
    <div className={`${cardClass} border border-border rounded-lg p-4 bg-card/40 backdrop-blur-sm`}>
      <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground">
        {label}
      </p>
      <p className={`text-3xl font-bold mt-2 tabular-nums ${tintClass}`}>
        {value !== null ? <CountUp value={value} /> : "—"}
      </p>
      <p className="text-xs text-muted-foreground mt-1">{sub}</p>
    </div>
  );
}

function IntelRibbon({
  title,
  data,
  accent,
  empty,
}: {
  title: string;
  data: { label: string; value: number }[];
  accent: string;
  empty: string;
}) {
  const peak = data.length > 0 ? Math.max(...data.map((d) => d.value)) : 1;
  return (
    <div className="rogue-card border border-border rounded-lg p-4 bg-card/40 backdrop-blur-sm space-y-3">
      <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground">
        {title}
      </p>
      {data.length === 0 ? (
        <p className="text-[11px] font-mono text-muted-foreground">
          {`// ${empty}`}
        </p>
      ) : (
        <ul className="space-y-1.5">
          {data.map((d) => {
            const pct = (d.value / peak) * 100;
            return (
              <li
                key={d.label}
                className="text-[11px] font-mono space-y-0.5"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span
                    className="truncate text-foreground"
                    title={d.label}
                  >
                    {d.label}
                  </span>
                  <span className="tabular-nums text-muted-foreground">
                    {d.value}
                  </span>
                </div>
                <span className="block h-1 bg-card/60 rounded-sm overflow-hidden">
                  <span
                    className="block h-full rounded-sm transition-all duration-700 ease-out"
                    style={{
                      width: `${pct}%`,
                      background: accent,
                      boxShadow: `0 0 6px ${accent}88`,
                    }}
                  />
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function SystemStatusWidget({
  health,
}: {
  health: Awaited<ReturnType<typeof api.health>> | null;
}) {
  return (
    <div className="rogue-card border border-border rounded-lg p-4 bg-card/40 backdrop-blur-sm space-y-2">
      <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground">
        system
      </p>
      <ul className="space-y-1.5 text-xs font-mono">
        <li className="flex justify-between items-center">
          <span className="text-muted-foreground">db</span>
          <span
            className={`flex items-center gap-1.5 ${
              health?.db === "up" ? "text-rogue-green" : "text-rogue-red"
            }`}
          >
            <span
              className={`inline-block w-1.5 h-1.5 rounded-full ${
                health?.db === "up" ? "bg-rogue-green animate-rogue-pulse-green" : "bg-rogue-red"
              }`}
            />
            {health?.db ?? "unknown"}
          </span>
        </li>
        <li className="flex justify-between">
          <span className="text-muted-foreground">primitives</span>
          <span className="tabular-nums">{health?.n_primitives ?? "—"}</span>
        </li>
        <li className="flex justify-between">
          <span className="text-muted-foreground">breaches</span>
          <span className="tabular-nums">{health?.n_breaches ?? "—"}</span>
        </li>
      </ul>
    </div>
  );
}
