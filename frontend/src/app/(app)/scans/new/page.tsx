"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import type { ScanSpec } from "@/lib/platform-api";

/**
 * Launch a scan. Posts a ScanSpec to /api/scans (which attaches the session key server-side and
 * forwards to POST /v1/scans), then routes to the live detail page. An Idempotency-Key guards against
 * a double-submit launching two paid scans.
 */
export default function NewScanPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"provider" | "endpoint">("provider");
  const [provider, setProvider] = useState("openai");
  const [endpoint, setEndpoint] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [scanMode, setScanMode] = useState<"pack" | "repertoire">("pack");
  const [pack, setPack] = useState("default");
  const [maxTests, setMaxTests] = useState(10);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const spec: ScanSpec = {
      target: {
        ...(mode === "provider" ? { provider } : { endpoint: endpoint.trim() }),
        model: model.trim() || null,
        api_key: apiKey.trim() || null,
      },
      mode: scanMode,
      pack,
      max_tests: maxTests,
    };
    try {
      const r = await fetch("/api/scans", {
        method: "POST",
        headers: { "content-type": "application/json", "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify(spec),
      });
      const body = (await r.json().catch(() => null)) as
        | { scan_id?: string; error?: { message?: string } }
        | null;
      if (r.ok && body?.scan_id) {
        router.push(`/scans/${body.scan_id}`);
        router.refresh();
        return;
      }
      setError(body?.error?.message ?? `Scan create failed (${r.status}).`);
    } catch {
      setError("Could not reach the server. Try again.");
    }
    setBusy(false);
  }

  const field = "w-full rounded border border-border bg-background px-3 py-2 text-sm outline-none focus:border-foreground/40";

  return (
    <div className="mx-auto w-full max-w-lg">
      <h1 className="text-xl font-semibold">New scan</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Point ROGUE at a model and pick an attack pack. Scans run asynchronously — you&apos;ll watch
        progress live on the next screen.
      </p>

      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        <div className="flex gap-2 text-sm">
          {(["provider", "endpoint"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`rounded border px-3 py-1 ${mode === m ? "border-foreground bg-muted" : "border-border text-muted-foreground"}`}
            >
              {m === "provider" ? "Known provider" : "Custom endpoint"}
            </button>
          ))}
        </div>

        {mode === "provider" ? (
          <label className="block text-sm">
            <span className="text-muted-foreground">Provider</span>
            <select value={provider} onChange={(e) => setProvider(e.target.value)} className={`${field} mt-1`}>
              {["openai", "anthropic", "openrouter", "groq", "gemini"].map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </label>
        ) : (
          <label className="block text-sm">
            <span className="text-muted-foreground">Endpoint (OpenAI-compatible base URL)</span>
            <input value={endpoint} onChange={(e) => setEndpoint(e.target.value)} placeholder="https://gateway.company.ai/v1" className={`${field} mt-1`} />
          </label>
        )}

        <label className="block text-sm">
          <span className="text-muted-foreground">Model {mode === "provider" ? "(optional — provider default)" : ""}</span>
          <input value={model} onChange={(e) => setModel(e.target.value)} placeholder={mode === "provider" ? "gpt-5.4-nano" : "model name"} className={`${field} mt-1`} />
        </label>

        <label className="block text-sm">
          <span className="text-muted-foreground">Target API key (optional — server key used if blank)</span>
          <input type="password" autoComplete="off" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-…" className={`${field} mt-1 font-mono`} />
        </label>

        <div>
          <span className="text-sm text-muted-foreground">Attack corpus</span>
          <div className="mt-1 flex gap-2 text-sm">
            {(
              [
                ["pack", "Curated pack"],
                ["repertoire", "Full repertoire"],
              ] as const
            ).map(([m, label]) => (
              <button
                key={m}
                type="button"
                onClick={() => setScanMode(m)}
                className={`rounded border px-3 py-1 ${scanMode === m ? "border-foreground bg-muted" : "border-border text-muted-foreground"}`}
              >
                {label}
              </button>
            ))}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            Full repertoire runs ROGUE&apos;s entire harvested corpus — more thorough, costs more.
          </p>
        </div>

        <div className="flex gap-4">
          <label className="block flex-1 text-sm">
            <span className="text-muted-foreground">Pack</span>
            <select
              value={pack}
              onChange={(e) => setPack(e.target.value)}
              disabled={scanMode === "repertoire"}
              className={`${field} mt-1 disabled:opacity-50`}
            >
              {["default", "aggressive", "compliance"].map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </label>
          <label className="block w-32 text-sm">
            <span className="text-muted-foreground">Max tests</span>
            <input type="number" min={1} max={1000} value={maxTests} onChange={(e) => setMaxTests(Math.max(1, Number(e.target.value) || 1))} className={`${field} mt-1`} />
          </label>
        </div>

        {error ? <p className="text-sm text-[var(--rogue-red,#ef4444)]">{error}</p> : null}

        <button
          type="submit"
          disabled={busy || (mode === "endpoint" && !endpoint.trim())}
          className="rounded bg-foreground px-4 py-2 text-sm font-medium text-background hover:opacity-90 disabled:opacity-50"
        >
          {busy ? "Launching…" : "Launch scan"}
        </button>
      </form>
    </div>
  );
}
