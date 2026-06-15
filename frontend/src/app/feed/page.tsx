import { api, API_CONFIGURED } from "@/lib/api";
import { FeedStream } from "@/components/feed-stream";
import { AugmentationStrip } from "@/components/augmentation-strip";
import { BanditWidget } from "@/components/bandit-widget";
import { CountUp } from "@/components/count-up";
import { EscalationWidget } from "@/components/escalation-widget";
import { MutationWidget } from "@/components/mutation-widget";
import { PersonaWidget } from "@/components/persona-widget";
import { StubbornnessWidget } from "@/components/stubbornness-widget";

// ISR, statically prerendered + revalidated every 5 min, matching /matrix and
// REVALIDATE_SECONDS in lib/api.ts, so visitors get instant loads and new Neon
// data surfaces within the window instead of paying the full round-trip.
// "auto" = ISR on Vercel; the self-host docker build rewrites it to "force-dynamic" (docker/frontend.Dockerfile).
export const dynamic = "auto";
export const revalidate = 300;

/**
 * /feed default export — ONE try/catch around the whole render so a missing API base in a preview
 * build (NEXT_PUBLIC_API_BASE is Production-scoped, hence unset in previews) can't fail the build.
 * Production rethrows on a real failure (keep the last-good static feed, never cache an empty one);
 * preview/local degrades to a placeholder so the preview build succeeds.
 */
export default async function FeedPage() {
  try {
    return await renderFeed();
  } catch (err) {
    if (API_CONFIGURED) throw err;
    return <FeedUnavailable />;
  }
}

function FeedUnavailable() {
  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-20 text-center space-y-3">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
          /feed · live
        </p>
        <h1 className="text-3xl font-bold tracking-tight">Live Feed</h1>
        <p className="text-sm text-muted-foreground max-w-md mx-auto">
          This preview build has no API connection; the live feed renders in production.
        </p>
      </div>
    </main>
  );
}

/**
 * /feed, Live Feed.
 *
 * Layout: 4-tile KPI strip, the §10.7 augmentation A/B summary strip, then
 * a 3-column "war room", sources/intel ribbon, attack list (expandable
 * rows with payload viewer + copy), augmentation sidebar (each widget now
 * carries a sparkline / bar chart).
 *
 * Spec: ROGUE_PLAN §11.1.
 */
async function renderFeed() {
  // `attacks` is the critical dataset (the feed list + KPIs). Fetch it WITHOUT
  // allSettled so a failure throws and propagates: Next + Vercel then keep
  // serving the last-good static feed instead of caching an empty one (an
  // allSettled-degraded empty render would otherwise be cached for the full ISR
  // window, the "feed is all empty" symptom). The 7 secondary widgets stay in
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

  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-10 space-y-8">
        {/* Header */}
        <header className="space-y-2 animate-rogue-fade-up">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green flex items-center gap-2">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-rogue-green animate-rogue-pulse-green" />
            /feed · live
          </p>
          <h1 className="text-3xl sm:text-4xl font-bold tracking-tight">Live Feed</h1>
          <p className="text-sm text-muted-foreground">
            Newest attack primitives surfaced from the open web.
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
          {/* LEFT intel ribbons + CENTER attack list, client-side so the time
              window (today / 7 days / all time) re-scopes without reloading. */}
          <FeedStream initialAttacks={attacks} />

          {/* RIGHT, augmentation sidebar */}
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
        {value !== null ? <CountUp value={value} /> : ", "}
      </p>
      <p className="text-xs text-muted-foreground mt-1">{sub}</p>
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
          <span className="tabular-nums">{health?.n_primitives ?? ", "}</span>
        </li>
        <li className="flex justify-between">
          <span className="text-muted-foreground">breaches</span>
          <span className="tabular-nums">{health?.n_breached ?? ", "}</span>
        </li>
      </ul>
    </div>
  );
}
