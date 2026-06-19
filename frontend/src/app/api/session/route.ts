/**
 * Session route, sign in / out with an `rk_live_` API key.
 *
 * POST validates the key against the live platform (an authed `GET /v1/scans?limit=1`) and, on
 * success, stores it in an httpOnly cookie. DELETE clears it. The raw key only ever travels in the
 * POST body over HTTPS and into a server-only cookie, it never lands in client-readable storage.
 */

import { NextResponse } from "next/server";

import { ApiV1Error, platformApi } from "@/lib/platform-api";
import { clearApiKey, setApiKey } from "@/lib/session";

export async function POST(request: Request) {
  let key: string | undefined;
  try {
    const body = (await request.json()) as { api_key?: unknown };
    if (typeof body?.api_key === "string") key = body.api_key.trim();
  } catch {
    /* fall through to the 400 below */
  }
  if (!key) {
    return NextResponse.json(
      { error: { code: "bad_request", message: "api_key is required" } },
      { status: 400 },
    );
  }

  // Validate by calling an authed endpoint with the key.
  try {
    await platformApi.listScans(key, { limit: 1 });
  } catch (e) {
    if (e instanceof ApiV1Error && e.status === 401) {
      return NextResponse.json(
        { error: { code: "invalid_api_key", message: "That API key was not recognized." } },
        { status: 401 },
      );
    }
    const message = e instanceof Error ? e.message : "could not reach the platform";
    return NextResponse.json({ error: { code: "upstream", message } }, { status: 502 });
  }

  await setApiKey(key);
  return NextResponse.json({ ok: true });
}

export async function DELETE() {
  await clearApiKey();
  return NextResponse.json({ ok: true });
}
