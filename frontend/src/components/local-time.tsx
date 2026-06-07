"use client";

/**
 * Render an ISO-8601 timestamp in the VIEWER's local timezone.
 *
 * This must be a client component. The dashboard pages are server-rendered on Render (a US-hosted
 * box), so formatting a date on the server would show the *server's* timezone, not the viewer's, 
 * which is why a user in Korea saw US time. Formatting here runs in the browser, so every viewer
 * sees their own local time (KST in Seoul, etc.). `suppressHydrationWarning` tolerates the expected
 * server-vs-client text difference; the client-rendered (correct) value is what the user ends up
 * seeing. The `title` attribute carries the full local timestamp for hover.
 */
export function LocalTime({
  iso,
  options = { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" },
}: {
  iso: string | null | undefined;
  options?: Intl.DateTimeFormatOptions;
}) {
  if (!iso) return <>, </>;
  const ms = Date.parse(iso);
  if (!Number.isFinite(ms)) return <>, </>;
  return (
    <span suppressHydrationWarning title={new Date(ms).toLocaleString()}>
      {new Date(ms).toLocaleString(undefined, options)}
    </span>
  );
}
