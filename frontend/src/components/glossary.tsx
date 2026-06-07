"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Central glossary + the <Term> hover/click reveal component.
 *
 * Every acronym or jargon word in user-facing copy should be wrapped in
 * <Term>...</Term> so a visitor can hover (desktop) or tap (mobile) to see
 * the expansion + a plain-English explanation. Goal: a non-technical CISO
 * can read every line of the dashboard without bouncing on a single term.
 *
 * Lookup is case-sensitive against the visible text. If the text differs
 * from the key (e.g., a stylized variant), pass the key via the `name`
 * prop: <Term name="PAIR">PAIR-driven</Term>.
 */
export type GlossaryEntry = {
  expansion: string;
  plain: string;
};

export const GLOSSARY: Record<string, GlossaryEntry> = {
  PAIR: {
    expansion: "Prompt Automatic Iterative Refinement",
    plain:
      "A separate attacker LLM reads each refusal and rewrites the prompt up to N times until breach or give-up. Measures how stubbornly your defense holds against an adaptive attacker, not a single shot.",
  },
  PAP: {
    expansion: "Persuasive Adversarial Prompt",
    plain:
      'Wraps a refused prompt in a persuasion frame, "logical appeal," "authority," "compliance officer." Tests whether your guardrails react to tone or to underlying intent.',
  },
  AutoDAN: {
    expansion: "Automatic DAN-style attack generator",
    plain:
      'Rewords a defended attack into semantically identical variants. If a config blocks the original wording but breaches on a paraphrase, the defense was pattern-matching the string, not understanding the request.',
  },
  mutation: {
    expansion: "Surface mutation",
    plain:
      "Take an attack the model just blocked, reword it into a different-looking but identical-meaning version, and try again. If the reworded one slips through, the model was filtering on keywords, not understanding what was actually being asked.",
  },
  MCP: {
    expansion: "Model Context Protocol",
    plain:
      "Anthropic's open standard for connecting AI assistants to tools and data. ROGUE both consumes MCP (via Bright Data's MCP server) and exposes its own MCP server that Claude Desktop can query directly.",
  },
  SERP: {
    expansion: "Search Engine Results Page",
    plain:
      "What you see when you Google something. Bright Data's SERP API returns those results as structured JSON. ROGUE uses it to discover new attack-discussion URLs across the open web.",
  },
  LLM: {
    expansion: "Large Language Model",
    plain:
      "AI like ChatGPT, Claude, or Llama. The thing under attack in every cell of this dashboard.",
  },
  CISO: {
    expansion: "Chief Information Security Officer",
    plain:
      "The executive who gets paged at 3 AM if your LLM leaks customer data. The threat brief is written for them.",
  },
  Δ: {
    expansion: "Delta (Greek letter for 'change')",
    plain:
      'In "+15pp Δ", breach rate jumped by 15 percentage points after the stress test was applied vs the baseline.',
  },
  pp: {
    expansion: "Percentage points",
    plain:
      "If breach rate goes from 40% to 55%, that's +15 percentage points, NOT +15%. +15% would be a relative jump from 40% to 46%, much smaller.",
  },
  CI: {
    expansion: "Confidence Interval",
    plain:
      '"60% [95% CI: 50–70%]" means we ran enough trials to be 95% confident the true rate is between 50% and 70%. Wider interval = less certainty; we report both honestly.',
  },
  "ε-greedy": {
    expansion: "Epsilon-greedy algorithm",
    plain:
      "90% of the time, pick the strategy you've found works best (greedy). 10% of the time, try something random (epsilon = chance of exploration). Keeps you from getting stuck on stale winners.",
  },
  SSE: {
    expansion: "Server-Sent Events",
    plain:
      "A browser standard that lets the server push updates to the page without you refreshing. Powers the live attack ticker.",
  },
  Crescendo: {
    expansion: "Crescendo multi-turn attack",
    plain:
      "Microsoft Research technique: instead of asking the harmful thing in turn 1, warm up over 3 turns and slip it in at turn 3. Models often comply because each turn alone looks innocent.",
  },
  "A/B": {
    expansion: "A/B test",
    plain:
      "Compare two variants under the same conditions. Here: same attack with a stress-test applied (B) vs the original (A), so any breach-rate difference is attributable to the stress test alone.",
  },
  primitive: {
    expansion: "Attack primitive",
    plain:
      "One distinct jailbreak technique, deduplicated across all the variations people posted. The atomic unit ROGUE tracks.",
  },
  vector: {
    expansion: "Attack vector",
    plain:
      'The mechanism the attack exploits, "roleplay framing," "system-prompt injection," "tool poisoning," etc.',
  },
  family: {
    expansion: "Attack family",
    plain:
      "One of 14 high-level categories ROGUE buckets attacks into: jailbreak, prompt injection, exfiltration, agentic-tool-abuse, weight abliteration, and so on.",
  },
  "deployment config": {
    expansion: "Deployment configuration",
    plain:
      'A model + system prompt + tool set combination. "GPT-4o helpful chatbot" and "Llama-3 internal coding assistant" are different deployment configs. ROGUE tests every attack against all of them.',
  },
  bandit: {
    expansion: "Multi-armed bandit",
    plain:
      "Classic decision-making algorithm. Each 'arm' is one strategy ROGUE could try; the bandit pulls higher-yield arms more often, lower-yield arms less. Online learning, gets smarter every day without retraining.",
  },
};

/**
 * Term, wraps a glossary word with a dotted-underline trigger.
 * Hover (desktop) reveals; click pins; click outside dismisses.
 */
export function Term({
  name,
  children,
}: {
  name?: string;
  children: React.ReactNode;
}) {
  const key =
    name ?? (typeof children === "string" ? children.trim() : "");
  const def = GLOSSARY[key];
  const [pinned, setPinned] = useState(false);
  const [hovering, setHovering] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!pinned) return;
    const handle = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setPinned(false);
      }
    };
    window.addEventListener("click", handle);
    return () => window.removeEventListener("click", handle);
  }, [pinned]);

  if (!def) {
    // Soft fallback, render children as-is, never throw.
    return <>{children}</>;
  }

  const open = pinned || hovering;

  return (
    <span
      ref={ref}
      className="relative inline"
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
    >
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setPinned((p) => !p);
        }}
        className={`inline border-b border-dotted cursor-help transition-colors px-0.5 ${
          open
            ? "border-rogue-green text-rogue-green"
            : "border-rogue-green/50 hover:border-rogue-green hover:text-rogue-green"
        }`}
        aria-label={`Definition of ${key}`}
        aria-expanded={open}
      >
        {children}
        <span
          className={`align-super text-[0.62em] ml-0.5 leading-none transition-colors ${
            open ? "text-rogue-green" : "text-rogue-green/70"
          }`}
          aria-hidden
        >
          ⓘ
        </span>
      </button>
      <span
        role="tooltip"
        className={`absolute left-0 top-full z-50 mt-0.5 w-72 p-3 rounded-md border border-rogue-green/40 bg-black/95 backdrop-blur-md shadow-[0_8px_32px_rgba(0,0,0,0.6)] text-left transition-opacity duration-150 pointer-events-none ${
          open ? "opacity-100" : "opacity-0"
        }`}
      >
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green mb-1">
          {key}
        </p>
        <p className="text-xs font-semibold text-foreground mb-1.5">
          {def.expansion}
        </p>
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          {def.plain}
        </p>
      </span>
    </span>
  );
}
