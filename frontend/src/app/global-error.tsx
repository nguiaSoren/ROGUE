"use client"; // Error boundaries must be Client Components

/**
 * Root-layout error boundary. Catches errors thrown in the root layout itself
 * (which the per-segment `error.tsx` cannot wrap). It REPLACES the root layout
 * when active, so it must render its own <html>/<body> and cannot rely on the
 * Nav/Footer/fonts/theme provider, hence the inline dark styling that keeps it
 * on-brand without the global stylesheet guaranteed to be present.
 */
export default function GlobalError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: "#050508",
          color: "#e6e6e6",
          fontFamily:
            "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
        }}
      >
        <div style={{ maxWidth: 480, padding: "0 24px", textAlign: "center" }}>
          <p
            style={{
              fontSize: 11,
              letterSpacing: "0.25em",
              textTransform: "uppercase",
              color: "#ff003c",
              margin: 0,
            }}
          >
            {"// fatal fault"}
          </p>
          <h1
            style={{
              fontSize: 28,
              fontWeight: 700,
              margin: "16px 0 12px",
              color: "#ffffff",
            }}
          >
            ROGUE hit an unrecoverable error.
          </h1>
          <p style={{ color: "#9a9a9a", lineHeight: 1.6, margin: "0 0 24px" }}>
            The page failed to render. Try reloading, if it keeps happening, the
            service is likely mid-deploy.
          </p>
          {error.digest && (
            <p style={{ fontSize: 11, color: "#6a6a6a", margin: "0 0 16px" }}>
              ref: {error.digest}
            </p>
          )}
          <button
            type="button"
            onClick={() => unstable_retry()}
            style={{
              cursor: "pointer",
              padding: "12px 24px",
              borderRadius: 8,
              border: "none",
              backgroundColor: "#00ff88",
              color: "#050508",
              fontWeight: 700,
              fontSize: 13,
              letterSpacing: "0.15em",
              textTransform: "uppercase",
            }}
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
