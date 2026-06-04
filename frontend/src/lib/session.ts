/**
 * Server-only session: the customer's `rk_live_` API key, held in an httpOnly cookie.
 *
 * The platform authenticates with API keys (not user logins), so the dashboard "session" IS the key.
 * It lives in an httpOnly + secure cookie set by the `/api/session` route handler, so the browser's JS
 * never holds the raw secret. Server Components read it via `getApiKey()`; client components never see
 * it — they call same-origin route handlers that re-read this cookie and forward the bearer.
 *
 * Import ONLY from Server Components, Route Handlers, or Server Actions (it uses `next/headers`).
 */

import { cookies } from "next/headers";

export const SESSION_COOKIE = "rogue_key";
const THIRTY_DAYS = 60 * 60 * 24 * 30;

/** The caller's API key, or null if not signed in. */
export async function getApiKey(): Promise<string | null> {
  const store = await cookies();
  return store.get(SESSION_COOKIE)?.value ?? null;
}

/** Set the session cookie (call only from a Route Handler / Server Action). */
export async function setApiKey(key: string): Promise<void> {
  const store = await cookies();
  store.set(SESSION_COOKIE, key, {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/",
    maxAge: THIRTY_DAYS,
  });
}

/** Clear the session cookie (logout). */
export async function clearApiKey(): Promise<void> {
  const store = await cookies();
  store.delete(SESSION_COOKIE);
}

/** A display-safe fingerprint of the key (the stored prefix style), never the full secret. */
export function keyHint(key: string): string {
  return key.length > 12 ? `${key.slice(0, 12)}…` : key;
}
