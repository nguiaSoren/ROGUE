import { ImageResponse } from "next/og";
import { LEADERBOARD_MODELS } from "@/lib/leaderboard-data";

/**
 * Dynamic OG card for /leaderboard (1200×630), brand-grounded:
 * background #050508, the breach-grid motif (a 3×3 cut, defended cells green,
 * one breached red), and the headline "MODELS RANKED BY RESISTANCE" + the
 * current most-resistant model pulled from the same matrix aggregate the page
 * reads. Self-contained: ImageResponse only supports flexbox + a CSS subset
 * (no `display:grid`), and we do NOT fetch Geist Mono at render — it falls back
 * to the runtime monospace, matching the `assets/brand/social/` card style.
 *
 * Mirrors the static `assets/brand/social/opengraph-image-LIVE-matrix-led`
 * direction. Degrades to a static headline if the API isn't reachable at
 * build/revalidate time.
 */
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const revalidate = 1800;

const GREEN = "#00ff88";
const RED = "#ff003c";
const BG = "#050508";

// 3×3 breach-grid motif: defended (green) cells + one breached (red) cell.
const GRID: ("green" | "red" | "dim")[] = [
  "green", "green", "dim",
  "green", "red", "green",
  "dim", "green", "green",
];

function topModel(): { label: string; rate: number } | null {
  if (LEADERBOARD_MODELS.length === 0) return null;
  return LEADERBOARD_MODELS.reduce<{ label: string; rate: number }>(
    (best, m) =>
      m.mean_breach_rate < best.rate ? { label: m.model_label, rate: m.mean_breach_rate } : best,
    { label: LEADERBOARD_MODELS[0].model_label, rate: LEADERBOARD_MODELS[0].mean_breach_rate },
  );
}

export default async function Image() {
  const best = topModel();

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: BG,
          backgroundImage:
            "radial-gradient(circle at 78% 22%, rgba(0,255,136,0.10), transparent 45%)",
          padding: "64px 72px",
          fontFamily: "monospace",
          color: "#e7e7ee",
        }}
      >
        {/* Top: wordmark + breach grid */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <div
              style={{
                fontSize: 26,
                letterSpacing: 8,
                color: GREEN,
                fontWeight: 700,
              }}
            >
              ROGUE
            </div>
            <div style={{ fontSize: 18, color: "#8b8b99", letterSpacing: 4, marginTop: 6 }}>
              /LEADERBOARD
            </div>
          </div>

          {/* breach-grid motif */}
          <div style={{ display: "flex", flexWrap: "wrap", width: 168, height: 168, gap: 8 }}>
            {GRID.map((cell, i) => (
              <div
                key={i}
                style={{
                  width: 48,
                  height: 48,
                  borderRadius: 6,
                  background:
                    cell === "red"
                      ? RED
                      : cell === "green"
                        ? "rgba(0,255,136,0.22)"
                        : "rgba(120,120,140,0.10)",
                  border:
                    cell === "red"
                      ? `2px solid ${RED}`
                      : cell === "green"
                        ? "2px solid rgba(0,255,136,0.5)"
                        : "1px solid rgba(120,120,140,0.25)",
                  boxShadow: cell === "red" ? `0 0 24px ${RED}` : "none",
                }}
              />
            ))}
          </div>
        </div>

        {/* Middle: headline */}
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: 68, fontWeight: 700, lineHeight: 1.05, letterSpacing: -1 }}>
            Models ranked by
          </div>
          <div style={{ fontSize: 68, fontWeight: 700, lineHeight: 1.05, letterSpacing: -1, color: GREEN }}>
            jailbreak resistance.
          </div>
          <div style={{ fontSize: 24, color: "#9a9aa8", marginTop: 22, maxWidth: 820 }}>
            Lower breach rate = higher rank. Scored by a calibrated judge against ROGUE&apos;s
            open-web attack corpus.
          </div>
        </div>

        {/* Bottom: current #1 + footer */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            {best ? (
              <>
                <div
                  style={{
                    display: "flex",
                    fontSize: 18,
                    color: GREEN,
                    border: `1px solid ${GREEN}`,
                    borderRadius: 6,
                    padding: "6px 12px",
                    letterSpacing: 2,
                  }}
                >
                  #1 MOST RESISTANT
                </div>
                <div style={{ display: "flex", fontSize: 22, color: "#e7e7ee" }}>
                  {`${best.label} · ${Math.round(best.rate * 100)}% breach`}
                </div>
              </>
            ) : (
              <div style={{ fontSize: 20, color: "#9a9aa8", letterSpacing: 2 }}>
                CONTINUOUS OPEN-WEB RED-TEAM
              </div>
            )}
          </div>
          <div style={{ fontSize: 18, color: "#6b6b78", letterSpacing: 2 }}>
            rogue-eosin.vercel.app
          </div>
        </div>
      </div>
    ),
    { ...size },
  );
}
