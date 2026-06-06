import {
  Check,
  Loader2,
  Sparkles,
  Terminal,
  Ticket,
  User,
  Wrench,
} from "lucide-react"
import { cn } from "@/lib/utils"

/**
 * McpPreview — a pixel-faithful, static "screenshot" of ROGUE's MCP server
 * driving a full red-team consult from INSIDE an AI IDE (Cursor / Claude
 * Desktop). This is the signature differentiator: ROGUE is an MCP *producer*,
 * so a security engineer runs validate → scan → poll → findings → file-tickets
 * without ever leaving the editor.
 *
 * Server component. No state, no effects, no client JS — it's an illustrative
 * frozen session. Every tool name shown is a REAL v1 MCP tool
 * (`src/rogue/mcp_server/scan_tools.py` + `docs/mcp.md`).
 */

type ToolState = "done" | "running"

interface ToolCall {
  /** Real MCP tool name (monospace). */
  name: string
  /** Tiny args echo, shown after the tool name in the call line. */
  args?: string
  /** One-line result digest under the call. */
  result: string
  state: ToolState
  /** Use the ticket glyph instead of the generic wrench (for create_jira_ticket). */
  icon?: "wrench" | "ticket"
}

/** A single MCP tool-invocation card — mono name, args echo, result line, state pip. */
function ToolCallCard({ call }: { call: ToolCall }) {
  const Glyph = call.icon === "ticket" ? Ticket : Wrench
  const running = call.state === "running"
  return (
    <div
      className={cn(
        "rounded-lg border bg-[#07070b]/80 px-3 py-2.5",
        running ? "border-rogue-green/40" : "border-border"
      )}
    >
      <div className="flex items-center gap-2">
        <Glyph
          className="mt-0.5 size-3.5 shrink-0 self-start text-rogue-green/70"
          aria-hidden="true"
        />
        <code className="min-w-0 flex-1 break-words font-mono text-[12px] sm:text-[13px] leading-tight text-foreground">
          <span className="text-rogue-green">{call.name}</span>
          {call.args !== undefined && (
            <span className="text-muted-foreground">({call.args})</span>
          )}
        </code>
        <span className="mt-0.5 flex shrink-0 items-center gap-1.5 self-start">
          {running ? (
            <>
              <Loader2
                className="size-3.5 animate-spin text-rogue-green"
                aria-hidden="true"
              />
              <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-rogue-green/80">
                running
              </span>
            </>
          ) : (
            <Check
              className="size-3.5 text-rogue-green"
              aria-label="completed"
            />
          )}
        </span>
      </div>
      <div className="mt-1.5 break-words pl-[22px] font-mono text-[11.5px] leading-relaxed text-muted-foreground">
        <span className="select-none text-rogue-green/50">← </span>
        {call.result}
      </div>
    </div>
  )
}

/** The scripted, illustrative tool-call sequence — mirrors docs/mcp.md flow (b). */
const TOOL_CALLS: ToolCall[] = [
  {
    name: "validate_target",
    args: 'endpoint="staging-api…/v1"',
    result: "{ reachable: true, authenticated: true, ok: true }",
    state: "done",
  },
  {
    name: "start_scan",
    args: 'pack="default", mode="ladder", max_tests=150',
    result: '{ scan_id: "scan_8f3a2", status: "queued" }',
    state: "done",
  },
  {
    name: "get_scan_status",
    args: '"scan_8f3a2"',
    result: '{ status: "running", progress: 68% } → polling…',
    state: "running",
  },
  {
    name: "list_findings",
    args: '"scan_8f3a2"',
    result: "11 breaches across 142 trials · 2 critical, 4 high",
    state: "done",
  },
  {
    name: "create_jira_ticket",
    args: 'integration="jira-prod"',
    result: '{ created: ["SEC-412", "SEC-413"], skipped: [] }',
    state: "done",
    icon: "ticket",
  },
]

export interface McpPreviewProps {
  className?: string
}

/**
 * The faux-IDE MCP session. Drop into a marketing section; responsive from
 * full-width down to ~600px (single column throughout).
 */
export function McpPreview({ className }: McpPreviewProps) {
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
          <span className="truncate font-mono text-[11px] sm:text-xs">Cursor — rogue-mcp</span>
        </div>
        <span className="ml-auto flex shrink-0 items-center gap-1.5 rounded-full border border-rogue-green/30 bg-rogue-green/5 px-2 py-0.5">
          <span className="size-1.5 animate-rogue-pulse-green rounded-full bg-rogue-green" />
          <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-rogue-green/90">
            MCP · rogue
          </span>
        </span>
      </div>

      {/* ── Conversation body ─────────────────────────────────────── */}
      <div className="space-y-5 px-4 py-5 sm:px-6">
        {/* 1 — User prompt */}
        <div className="flex gap-3">
          <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md border border-border bg-card/60 text-muted-foreground">
            <User className="size-3.5" aria-hidden="true" />
          </span>
          <p className="pt-0.5 text-sm leading-relaxed text-foreground">
            Scan my staging endpoint for jailbreaks and file the criticals to
            Jira.
          </p>
        </div>

        {/* 2 — Assistant: narration + tool-call cards */}
        <div className="flex gap-3">
          <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md border border-rogue-green/40 bg-rogue-green/10 text-rogue-green">
            <Sparkles className="size-3.5" aria-hidden="true" />
          </span>
          <div className="min-w-0 flex-1 space-y-3">
            <p className="pt-0.5 text-sm leading-relaxed text-muted-foreground">
              On it. I&apos;ll validate the target, run a ladder-mode red-team
              through ROGUE&apos;s MCP server, then file Jira tickets for the
              critical findings.
            </p>

            <div className="space-y-2">
              {TOOL_CALLS.map((call) => (
                <ToolCallCard key={call.name} call={call} />
              ))}
            </div>
          </div>
        </div>

        {/* 3 — Assistant final summary */}
        <div className="flex gap-3">
          <span
            className="mt-0.5 flex size-6 shrink-0 items-center justify-center"
            aria-hidden="true"
          />
          <div className="min-w-0 flex-1 rounded-lg border border-rogue-green/20 bg-rogue-green/[0.04] px-4 py-3">
            <p className="text-sm leading-relaxed text-foreground">
              <span className="font-medium text-rogue-green">
                Scan complete
              </span>{" "}
              — 142 trials, 11 breaches{" "}
              <span className="font-mono text-rogue-green">(7.7%)</span>. Top
              risk:{" "}
              <span className="font-medium">Crescendo</span>{" "}
              <span className="font-mono text-rogue-red">(CRITICAL, 4/5)</span>.
              Filed{" "}
              <span className="font-medium">2 Jira tickets</span> for the
              criticals; full report at{" "}
              <code className="font-mono text-[12px] text-rogue-green/90">
                app.rogue/scans/scan_8f3a2/report
              </code>
              .
            </p>
          </div>
        </div>
      </div>

      {/* ── Footer caption ────────────────────────────────────────── */}
      <figcaption className="flex items-center gap-2 border-t border-border bg-[#07070b] px-4 py-2 sm:px-6">
        <span className="size-1.5 rounded-full bg-rogue-green/50" aria-hidden="true" />
        <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          Illustrative MCP session — ROGUE is the MCP server
        </span>
      </figcaption>
    </figure>
  )
}
