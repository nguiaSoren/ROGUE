"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/** Clears the session cookie via DELETE /api/session, then returns to sign-in. */
export function SignOutButton() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  return (
    <button
      type="button"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        await fetch("/api/session", { method: "DELETE" });
        router.push("/sign-in");
        router.refresh();
      }}
      className="rounded border border-border px-2 py-1 hover:bg-muted disabled:opacity-50"
    >
      {busy ? "…" : "Sign out"}
    </button>
  );
}
