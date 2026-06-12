"use client"

import { useState } from "react"
import { Check, Copy, Terminal } from "lucide-react"
import { cn } from "@/lib/utils"

/**
 * McpConnect, a real, copy-pasteable connection card for ROGUE's LIVE MCP
 * server. Unlike <McpPreview/> (an illustrative scan session), everything here
 * is operational: the endpoint below is reachable right now, anonymously,
 * read-only, and free.
 *
 * HONESTY: the read tools (threat DB) are open + keyless. The action tools
 * (start_scan, file tickets) need an account, so the footer says so plainly.
 * Endpoint verified live: POST .../mcp → 200 text/event-stream, serverInfo
 * {name: "rogue"}. Config mirrors docs/mcp.md.
 *
 * Client component only for the clipboard buttons; no other state.
 */

const ENDPOINT = "https://rogue-private.onrender.com/mcp"

const CONFIG_JSON = `{
  "mcpServers": {
    "rogue": {
      "url": "${ENDPOINT}",
      "transport": "streamable-http"
    }
  }
}`

function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false)

  const copy = () => {
    navigator.clipboard?.writeText(value).then(
      () => {
        setCopied(true)
        window.setTimeout(() => setCopied(false), 1600)
      },
      () => {
        /* clipboard blocked, the text is still visible to select by hand */
      }
    )
  }

  return (
    <button
      type="button"
      onClick={copy}
      aria-label={copied ? `${label} copied` : `Copy ${label}`}
      className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-border bg-background/60 px-2.5 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground transition-colors hover:border-rogue-green/40 hover:text-rogue-green"
    >
      {copied ? (
        <>
          <Check className="size-3.5 text-rogue-green" aria-hidden="true" />
          copied
        </>
      ) : (
        <>
          <Copy className="size-3.5" aria-hidden="true" />
          copy
        </>
      )}
    </button>
  )
}

export function McpConnect({ className }: { className?: string }) {
  return (
    <figure
      className={cn(
        "rogue-card overflow-hidden rounded-xl border border-border bg-[#0a0a12] shadow-2xl shadow-black/40",
        className
      )}
    >
      {/* ── Window chrome ─────────────────────────────────────────── */}
      <div className="flex items-center gap-3 border-b border-border bg-[#07070b] px-4 py-2.5">
        <div className="flex items-center gap-1.5" aria-hidden="true">
          <span className="size-3 rounded-full bg-[#ff5f57]" />
          <span className="size-3 rounded-full bg-[#febc2e]" />
          <span className="size-3 rounded-full bg-[#28c840]" />
        </div>
        <div className="flex min-w-0 items-center gap-2 text-muted-foreground">
          <Terminal className="size-3.5 shrink-0" aria-hidden="true" />
          <span className="truncate font-mono text-[11px] sm:text-xs">
            claude_desktop_config.json
          </span>
        </div>
        <span className="ml-auto flex shrink-0 items-center gap-1.5 rounded-full border border-rogue-green/30 bg-rogue-green/5 px-2 py-0.5">
          <span className="size-1.5 animate-rogue-pulse-green rounded-full bg-rogue-green" />
          <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-rogue-green/90">
            live · keyless
          </span>
        </span>
      </div>

      {/* ── Body ──────────────────────────────────────────────────── */}
      <div className="space-y-5 px-4 py-5 sm:px-6">
        {/* Endpoint row */}
        <div className="space-y-2">
          <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            endpoint · read-only, no API key
          </p>
          <div className="flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded-md border border-border bg-[#07070b]/80 px-3 py-2 font-mono text-[12px] sm:text-[13px] text-rogue-green">
              {ENDPOINT}
            </code>
            <CopyButton value={ENDPOINT} label="endpoint" />
          </div>
        </div>

        {/* Config block */}
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
              paste into Claude Desktop · Cursor · Windsurf
            </p>
            <CopyButton value={CONFIG_JSON} label="config" />
          </div>
          <pre className="overflow-x-auto rounded-md border border-border bg-[#07070b]/80 px-3 py-3 font-mono text-[12px] leading-relaxed text-foreground">
            <code>{CONFIG_JSON}</code>
          </pre>
        </div>

        {/* What you can ask */}
        <div className="rounded-lg border border-rogue-green/20 bg-rogue-green/[0.04] px-4 py-3">
          <p className="text-sm leading-relaxed text-foreground">
            Then just ask, in your own words:
          </p>
          <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
            &ldquo;What are the worst jailbreaks for a model like me right now?&rdquo;
            &nbsp;·&nbsp; &ldquo;Anything new and critical today?&rdquo; &nbsp;·&nbsp;
            &ldquo;Show me the daily threat brief.&rdquo;
          </p>
          <p className="mt-2 font-mono text-[11px] text-muted-foreground/80">
            → ROGUE answers from its live breach matrix, real attacks harvested
            from the open web, judge-graded.
          </p>
        </div>
      </div>

      {/* ── Footer caption ────────────────────────────────────────── */}
      <figcaption className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-border bg-[#07070b] px-4 py-2.5 sm:px-6">
        <span className="size-1.5 rounded-full bg-rogue-green/60" aria-hidden="true" />
        <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-rogue-green/90">
          live now · no signup · free
        </span>
        <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">
          — read-only threat intel. Running scans needs an account.
        </span>
      </figcaption>
    </figure>
  )
}
