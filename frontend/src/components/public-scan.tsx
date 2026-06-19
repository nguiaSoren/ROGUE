"use client";

import { useRef, useState } from "react";
import { Loader2, ShieldAlert } from "lucide-react";

import { FieldLabel } from "@/components/marketing/section";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { track } from "@/lib/analytics";
import { cn } from "@/lib/utils";

/**
 * Public, zero-install self-serve red-team for /scan.
 *
 * Client component. Collects a visitor's OWN model endpoint + key, POSTs them to
 * the Wave backend (`POST {API_BASE}/api/public-scan`), and swaps itself for an
 * inline shareable breach card on success. On any failure it surfaces the
 * server's `detail` string in a red box and keeps the entered values so the
 * visitor can retry.
 *
 * The API base is resolved the same way `src/lib/api.ts` and the demo form do,
 * from `NEXT_PUBLIC_API_BASE` (defaulting to localhost:8000), rather than
 * hardcoded — so it tracks whatever the dashboard pages already talk to.
 */

// Mirror `src/lib/api.ts` / request-demo-form: same env var, same localhost
// fallback. apiGet is GET-only + ISR-cached so it isn't reusable for this POST;
// we reuse its base-URL contract instead.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

// A live ATTACKER → MODEL → JUDGE scan against an arbitrary endpoint can run a
// while (Render cold-boot + several primitives + the target's own latency). Cap
// it generously so a real scan completes, but still bail rather than hang the UI
// forever — the server-side 504 is the authoritative timeout; this is the client
// guard behind it.
const SCAN_TIMEOUT_MS = 120_000;
// If still in flight after this, reassure the visitor it's a live scan, not a hang.
const SLOW_HINT_MS = 8_000;

// The leaderboard is the public landing target for a shared breach card.
const SHARE_URL = "https://rogue-eosin.vercel.app/leaderboard";

const PACKS = [
  { value: "default", label: "Default — a small bounded probe" },
  { value: "aggressive", label: "Aggressive — broader jailbreak pack" },
] as const;
type Pack = (typeof PACKS)[number]["value"];

type Status = "idle" | "submitting" | "success" | "error";

/** Judge mode the server graded with. */
type Judge = "keyless" | "calibrated-v3";

/** POST /api/public-scan request body. */
interface ScanRequest {
  endpoint: string;
  model: string;
  api_key: string;
  judge_key?: string;
  system_prompt?: string;
  pack: Pack;
}

/** POST /api/public-scan 200 summary block. */
interface ScanSummary {
  model_label: string;
  breached: number;
  trials: number;
  rate: number;
  judge: Judge;
}

/** POST /api/public-scan 200 response. */
interface ScanResponse {
  card_png_base64: string;
  card_svg: string;
  summary: ScanSummary;
}

const ctaButton = cn(
  "inline-flex items-center justify-center gap-2 rounded-lg px-6 py-3 w-full",
  "bg-rogue-green text-black font-mono text-sm font-bold tracking-[0.15em] uppercase",
  "transition-opacity hover:opacity-90",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rogue-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background",
  "disabled:cursor-not-allowed disabled:opacity-60",
);

const secondaryButton = cn(
  "inline-flex items-center gap-2 rounded-md border px-4 py-2",
  "font-mono text-xs uppercase tracking-[0.15em]",
  "transition-colors",
);

export function PublicScan() {
  const [status, setStatus] = useState<Status>("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [showSlowHint, setShowSlowHint] = useState(false);
  const [result, setResult] = useState<ScanResponse | null>(null);

  const slowTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const submitting = status === "submitting";

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (submitting) return;

    const form = e.currentTarget;
    const data = new FormData(form);
    const endpoint = String(data.get("endpoint") ?? "").trim();
    const model = String(data.get("model") ?? "").trim();
    const api_key = String(data.get("api_key") ?? "").trim();
    const judge_key = String(data.get("judge_key") ?? "").trim();
    const system_prompt = String(data.get("system_prompt") ?? "").trim();
    const pack = (String(data.get("pack") ?? "default") as Pack) || "default";

    setErrorMsg(null);
    setStatus("submitting");
    slowTimer.current = setTimeout(() => setShowSlowHint(true), SLOW_HINT_MS);

    const body: ScanRequest = { endpoint, model, api_key, pack };
    // Only include the optionals when present — the server treats absence as
    // "use the keyless heuristic judge" / "no custom system prompt".
    if (judge_key) body.judge_key = judge_key;
    if (system_prompt) body.system_prompt = system_prompt;

    try {
      const r = await fetch(`${API_BASE}/api/public-scan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(SCAN_TIMEOUT_MS),
      });

      // The contract puts a human-readable reason in `detail` on every error
      // status (400/422/429/502/504). Surface it verbatim where we can.
      if (!r.ok) {
        let detail = `Scan failed (${r.status}). Please try again.`;
        try {
          const j: unknown = await r.json();
          if (
            j &&
            typeof j === "object" &&
            "detail" in j &&
            typeof (j as { detail: unknown }).detail === "string"
          ) {
            detail = (j as { detail: string }).detail;
          }
        } catch {
          // non-JSON error body — keep the status-based fallback
        }
        setErrorMsg(detail);
        setStatus("error");
        return;
      }

      const payload = (await r.json()) as ScanResponse;
      setResult(payload);
      track("public_scan_completed", {
        pack,
        judge: payload.summary.judge,
        breached: payload.summary.breached,
        trials: payload.summary.trials,
      });
      setStatus("success");
    } catch {
      setErrorMsg(
        "Couldn't reach ROGUE to run the scan — check your connection and try again. Your details are still here.",
      );
      setStatus("error");
    } finally {
      if (slowTimer.current) clearTimeout(slowTimer.current);
      setShowSlowHint(false);
    }
  }

  function reset() {
    setResult(null);
    setErrorMsg(null);
    setStatus("idle");
  }

  if (status === "success" && result) {
    return <ScanResult result={result} onReset={reset} />;
  }

  return (
    <div className="max-w-xl space-y-6">
      {/* Honest / safety note — always visible above the form. */}
      <div className="rogue-card border border-rogue-green/30 rounded-xl p-5 bg-rogue-green/[0.04] space-y-2">
        <p className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.18em] text-rogue-green">
          <ShieldAlert className="size-4" /> only scan what you own
        </p>
        <p className="text-sm text-muted-foreground leading-relaxed">
          Only scan endpoints you <span className="text-foreground">own or are authorized to test</span>. Your
          keys are sent to ROGUE&apos;s API to run this one scan and are{" "}
          <span className="text-foreground">never stored or logged</span>.
        </p>
        <p className="text-xs text-muted-foreground leading-relaxed">
          This is a small, bounded scan (a few primitives) and takes <span className="tabular-nums">~10–60s</span>.
        </p>
      </div>

      <form
        onSubmit={handleSubmit}
        className="rogue-card border border-border rounded-xl p-6 bg-card/40 space-y-5"
      >
        <div className="space-y-1.5">
          <FieldLabel htmlFor="ps-endpoint">
            Endpoint <span className="text-rogue-green">*</span>
          </FieldLabel>
          <Input
            id="ps-endpoint"
            name="endpoint"
            type="url"
            inputMode="url"
            required
            autoComplete="off"
            spellCheck={false}
            disabled={submitting}
            placeholder="https://api.your-co.com/v1"
          />
        </div>

        <div className="space-y-1.5">
          <FieldLabel htmlFor="ps-model">
            Model <span className="text-rogue-green">*</span>
          </FieldLabel>
          <Input
            id="ps-model"
            name="model"
            required
            autoComplete="off"
            spellCheck={false}
            disabled={submitting}
            placeholder="your-model"
          />
        </div>

        <div className="space-y-1.5">
          <FieldLabel htmlFor="ps-api-key">
            API key <span className="text-rogue-green">*</span>
          </FieldLabel>
          <Input
            id="ps-api-key"
            name="api_key"
            type="password"
            required
            autoComplete="off"
            disabled={submitting}
            placeholder="sk-…"
          />
          <p className="text-xs text-muted-foreground leading-relaxed">
            Your target endpoint&apos;s key — sent only to run this one scan, never stored or logged.
          </p>
        </div>

        <div className="space-y-1.5">
          <FieldLabel htmlFor="ps-judge-key">
            Judge key <span className="text-muted-foreground normal-case">(optional)</span>
          </FieldLabel>
          <Input
            id="ps-judge-key"
            name="judge_key"
            type="password"
            autoComplete="off"
            disabled={submitting}
            placeholder="anthropic / openai key"
          />
          <p className="text-xs text-muted-foreground leading-relaxed">
            Optional: an Anthropic/OpenAI key → graded by ROGUE&apos;s{" "}
            <span className="text-rogue-green">calibrated v3 judge</span> (89.3% human agreement). Leave blank
            for the free keyless heuristic judge.
          </p>
        </div>

        <div className="space-y-1.5">
          <FieldLabel htmlFor="ps-system-prompt">
            System prompt <span className="text-muted-foreground normal-case">(optional)</span>
          </FieldLabel>
          <Textarea
            id="ps-system-prompt"
            name="system_prompt"
            disabled={submitting}
            placeholder="You are a helpful assistant for…"
          />
          <p className="text-xs text-muted-foreground leading-relaxed">
            Red-team your <span className="text-foreground">real deployment</span> — paste the system prompt
            your model runs with.
          </p>
        </div>

        <div className="space-y-1.5">
          <FieldLabel htmlFor="ps-pack">Attack pack</FieldLabel>
          <Select id="ps-pack" name="pack" defaultValue={PACKS[0].value} disabled={submitting}>
            {PACKS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </Select>
        </div>

        {errorMsg && status === "error" && <ErrorBox detail={errorMsg} />}

        <div className="space-y-2">
          <button type="submit" className={ctaButton} disabled={submitting}>
            {submitting ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                Scanning…
              </>
            ) : (
              "Run the scan"
            )}
          </button>
          {submitting && (
            <p className="text-xs text-muted-foreground text-center leading-relaxed" aria-live="polite">
              Running a live ATTACKER → MODEL → JUDGE red-team against your endpoint…
              {showSlowHint && (
                <>
                  {" "}
                  <span className="text-foreground/70">this is a real scan, it can take up to a minute.</span>
                </>
              )}
            </p>
          )}
        </div>
      </form>
    </div>
  );
}

/** Red, brand-styled error box — surfaces the server's `detail` verbatim. */
function ErrorBox({ detail }: { detail: string }) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-rogue-red/40 bg-rogue-red/10 px-4 py-3 space-y-1"
    >
      <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-rogue-red">scan failed</p>
      <p className="text-sm text-foreground leading-relaxed">{detail}</p>
    </div>
  );
}

/** Success view: the breach card image + summary + download / share / reset. */
function ScanResult({ result, onReset }: { result: ScanResponse; onReset: () => void }) {
  const { card_png_base64, summary } = result;
  const { model_label, breached, trials, rate, judge } = summary;
  const ratePct = Math.round(rate * 100);
  const judgeLabel = judge === "calibrated-v3" ? "calibrated v3" : "keyless heuristic";

  const pngHref = `data:image/png;base64,${card_png_base64}`;

  const shareText = `I red-teamed my LLM with @ROGUE — ${breached}/${trials} jailbroken. Scan yours:`;
  const shareHref = `https://twitter.com/intent/tweet?text=${encodeURIComponent(
    shareText,
  )}&url=${encodeURIComponent(SHARE_URL)}`;

  return (
    <div className="max-w-xl space-y-6 animate-rogue-fade-up">
      <div className="space-y-2">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
          /scan · breach card
        </p>
        <h2 className="text-2xl sm:text-3xl font-bold tracking-tight">Your breach card</h2>
        <p className="font-mono text-sm text-muted-foreground">
          <span className="text-foreground tabular-nums">{breached}</span>/
          <span className="tabular-nums">{trials}</span> breached ·{" "}
          <span
            className="tabular-nums"
            style={{
              color: rate >= 0.3 ? "var(--rogue-red)" : rate >= 0.1 ? "var(--rogue-orange)" : "var(--rogue-green)",
            }}
          >
            {ratePct}%
          </span>{" "}
          · judge: <span className="text-foreground">{judgeLabel}</span>
          <span className="block opacity-70 mt-0.5">{model_label}</span>
        </p>
      </div>

      <div className="overflow-hidden rounded-lg border border-border bg-card/40">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={pngHref}
          alt={`ROGUE breach card for ${model_label} — ${breached} of ${trials} attacks breached (${ratePct}%), graded by the ${judgeLabel} judge`}
          className="h-auto w-full"
        />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <a
          href={pngHref}
          download={`rogue-breach-card-${model_label.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}.png`}
          className={cn(
            secondaryButton,
            "border-rogue-green/50 text-rogue-green hover:bg-rogue-green/10",
          )}
        >
          ↓ Download card
        </a>
        <a
          href={shareHref}
          target="_blank"
          rel="noopener noreferrer"
          onClick={() => track("public_scan_share_x", { breached, trials })}
          className={cn(secondaryButton, "border-border text-foreground hover:bg-card/60")}
        >
          Share on X
        </a>
        <button
          type="button"
          onClick={onReset}
          className={cn(secondaryButton, "border-border text-muted-foreground hover:bg-card/60")}
        >
          ↺ Scan another
        </button>
      </div>

      <p className="font-mono text-[10px] text-muted-foreground leading-relaxed">
        {"// bounded scan against your endpoint · keys never stored or logged · for the full deep-pipeline picture see the "}
        <a href="/leaderboard" className="text-rogue-green hover:underline">
          leaderboard
        </a>
      </p>
    </div>
  );
}
