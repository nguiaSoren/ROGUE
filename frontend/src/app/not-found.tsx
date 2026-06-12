import Link from "next/link";

/**
 * Custom 404. Renders for any unmatched URL and for explicit `notFound()` calls
 * (e.g. the permanently non-commercial /security route). Server component, in
 * the site's dark terminal aesthetic, inside the normal Nav/Footer chrome.
 */
export const metadata = {
  title: "404, ROGUE",
  description: "The page you are looking for does not exist.",
};

export default function NotFound() {
  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-2xl mx-auto px-6 py-24 md:py-32 text-center space-y-6">
        <p className="font-mono text-[11px] uppercase tracking-[0.25em] text-rogue-green">
          {"// 404 · no route"}
        </p>
        <h1 className="text-5xl md:text-6xl font-bold tracking-tight">404</h1>
        <p className="text-[17px] text-foreground leading-relaxed">
          That page isn&apos;t here. It may have moved, or never existed. The
          threat DB, breach matrix, and daily brief are all one click away.
        </p>
        <div className="flex flex-col sm:flex-row gap-3 justify-center items-center pt-2">
          <Link
            href="/"
            className="inline-flex items-center justify-center rounded-lg px-6 py-3 bg-rogue-green text-black font-mono text-sm font-bold tracking-[0.15em] uppercase transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rogue-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            Back to home
          </Link>
          <div className="flex gap-x-5 font-mono text-xs uppercase tracking-[0.15em] text-muted-foreground">
            <Link href="/feed" className="transition-colors hover:text-rogue-green">
              /feed
            </Link>
            <Link href="/matrix" className="transition-colors hover:text-rogue-green">
              /matrix
            </Link>
            <Link href="/brief" className="transition-colors hover:text-rogue-green">
              /brief
            </Link>
          </div>
        </div>
      </div>
    </main>
  );
}
