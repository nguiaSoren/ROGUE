import Link from "next/link";

import { Section } from "@/components/marketing/section";
import { ScanReplay } from "@/components/marketing/scan-replay";
import { McpConnect } from "@/components/marketing/mcp-connect";

export const metadata = {
  title: "Try ROGUE",
  description:
    "Watch ROGUE run a scan, no signup. A real recorded ROGUE scan against a demo target, replayed in your browser: attacks land on the ladder, breaches surface red, and a CISO-ready report builds.",
};

/**
 * /try, the public "test it right away" experience. A visitor clicks one button
 * and watches a REPLAY of a recorded ROGUE scan: attacks animate onto the
 * ladder, breaches settle red with the model's actual response, and the report
 * card builds. No auth (not under (app)/, so it is not gated), no live model
 * call, no network. The replay itself lives in the client <ScanReplay/>; this
 * server component is the page shell, metadata, and honest framing only.
 */
export default function TryPage() {
  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="space-y-16 md:space-y-20 py-20 md:py-28">
        {/* 1. HERO ----------------------------------------------------- */}
        <Section className="animate-rogue-fade-up">
          <div className="max-w-3xl space-y-6">
            <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
              try it now
            </p>
            <h1 className="text-3xl sm:text-4xl md:text-6xl font-bold tracking-tight leading-[1.05]">
              Watch ROGUE run a scan. No signup.
            </h1>
            <p className="text-base md:text-lg text-muted-foreground leading-relaxed max-w-2xl">
              Press one button and watch real open-web jailbreaks land on a demo
              target, the ones it refuses settle green, the ones that break
              surface red with the model&rsquo;s own words, and a CISO-ready
              report builds at the end.
            </p>
            <p className="text-sm text-muted-foreground leading-relaxed max-w-2xl border-l-2 border-border pl-4">
              A real recorded ROGUE scan against a demo target, replayed in your
              browser, not a live scan on your input. Want it on your own model
              &times; system-prompt?{" "}
              <Link
                href="/scan"
                className="text-rogue-green hover:underline underline-offset-4"
              >
                scan your own model — live, no install
              </Link>
              .
            </p>
          </div>
        </Section>

        {/* 2. THE REPLAY --------------------------------------------- */}
        <Section className="animate-rogue-fade-up">
          <ScanReplay className="mx-auto max-w-4xl" />
        </Section>

        {/* 3. CONNECT FOR REAL (live MCP, not a replay) -------------- */}
        <Section
          eyebrow="this one's live, not a replay"
          title="Or query the real threat DB from your own IDE."
          lede="The replay above is recorded. This is not, ROGUE&rsquo;s MCP server is live right now, read-only and keyless. Paste the config into Claude Desktop, Cursor, or Windsurf and ask it about the threats breaking models like yours. No signup, free."
          className="animate-rogue-fade-up"
        >
          <McpConnect className="mx-auto max-w-3xl" />
        </Section>

        {/* 4. CLOSING ------------------------------------------------ */}
        <Section className="animate-rogue-fade-up">
          <p className="text-[15px] text-muted-foreground leading-relaxed max-w-3xl mx-auto text-center">
            This was one recorded run. The same engine harvests live jailbreaks
            on a schedule and reproduces them in periodic measured runs, see the{" "}
            <Link
              href="/matrix"
              className="text-rogue-green hover:underline underline-offset-4"
            >
              live breach matrix
            </Link>{" "}
            and the{" "}
            <Link
              href="/feed"
              className="text-rogue-green hover:underline underline-offset-4"
            >
              threat feed
            </Link>
            , or{" "}
            <Link
              href="/sign-in"
              className="text-rogue-green hover:underline underline-offset-4"
            >
              request access
            </Link>{" "}
            to point it at your stack.
          </p>
        </Section>
      </div>
    </main>
  );
}
