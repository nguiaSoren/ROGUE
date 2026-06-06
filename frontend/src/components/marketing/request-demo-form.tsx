"use client";

import { useRef, useState } from "react";
import { CheckCircle2, Loader2 } from "lucide-react";

import { FieldLabel } from "@/components/marketing/section";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { track } from "@/lib/analytics";
import { cn } from "@/lib/utils";

/**
 * Lead-capture form for /request-demo.
 *
 * Client component. Validates email client-side, POSTs JSON to the Wave-1
 * backend (`POST {API_BASE}/api/demo-request`), and swaps itself for an inline
 * confirmation card on success. On any failure (network or non-2xx) it shows an
 * inline error and keeps the entered values so the visitor can retry.
 *
 * The API base is resolved the same way `src/lib/api.ts` does — from
 * `NEXT_PUBLIC_API_BASE` (defaulting to localhost:8000) — rather than
 * hardcoded, so it tracks whatever the dashboard pages already talk to.
 */

// Mirror `src/lib/api.ts`: same env var, same localhost fallback. The api.ts
// `apiGet` helper is GET-only + ISR-cached, so it isn't reusable for this POST;
// we reuse its base-URL contract instead.
const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

// Render's free tier cold-boots on the first request after idle — the POST can
// take several seconds. Cap it generously so a real cold start succeeds, but
// still bail rather than hang the UI forever.
const SUBMIT_TIMEOUT_MS = 30_000;
// If the request is still in flight after this, show a "this can take a few
// seconds" hint so a cold start doesn't read as a hang.
const SLOW_HINT_MS = 4_000;

const DEPLOYMENT_TYPES = [
  "Hosted API",
  "Self-hosted / private",
  "SDK / CI",
  "MCP",
  "Not sure yet",
] as const;

// Pragmatic email shape check — presence + a basic local@domain.tld pattern.
// The server is authoritative (422 on bad email); this is just fast UX.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type Status = "idle" | "submitting" | "success" | "error";

const ctaButton = cn(
  "inline-flex items-center justify-center gap-2 rounded-lg px-6 py-3 w-full",
  "bg-rogue-green text-black font-mono text-sm font-bold tracking-[0.15em] uppercase",
  "transition-opacity hover:opacity-90",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rogue-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background",
  "disabled:cursor-not-allowed disabled:opacity-60",
);

export function RequestDemoForm() {
  const [status, setStatus] = useState<Status>("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [emailError, setEmailError] = useState<string | null>(null);
  const [showSlowHint, setShowSlowHint] = useState(false);
  const [submittedType, setSubmittedType] = useState<string>("");

  const slowTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const submitting = status === "submitting";

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (submitting) return;

    const form = e.currentTarget;
    const data = new FormData(form);
    const name = String(data.get("name") ?? "").trim();
    const company = String(data.get("company") ?? "").trim();
    const email = String(data.get("email") ?? "").trim();
    const deployment_type = String(data.get("deployment_type") ?? "").trim();
    const message = String(data.get("message") ?? "").trim();

    // Client-side email validation — presence + shape.
    if (!email || !EMAIL_RE.test(email)) {
      setEmailError("Enter a valid work email so we can reach you.");
      setStatus("error");
      setErrorMsg(null);
      return;
    }
    setEmailError(null);
    setErrorMsg(null);
    setStatus("submitting");

    slowTimer.current = setTimeout(() => setShowSlowHint(true), SLOW_HINT_MS);

    try {
      const r = await fetch(`${API_BASE}/api/demo-request`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, company, email, deployment_type, message }),
        signal: AbortSignal.timeout(SUBMIT_TIMEOUT_MS),
      });

      if (!r.ok) {
        if (r.status === 422) {
          setEmailError("That email looks invalid — double-check and retry.");
          setStatus("error");
          return;
        }
        throw new Error(`demo-request → ${r.status}`);
      }

      setSubmittedType(deployment_type);
      track("request_demo_submitted", { deployment_type });
      setStatus("success");
    } catch {
      setErrorMsg(
        "Something went wrong sending your request. Please try again — your details are still here.",
      );
      setStatus("error");
    } finally {
      if (slowTimer.current) clearTimeout(slowTimer.current);
      setShowSlowHint(false);
    }
  }

  if (status === "success") {
    return (
      <div className="rogue-card border border-rogue-green/40 rounded-xl p-6 bg-card/40 max-w-xl">
        <div className="flex items-start gap-3">
          <CheckCircle2 className="size-6 text-rogue-green shrink-0 mt-0.5" />
          <div className="space-y-2">
            <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-rogue-green">
              request received
            </p>
            <h2 className="text-xl font-bold tracking-tight">
              Thanks — we&apos;ll be in touch.
            </h2>
            <p className="text-sm text-muted-foreground leading-relaxed">
              We&apos;ll reach out shortly to scope a scan against your{" "}
              {submittedType ? (
                <span className="text-foreground">{submittedType}</span>
              ) : (
                "stack"
              )}{" "}
              and walk you through a sample report.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      noValidate
      className="rogue-card border border-border rounded-xl p-6 bg-card/40 max-w-xl space-y-5"
    >
      <div className="space-y-1.5">
        <FieldLabel htmlFor="rd-name">Name</FieldLabel>
        <Input id="rd-name" name="name" autoComplete="name" disabled={submitting} />
      </div>

      <div className="space-y-1.5">
        <FieldLabel htmlFor="rd-company">Company</FieldLabel>
        <Input
          id="rd-company"
          name="company"
          autoComplete="organization"
          disabled={submitting}
        />
      </div>

      <div className="space-y-1.5">
        <FieldLabel htmlFor="rd-email">
          Work email <span className="text-rogue-green">*</span>
        </FieldLabel>
        <Input
          id="rd-email"
          name="email"
          type="email"
          required
          autoComplete="email"
          disabled={submitting}
          aria-invalid={emailError ? true : undefined}
          aria-describedby={emailError ? "rd-email-error" : undefined}
          onChange={() => emailError && setEmailError(null)}
        />
        {emailError && (
          <p id="rd-email-error" className="text-xs text-destructive">
            {emailError}
          </p>
        )}
      </div>

      <div className="space-y-1.5">
        <FieldLabel htmlFor="rd-deployment">Deployment type</FieldLabel>
        <Select
          id="rd-deployment"
          name="deployment_type"
          defaultValue={DEPLOYMENT_TYPES[0]}
          disabled={submitting}
        >
          {DEPLOYMENT_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </Select>
      </div>

      <div className="space-y-1.5">
        <FieldLabel htmlFor="rd-message">
          Message <span className="text-muted-foreground normal-case">(optional)</span>
        </FieldLabel>
        <Textarea
          id="rd-message"
          name="message"
          disabled={submitting}
          placeholder="What are you trying to secure? Models, tools, system prompts…"
        />
      </div>

      {errorMsg && (
        <p role="alert" className="text-sm text-destructive">
          {errorMsg}
        </p>
      )}

      <div className="space-y-2">
        <button type="submit" className={ctaButton} disabled={submitting}>
          {submitting ? (
            <>
              <Loader2 className="size-4 animate-spin" />
              Sending…
            </>
          ) : (
            "Request a demo"
          )}
        </button>
        {submitting && showSlowHint && (
          <p className="text-xs text-muted-foreground text-center" aria-live="polite">
            Waking the service — this can take a few seconds.
          </p>
        )}
      </div>
    </form>
  );
}
