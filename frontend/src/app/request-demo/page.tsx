import type { Metadata } from "next";
import { ClipboardCheck, FileText, Radar, ShieldCheck } from "lucide-react";

import { RequestDemoForm } from "@/components/marketing/request-demo-form";

export const metadata: Metadata = {
  title: "Request a demo, ROGUE",
  description:
    "Book a ROGUE demo: a scoped red-team scan against your own model, system prompt, and tools, plus a walkthrough of the sample threat report you'd actually ship.",
};

/**
 * /request-demo, lead-capture landing page.
 *
 * Server component wrapper: hero + a left "what to expect" / trust column and
 * the client lead-capture form on the right (stacks on mobile). The form is the
 * only interactive part, isolated in <RequestDemoForm>.
 */

const EXPECT = [
  {
    icon: Radar,
    title: "A scoped scan of your stack",
    body: "We point ROGUE at your model × system prompt × tools and reproduce live open-web jailbreaks against that exact configuration.",
  },
  {
    icon: FileText,
    title: "A sample report walkthrough",
    body: "Walk through a real breach matrix and CISO-readable threat brief, the exact artifact ROGUE ships you daily.",
  },
  {
    icon: ShieldCheck,
    title: "The attacks that actually land",
    body: "See which families breach your config, with 95% confidence intervals and the verbatim prompt that cracked it.",
  },
  {
    icon: ClipboardCheck,
    title: "No commitment",
    body: "A 30-minute scoped session. If it isn't useful, you walk away with a free read on your exposure.",
  },
];

export default function RequestDemoPage() {
  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-7xl mx-auto px-6 py-16 md:py-24 space-y-12">
        {/* Hero ------------------------------------------------------- */}
        <header className="max-w-3xl space-y-4">
          <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
            request a demo
          </p>
          <h1 className="text-4xl md:text-5xl font-bold tracking-tight">
            See ROGUE break, and fix, your stack.
          </h1>
          <p className="text-base md:text-lg text-muted-foreground leading-relaxed">
            Tell us where your model lives and we&apos;ll run a scoped red-team
            scan against it, then walk you through a sample report so you can see
            exactly what lands, what holds, and what to fix first.
          </p>
        </header>

        {/* What to expect (left) + form (right) ---------------------- */}
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_minmax(0,36rem)] gap-10 lg:gap-16 items-start">
          <div className="space-y-6">
            <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
              what to expect
            </p>
            <ul className="space-y-5">
              {EXPECT.map(({ icon: Icon, title, body }) => (
                <li key={title} className="flex items-start gap-3">
                  <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg border border-rogue-green/30 bg-rogue-green/10">
                    <Icon className="size-4 text-rogue-green" />
                  </span>
                  <div className="space-y-1">
                    <p className="font-semibold tracking-tight">{title}</p>
                    <p className="text-sm text-muted-foreground leading-relaxed">
                      {body}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
            <p className="text-sm text-muted-foreground leading-relaxed border-t border-border pt-5">
              ROGUE continuously harvests jailbreaks and prompt-injections from
              19 open-web sources and reproduces them against real deployment
              configs, so you&apos;re tested against what attackers are sharing
              today, not a frozen benchmark.
            </p>
          </div>

          <RequestDemoForm />
        </div>
      </div>
    </main>
  );
}
