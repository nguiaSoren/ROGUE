"use client";

import ReactMarkdown from "react-markdown";

/**
 * Renders the scan report's `executive_summary` markdown as a clean, prose-first
 * block, the "forward-to-your-boss" overview. Unlike `BriefMarkdown` (which is
 * tuned to the threat-brief's CRITICAL/HIGH section vocabulary), this is tuned for
 * a short narrative: readable headings, paragraphs, lists, and inline emphasis,
 * with no severity-keyword tinting that would misfire on plain English.
 */
export function ReportSummaryMarkdown({ source }: { source: string }) {
  return (
    <div className="space-y-3 leading-relaxed">
      <ReactMarkdown
        components={{
          h1: ({ children }) => (
            <h3 className="text-lg font-bold tracking-tight text-foreground mt-4 mb-2">
              {children}
            </h3>
          ),
          h2: ({ children }) => (
            <h3 className="text-base font-bold tracking-tight text-foreground mt-4 mb-2">
              {children}
            </h3>
          ),
          h3: ({ children }) => (
            <h4 className="text-sm font-semibold text-foreground mt-3 mb-1.5">
              {children}
            </h4>
          ),
          p: ({ children }) => (
            <p className="text-sm leading-relaxed text-foreground/90">{children}</p>
          ),
          ul: ({ children }) => (
            <ul className="space-y-1.5 my-2 pl-5 list-disc marker:text-rogue-green/60">
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol className="space-y-1.5 my-2 pl-5 list-decimal marker:text-rogue-green/60">
              {children}
            </ol>
          ),
          li: ({ children }) => (
            <li className="text-sm leading-relaxed text-foreground/90">{children}</li>
          ),
          strong: ({ children }) => (
            <strong className="font-bold text-foreground">{children}</strong>
          ),
          em: ({ children }) => (
            <em className="italic text-muted-foreground">{children}</em>
          ),
          code: ({ children }) => (
            <code className="px-1.5 py-0.5 rounded-sm bg-card/60 border border-border text-rogue-green font-mono text-[12px]">
              {children}
            </code>
          ),
          a: ({ href, children }) => (
            <a
              href={href}
              className="text-rogue-green underline underline-offset-2 hover:opacity-80"
            >
              {children}
            </a>
          ),
          hr: () => <hr className="border-border my-4" />,
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}
