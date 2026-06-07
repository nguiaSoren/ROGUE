"use client";

import { useState } from "react";

/**
 * "Connect via MCP", one-click install buttons for the hosted ROGUE MCP server.
 *
 * The server is mounted into the API at `<api-base>/mcp` (streamable-http), so
 * there's nothing to download or clone: clients connect to a URL.
 *  - "Add to Cursor" / "Add to VS Code" fire the IDE's MCP-install deeplink.
 *  - "Copy URL" is the universal fallback, paste into Claude Desktop's custom
 *    connector or any MCP client.
 */
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
// Trailing slash: the server is mounted at /mcp, so the endpoint is /mcp/, 
// using it directly avoids a 307 redirect that some MCP clients won't follow.
const MCP_URL = `${API_BASE}/mcp/`;

// Cursor deeplink: base64 of the server config {url}. VS Code: url-encoded
// {type,url}. Both open the IDE and prompt to add the `rogue` server.
const cursorHref = `cursor://anysphere.cursor-deeplink/mcp/install?name=rogue&config=${
  typeof window !== "undefined"
    ? window.btoa(JSON.stringify({ url: MCP_URL }))
    : ""
}`;
const vscodeHref = `vscode:mcp/install?${encodeURIComponent(
  JSON.stringify({ name: "rogue", type: "http", url: MCP_URL }),
)}`;

export function McpConnect() {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(MCP_URL);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard blocked, user can still read the URL below */
    }
  };

  return (
    <div className="rogue-card border border-border rounded-xl p-5 bg-card/40 backdrop-blur-sm space-y-4">
      <div className="flex flex-wrap items-center gap-2.5">
        <a
          href={cursorHref}
          className="inline-flex items-center gap-2 px-3.5 py-2 rounded-md border border-rogue-green/40 bg-rogue-green/10 text-rogue-green font-mono text-xs uppercase tracking-wider hover:bg-rogue-green/20 transition-colors"
        >
          + Add to Cursor
        </a>
        <a
          href={vscodeHref}
          className="inline-flex items-center gap-2 px-3.5 py-2 rounded-md border border-border bg-card/60 font-mono text-xs uppercase tracking-wider hover:border-rogue-green hover:text-rogue-green transition-colors"
        >
          + Add to VS Code
        </a>
        <button
          type="button"
          onClick={copy}
          className="inline-flex items-center gap-2 px-3.5 py-2 rounded-md border border-border bg-card/60 font-mono text-xs uppercase tracking-wider hover:border-rogue-green hover:text-rogue-green transition-colors"
        >
          {copied ? "✓ copied" : "Copy MCP URL"}
        </button>
      </div>

      <div className="font-mono text-[11px] text-muted-foreground break-all">
        <span className="text-rogue-green">{MCP_URL}</span>
      </div>

      <p className="text-xs text-muted-foreground leading-relaxed">
        <span className="text-foreground">Claude Desktop:</span> Settings →
        Connectors → Add custom connector → paste the URL above.{" "}
        <span className="text-foreground">Cursor / VS Code:</span> click the
        button, your editor opens and offers to add the{" "}
        <code className="text-rogue-green">rogue</code> server. No clone, no
        Python, no JSON editing, it&apos;s a hosted, read-only MCP server with
        5 query tools.
      </p>
    </div>
  );
}
