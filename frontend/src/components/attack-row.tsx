"use client";

import { useEffect, useRef, useState } from "react";
import type { AttackPrimitive } from "@/lib/api";
import { AttackReplay } from "@/components/attack-replay";

/**
 * Expandable attack-feed row.
 *
 * Collapsed (default): severity badge · title · family/vector · source link.
 * Expanded (click): payload template preview, all sources, multi-turn /
 * tool / system-prompt requirement chips, copy-payload button.
 *
 * The expand interaction is the "wow, the actual prompt that broke this"
 * moment — turns the feed from a list of headlines into a forensics tool.
 */
export function AttackRow({
  attack,
  index,
}: {
  attack: AttackPrimitive;
  index: number;
}) {
  const [open, setOpen] = useState(false);
  const [replayKey, setReplayKey] = useState<number | null>(null);
  const sev = (attack.base_severity || "medium").toLowerCase();
  const sevConfig =
    {
      critical: {
        badge:
          "text-red-300 border-rogue-red bg-rogue-red/15 animate-rogue-pulse-critical",
        cardExtra: "rogue-card-critical",
      },
      high: {
        badge: "text-orange-300 border-orange-500/60 bg-orange-500/15",
        cardExtra: "",
      },
      medium: {
        badge: "text-yellow-300 border-yellow-500/50 bg-yellow-500/10",
        cardExtra: "",
      },
      low: {
        badge: "text-blue-300 border-blue-500/40 bg-blue-500/10",
        cardExtra: "",
      },
    }[sev] || { badge: "text-muted-foreground border-border", cardExtra: "" };

  const primarySource = attack.sources?.[0];
  const stagger = Math.min(index * 0.04, 0.6);

  return (
    <li
      id={`a-${attack.primitive_id}`}
      className={`rogue-card ${sevConfig.cardExtra} animate-rogue-fade-up border border-border rounded-lg bg-card/40 backdrop-blur-sm overflow-hidden transition-colors`}
      style={{ animationDelay: `${stagger}s` }}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full text-left p-4 cursor-pointer hover:bg-card/60 transition-colors"
        aria-expanded={open}
      >
        <div className="flex items-start gap-3">
          <span
            className={`text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 border rounded-sm ${sevConfig.badge} flex-shrink-0 mt-0.5`}
          >
            {attack.base_severity}
          </span>
          <div className="flex-1 min-w-0 space-y-1.5">
            <p className="font-medium leading-tight" title={attack.title}>
              {attack.title}
            </p>
            <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed">
              {attack.short_description}
            </p>
            <div className="flex items-center gap-3 text-[11px] font-mono text-muted-foreground flex-wrap">
              <span>
                family: <span className="text-foreground">{attack.family}</span>
              </span>
              <span>
                vector: <span className="text-foreground">{attack.vector}</span>
              </span>
              {primarySource?.bright_data_product && (
                <span className="text-[10px] px-1.5 py-0.5 border border-rogue-green/40 text-rogue-green rounded-sm uppercase tracking-wider">
                  {primarySource.bright_data_product}
                </span>
              )}
              {attack.requires_multi_turn && (
                <span className="text-[10px] px-1.5 py-0.5 border border-amber-500/40 text-amber-300 rounded-sm uppercase tracking-wider">
                  multi-turn
                </span>
              )}
              {attack.requires_tools?.length > 0 && (
                <span className="text-[10px] px-1.5 py-0.5 border border-cyan-500/40 text-cyan-300 rounded-sm uppercase tracking-wider">
                  tools: {attack.requires_tools.length}
                </span>
              )}
            </div>
          </div>
          <span
            className={`text-muted-foreground font-mono text-xs flex-shrink-0 transition-transform ${
              open ? "rotate-90 text-rogue-green" : ""
            }`}
            aria-hidden
          >
            ▸
          </span>
        </div>
      </button>

      {open && (
        <div className="border-t border-border bg-background/40 px-4 py-3 space-y-3 animate-rogue-fade-up">
          {attack.payload_template ? (
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-rogue-green">
                  payload_template
                </p>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setReplayKey(Date.now());
                    }}
                    className="text-[10px] font-mono uppercase tracking-wider text-rogue-green hover:bg-rogue-green/10 transition-colors px-2 py-0.5 border border-rogue-green/40 rounded-sm flex items-center gap-1"
                    title="Watch the attack play out: attacker → model → judge"
                  >
                    ▶ {replayKey !== null ? "replay" : "play"}
                  </button>
                  <CopyButton text={attack.payload_template} />
                </div>
              </div>
              {replayKey !== null ? (
                <AttackReplay key={replayKey} attack={attack} />
              ) : (
                <pre className="text-[11px] font-mono leading-relaxed text-foreground/85 bg-card/60 rounded-md p-3 max-h-64 overflow-y-auto whitespace-pre-wrap break-words border border-border/40">
                  {attack.payload_template}
                </pre>
              )}
            </div>
          ) : (
            <p className="text-[11px] font-mono text-muted-foreground">
              {"// no payload template (cluster head pending)"}
            </p>
          )}

          {attack.sources && attack.sources.length > 0 && (
            <div>
              <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground mb-1.5">
                sources ({attack.sources.length})
              </p>
              <ul className="space-y-1">
                {attack.sources.map((s) => (
                  <li key={s.url} className="text-[11px] font-mono">
                    <a
                      href={s.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-rogue-green hover:underline truncate inline-block max-w-full"
                      title={s.url}
                    >
                      {s.url} ↗
                    </a>
                    {s.author && (
                      <span className="text-muted-foreground ml-2">
                        · {s.author}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex items-center gap-3 text-[10px] font-mono text-muted-foreground pt-1">
            <span>id: {attack.primitive_id.slice(0, 8)}</span>
            {attack.reproducibility_score !== null && (
              <span>
                repro: {(attack.reproducibility_score * 100).toFixed(0)}%
              </span>
            )}
            {attack.cluster_id && (
              <span>cluster: {attack.cluster_id.slice(0, 8)}</span>
            )}
            {attack.canonical && (
              <span className="text-rogue-green">★ canonical</span>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<number | null>(null);
  useEffect(() => {
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    };
  }, []);
  return (
    <button
      type="button"
      onClick={async (e) => {
        e.stopPropagation();
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          if (timerRef.current !== null) window.clearTimeout(timerRef.current);
          timerRef.current = window.setTimeout(() => setCopied(false), 1500);
        } catch {
          /* swallow */
        }
      }}
      className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground hover:text-rogue-green transition-colors px-2 py-0.5 border border-border rounded-sm"
    >
      {copied ? "copied ✓" : "copy"}
    </button>
  );
}
