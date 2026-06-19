import { CellView } from "@/components/cell-view";
import MODEL_CARDS from "@/data/model-cards.json";

/**
 * config → slug, inverted from the SAME `@/data/model-cards.json` the leaderboard and `/m/<slug>`
 * use, so a cell reached for a known model can surface that model's shareable breach card. Built
 * once at module load (the map is static + bundled).
 */
const CONFIG_TO_SLUG: Record<string, string> = Object.fromEntries(
  Object.entries(MODEL_CARDS as Record<string, { family: string; config: string }>).map(
    ([slug, entry]) => [entry.config, slug],
  ),
);

/**
 * The breach card for the model behind this cell — shown when the cell's config maps to a known
 * model. Closes the loop leaderboard → matrix → card: you drill in from the board and the model's
 * shareable card is right here, above the breaching-primitive list. Raw <img> (matches matrix-drawer).
 */
function ModelCardBanner({ slug }: { slug: string }) {
  const src = `/cards/${slug}.png`;
  return (
    <section className="rounded-lg border border-border bg-card/40 p-4 flex flex-col sm:flex-row items-start gap-4">
      <a
        href={src}
        target="_blank"
        rel="noopener noreferrer"
        className="block shrink-0 overflow-hidden rounded-md border border-border transition-colors hover:border-rogue-green/60"
        title="Open the full-size breach card"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={src}
          alt={`${slug} breach card`}
          width={1200}
          height={630}
          loading="lazy"
          className="h-auto w-[320px] max-w-full"
        />
      </a>
      <div className="space-y-1.5 min-w-0">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">breach card</p>
        <p className="text-sm text-muted-foreground leading-relaxed">
          The shareable breach card for this model — the same numbers as the breaching primitives
          below.
        </p>
        <a
          href={src}
          download
          className="inline-flex items-center gap-2 rounded-md border border-rogue-green/50 px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.15em] text-rogue-green transition-colors hover:bg-rogue-green/10"
        >
          ↓ download card
        </a>
      </div>
    </section>
  );
}

/**
 * /matrix/cell?family=&config=&date=, every breaching primitive in one
 * (family × config) cell.
 *
 * The matrix grid collapses a cell to its single worst-offending primitive;
 * this page expands it into the full list (>0% any-breach, worst-first), each
 * card in the same format as the cell drawer. Reached from the drawer's
 * "see all breaching primitives in this cell →" link and the /matrix
 * "worst attacker today" callout.
 *
 * This is a dynamic route (reads ?family/config/date), so it deliberately does
 * NO server-side API fetch, a transient Render cold-cycle would otherwise
 * render a hard "502 / cell unavailable" with no recovery. The data is fetched
 * client-side by `CellView` (retry + timeout + a "waking up, retry" state), so
 * the page shell renders instantly and an API blip retries instead of erroring.
 */
export default async function CellPage({
  searchParams,
}: {
  searchParams: Promise<{
    family?: string;
    config?: string;
    date?: string;
    scope?: string;
    attacker?: string;
    from?: string;
  }>;
}) {
  const { family, config, date, scope, attacker, from } = await searchParams;
  const initialScope = scope === "all-time" ? "all-time" : "this-run";
  const initialAttacker = attacker === "augmented" ? "augmented" : "baseline";
  const cardSlug = config ? CONFIG_TO_SLUG[config] : undefined;

  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 py-10 space-y-4">
        {!family || !config ? (
          <div className="border border-rogue-red/40 rounded-lg p-6 font-mono text-sm text-rogue-red bg-rogue-red/5">
            {"// missing ?family= and ?config= query params"}
          </div>
        ) : (
          <>
            {cardSlug && <ModelCardBanner slug={cardSlug} />}
            <CellView
              family={family}
              config={config}
              date={date}
              initialScope={initialScope}
              initialAttacker={initialAttacker}
              from={from}
            />
          </>
        )}
      </div>
    </main>
  );
}
