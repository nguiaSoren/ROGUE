"use client";

import ReactMarkdown from "react-markdown";

/**
 * Renders the threat-brief markdown with the ROGUE aesthetic:
 *  - H2/H3 sections get colored bars based on tier
 *  - Family/Vector/Severity lines are stylized as code-chip rows
 *  - CRITICAL severity gets a red glow
 *  - "Breached configs:" sub-lists get monospace + bullet tinting
 */
export function BriefMarkdown({ source }: { source: string }) {
  return (
    <div className="space-y-6 leading-relaxed">
      <ReactMarkdown
        components={{
          h1: ({ children }) => (
            <h1 className="text-3xl font-bold tracking-tight border-b border-border pb-3 mb-4">
              {children}
            </h1>
          ),
          h2: ({ children }) => {
            const text = String(children);
            const tint =
              /CRITICAL/i.test(text)
                ? "text-rogue-red border-rogue-red/40"
                : /HIGH/i.test(text)
                ? "text-orange-300 border-orange-500/40"
                : /MEDIUM/i.test(text)
                ? "text-yellow-300 border-yellow-500/40"
                : /LOW/i.test(text)
                ? "text-blue-300 border-blue-500/40"
                : "text-rogue-green border-rogue-green/40";
            return (
              <h2
                className={`text-2xl font-bold tracking-tight mt-10 mb-4 pl-4 border-l-2 ${tint}`}
              >
                {children}
              </h2>
            );
          },
          h3: ({ children }) => (
            <h3 className="text-lg font-semibold mt-6 mb-3 text-foreground">
              {children}
            </h3>
          ),
          ul: ({ children }) => (
            <ul className="space-y-1.5 my-3 pl-4 list-disc marker:text-rogue-green/60">
              {children}
            </ul>
          ),
          li: ({ children }) => {
            const text = String(children);
            // Lines like "- Severity: **CRITICAL** (score 1.000)"
            const isCriticalLine = /Severity:\s*\*?\*?CRITICAL/i.test(text);
            return (
              <li
                className={`text-sm leading-relaxed ${
                  isCriticalLine ? "text-rogue-red font-medium" : "text-foreground/90"
                }`}
              >
                {children}
              </li>
            );
          },
          code: ({ children }) => (
            <code className="px-1.5 py-0.5 rounded-sm bg-card/60 border border-border text-rogue-green font-mono text-[12px]">
              {children}
            </code>
          ),
          strong: ({ children }) => {
            const text = String(children);
            const tint =
              /CRITICAL/i.test(text) ? "text-rogue-red" :
              /HIGH/i.test(text) ? "text-orange-300" :
              /MEDIUM/i.test(text) ? "text-yellow-300" :
              /LOW/i.test(text) ? "text-blue-300" :
              "text-foreground";
            return <strong className={`font-bold ${tint}`}>{children}</strong>;
          },
          em: ({ children }) => (
            <em className="text-muted-foreground italic">{children}</em>
          ),
          p: ({ children }) => (
            <p className="text-sm leading-relaxed text-foreground/90 my-2">{children}</p>
          ),
          hr: () => <hr className="border-border my-6" />,
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}
