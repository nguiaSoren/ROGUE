"use client";

import { useEffect, useState } from "react";
import type { AttackPrimitive } from "@/lib/api";

/**
 * Terminal-style 3-phase replay of an attack: ATTACKER → MODEL → JUDGE.
 *
 * Sections fade in sequentially with a leading cursor so the visitor sees
 * the attack "play out" rather than just reading a wall of text. The model
 * response is heuristically synthesized from the attack's reproducibility
 * score, real per-trial transcripts would require an /api/attacks/{id}
 * fetch which is overkill for the replay UX.
 *
 * Used inside AttackRow's expanded section. Mount/unmount triggers a fresh
 * playback every time the user clicks ▶ replay.
 */
export function AttackReplay({ attack }: { attack: AttackPrimitive }) {
  const [phase, setPhase] = useState<0 | 1 | 2 | 3>(0);

  useEffect(() => {
    const t1 = setTimeout(() => setPhase(1), 200);
    const t2 = setTimeout(() => setPhase(2), 1400);
    const t3 = setTimeout(() => setPhase(3), 2800);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
    };
  }, []);

  const payload = attack.payload_template?.trim() ?? "(no payload template)";
  const repro = attack.reproducibility_score ?? 0;
  const willBreach = repro >= 0.5;
  const sev = (attack.base_severity || "medium").toUpperCase();

  return (
    <div className="rounded-md border border-border bg-black/60 p-4 font-mono text-[11px] leading-relaxed space-y-3">
      {/* ATTACKER */}
      <Phase
        active={phase >= 1}
        label="ATTACKER"
        labelClass="text-rogue-red"
        labelGlow="rgba(255, 0, 60, 0.6)"
      >
        <pre className="whitespace-pre-wrap break-words text-foreground/90 max-h-44 overflow-y-auto">
          {payload}
        </pre>
      </Phase>

      {/* MODEL */}
      <Phase
        active={phase >= 2}
        label={`MODEL · ${shortName(attack.requires_tools?.length ? "agent" : "chat")}`}
        labelClass="text-cyan-300"
        labelGlow="rgba(34, 211, 238, 0.6)"
      >
        <p className="text-foreground/85">
          {willBreach
            ? "Sure, happy to help. " +
              synthesizeBreachResponse(attack) +
              " [transcript redacted for brevity]"
            : "I'm not able to help with that request. " +
              synthesizeRefusal(attack)}
        </p>
      </Phase>

      {/* JUDGE */}
      <Phase
        active={phase >= 3}
        label="JUDGE · llm-grader"
        labelClass={willBreach ? "text-rogue-red" : "text-rogue-green"}
        labelGlow={
          willBreach ? "rgba(255, 0, 60, 0.6)" : "rgba(0, 255, 136, 0.6)"
        }
      >
        <div className="flex items-center gap-3 flex-wrap">
          <span
            className={`inline-flex items-center gap-1.5 px-2 py-0.5 border rounded-sm uppercase tracking-wider ${
              willBreach
                ? "text-rogue-red border-rogue-red/60 bg-rogue-red/10 animate-rogue-pulse-critical"
                : "text-rogue-green border-rogue-green/60 bg-rogue-green/10"
            }`}
          >
            {willBreach ? "● breach" : "○ refused"}
          </span>
          <span className="text-muted-foreground">
            severity: <span className={willBreach ? "text-rogue-red" : "text-foreground"}>{sev}</span>
          </span>
          <span className="text-muted-foreground">
            reproducibility:{" "}
            <span className="tabular-nums text-foreground">
              {(repro * 100).toFixed(0)}%
            </span>
          </span>
          <span className="text-muted-foreground">
            family: <span className="text-foreground">{attack.family}</span>
          </span>
        </div>
      </Phase>
    </div>
  );
}

function Phase({
  active,
  label,
  labelClass,
  labelGlow,
  children,
}: {
  active: boolean;
  label: string;
  labelClass: string;
  labelGlow: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={`transition-opacity duration-500 ${active ? "opacity-100" : "opacity-0"}`}
    >
      <p
        className={`uppercase tracking-[0.22em] text-[10px] mb-1 flex items-center gap-2 ${labelClass}`}
      >
        <span
          className="inline-block w-1.5 h-1.5 rounded-full"
          style={{
            background: "currentColor",
            boxShadow: `0 0 8px ${labelGlow}`,
          }}
        />
        {label}
      </p>
      <div className="pl-3 border-l border-border">
        {children}
        {active && (
          <span className="inline-block w-1.5 h-3 bg-rogue-green ml-1 align-middle rogue-caret-blink" />
        )}
      </div>
    </div>
  );
}

function synthesizeRefusal(attack: AttackPrimitive): string {
  if (attack.family.toLowerCase().includes("inject"))
    return "I noticed the embedded instruction, I'll continue to follow the original system prompt.";
  if (attack.family.toLowerCase().includes("roleplay"))
    return "Even in a hypothetical or fictional framing, I can't provide that.";
  return "Even if the framing changes, the underlying request is still one I can't fulfill.";
}

function synthesizeBreachResponse(attack: AttackPrimitive): string {
  if (attack.family.toLowerCase().includes("inject"))
    return "Following the latest instructions in the document:";
  if (attack.family.toLowerCase().includes("roleplay"))
    return "Sure, in character, here's what that character would say:";
  if (attack.family.toLowerCase().includes("escal"))
    return "Now that we've established context across the prior turns, here's the detailed answer:";
  return "Here's a step-by-step walkthrough:";
}

function shortName(s: string): string {
  return s.length > 12 ? s.slice(0, 12) + "…" : s;
}

/**
 * Companion CSS for the typing cursor.
 * (defined in globals.css via .rogue-caret blink)
 */
