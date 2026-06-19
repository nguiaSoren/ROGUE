"use client";

import { useState } from "react";
import { CheckCircle2, Loader2 } from "lucide-react";

import { Input } from "@/components/ui/input";
import { track } from "@/lib/analytics";
import { cn } from "@/lib/utils";

/**
 * Newsletter subscribe form, drop into the footer (compact inline) or a page
 * section (carded block). Client component.
 *
 * Validates the email client-side, then POSTs JSON to the Wave-1 backend
 * (`POST {API_BASE}/api/newsletter`). The server distinguishes a fresh
 * subscribe (201) from an already-subscribed address (200, `already: true`) and
 * we surface a different confirmation for each. On any failure (network or
 * non-2xx other than 422) we show an inline error and keep the entered value so
 * the visitor can retry.
 *
 * The API base is resolved the same way `src/lib/api.ts` does, from
 * `NEXT_PUBLIC_API_BASE` (defaulting to localhost:8000), so it tracks whatever
 * the dashboard pages already talk to.
 */

// Mirror `src/lib/api.ts`: same env var, same localhost fallback.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

// Render's free tier cold-boots on the first request after idle, cap the POST
// generously so a real cold start succeeds, but still bail rather than hang.
const SUBMIT_TIMEOUT_MS = 30_000;

// Pragmatic email shape check, presence + a basic local@domain.tld pattern.
// The server is authoritative (422 on bad email); this is just fast UX.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type Status = "idle" | "submitting" | "success" | "error";

export function NewsletterSignup({
  variant = "section",
  className,
}: {
  variant?: "footer" | "section";
  className?: string;
}) {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [message, setMessage] = useState<string | null>(null);

  const submitting = status === "submitting";
  const succeeded = status === "success";
  const isError = status === "error";

  const inputId = `newsletter-email-${variant}`;
  const msgId = `newsletter-msg-${variant}`;

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (submitting) return;

    const value = email.trim();
    if (!value || !EMAIL_RE.test(value)) {
      setStatus("error");
      setMessage("Enter a valid email address.");
      return;
    }

    setStatus("submitting");
    setMessage(null);

    try {
      const r = await fetch(`${API_BASE}/api/newsletter`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: value, source: "newsletter" }),
        signal: AbortSignal.timeout(SUBMIT_TIMEOUT_MS),
      });

      if (!r.ok) {
        if (r.status === 422) {
          setStatus("error");
          setMessage("That email looks invalid, double-check and retry.");
          return;
        }
        throw new Error(`newsletter → ${r.status}`);
      }

      let already = false;
      try {
        const body = (await r.json()) as { already?: boolean };
        already = Boolean(body?.already);
      } catch {
        // Fall back to status code if the body isn't JSON.
        already = r.status === 200;
      }

      track("newsletter_subscribed", { source: "newsletter", already });
      setStatus("success");
      setMessage(
        already
          ? "You're already on the list."
          : "Subscribed, threat briefs incoming.",
      );
    } catch {
      setStatus("error");
      setMessage("Something went wrong. Please try again.");
    }
  }

  // ---- footer variant: compact inline row -------------------------------
  if (variant === "footer") {
    return (
      <div className={cn("w-full", className)}>
        <h3 className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
          Stay updated
        </h3>
        <p className="mt-4 max-w-xs text-sm text-muted-foreground leading-relaxed">
          The weekly threat brief, new jailbreaks reproduced against real
          deployments.
        </p>
        {succeeded ? (
          <p
            id={msgId}
            role="status"
            className="mt-4 flex items-center gap-2 text-sm text-rogue-green"
          >
            <CheckCircle2 className="size-4 shrink-0" />
            {message}
          </p>
        ) : (
          <form onSubmit={handleSubmit} noValidate className="mt-4 space-y-2">
            <label htmlFor={inputId} className="sr-only">
              Email address
            </label>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input
                id={inputId}
                name="email"
                type="email"
                inputMode="email"
                autoComplete="email"
                placeholder="you@company.com"
                value={email}
                disabled={submitting}
                aria-invalid={isError ? true : undefined}
                aria-describedby={message ? msgId : undefined}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (isError) {
                    setStatus("idle");
                    setMessage(null);
                  }
                }}
                className="h-9 text-sm min-w-0 sm:flex-1"
              />
              <button
                type="submit"
                disabled={submitting}
                className={cn(
                  "inline-flex h-9 items-center justify-center gap-2 rounded-lg px-4 shrink-0",
                  "bg-rogue-green text-[#050508] font-mono text-xs font-semibold uppercase tracking-[0.15em]",
                  "transition-opacity hover:opacity-90",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rogue-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                  "disabled:cursor-not-allowed disabled:opacity-60",
                )}
              >
                {submitting ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  "Subscribe"
                )}
              </button>
            </div>
            {isError && message && (
              <p id={msgId} role="alert" className="text-xs text-destructive">
                {message}
              </p>
            )}
          </form>
        )}
      </div>
    );
  }

  // ---- section variant: carded block ------------------------------------
  return (
    <div
      className={cn(
        "rogue-card border border-border rounded-xl p-6 bg-card/40",
        className,
      )}
    >
      <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-rogue-green">
        threat brief
      </p>
      <h2 className="mt-3 text-2xl font-bold tracking-tight">
        Get the weekly threat brief
      </h2>
      <p className="mt-3 text-sm text-muted-foreground leading-relaxed">
        A weekly diff of new jailbreaks and prompt-injection harvested from the
        open web and reproduced against real LLM deployments. No spam, unsubscribe
        anytime.
      </p>

      {succeeded ? (
        <p
          id={msgId}
          role="status"
          className="mt-6 flex items-center gap-2 text-sm text-rogue-green"
        >
          <CheckCircle2 className="size-5 shrink-0" />
          {message}
        </p>
      ) : (
        <form onSubmit={handleSubmit} noValidate className="mt-6 space-y-3">
          <label htmlFor={inputId} className="sr-only">
            Email address
          </label>
          <div className="flex flex-col gap-3 sm:flex-row">
            <Input
              id={inputId}
              name="email"
              type="email"
              inputMode="email"
              autoComplete="email"
              placeholder="you@company.com"
              value={email}
              disabled={submitting}
              aria-invalid={isError ? true : undefined}
              aria-describedby={message ? msgId : undefined}
              onChange={(e) => {
                setEmail(e.target.value);
                if (isError) {
                  setStatus("idle");
                  setMessage(null);
                }
              }}
              className="min-w-0 sm:flex-1"
            />
            <button
              type="submit"
              disabled={submitting}
              className={cn(
                "inline-flex items-center justify-center gap-2 rounded-lg px-6 py-2.5 shrink-0",
                "bg-rogue-green text-[#050508] font-mono text-sm font-bold tracking-[0.15em] uppercase",
                "transition-opacity hover:opacity-90",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rogue-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                "disabled:cursor-not-allowed disabled:opacity-60",
              )}
            >
              {submitting ? (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  Subscribing…
                </>
              ) : (
                "Subscribe"
              )}
            </button>
          </div>
          {isError && message && (
            <p id={msgId} role="alert" className="text-sm text-destructive">
              {message}
            </p>
          )}
        </form>
      )}
    </div>
  );
}
