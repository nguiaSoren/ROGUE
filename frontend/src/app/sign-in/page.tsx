"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/**
 * Sign in with an `rk_live_` API key. The key is POSTed to /api/session, which validates it against
 * the platform and stores it in an httpOnly cookie — it is never kept in client-readable storage.
 */
export default function SignInPage() {
  const router = useRouter();
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await fetch("/api/session", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ api_key: key.trim() }),
      });
      if (r.ok) {
        router.push("/scans");
        router.refresh();
        return;
      }
      const body = (await r.json().catch(() => null)) as { error?: { message?: string } } | null;
      setError(body?.error?.message ?? "Sign-in failed.");
    } catch {
      setError("Could not reach the server. Try again.");
    }
    setBusy(false);
  }

  return (
    <div className="mx-auto w-full max-w-md px-4 py-16">
      <h1 className="text-xl font-semibold">Sign in to ROGUE</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        Paste your API key (<span className="font-mono">rk_live_…</span>). It is stored only in a
        secure, server-side session cookie — never in the browser.
      </p>
      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        <input
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder="rk_live_…"
          className="w-full rounded border border-border bg-background px-3 py-2.5 font-mono text-base sm:text-sm outline-none focus:border-foreground/40"
        />
        {error ? <p className="text-sm text-[var(--rogue-red,#ef4444)]">{error}</p> : null}
        <button
          type="submit"
          disabled={busy || !key.trim()}
          className="w-full rounded bg-foreground px-3 py-2.5 text-sm font-medium text-background hover:opacity-90 disabled:opacity-50"
        >
          {busy ? "Verifying…" : "Sign in"}
        </button>
      </form>
      <p className="mt-6 text-xs text-muted-foreground">
        Don&apos;t have a key yet?{" "}
        <a href="mailto:nguiasoren@gmail.com?subject=ROGUE%20access%20request" className="underline hover:text-foreground">
          Request access
        </a>{" "}
        and we&apos;ll set up your account.
      </p>
    </div>
  );
}
