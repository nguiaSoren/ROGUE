/**
 * POST /api/scans/validate — the "test connection" pre-flight proxy.
 *
 * Reads the API key from the server session cookie and forwards the posted target to the upstream
 * `POST /v1/validate` (the cheap synchronous reachability/credentials check that brackets a paid
 * scan), so the browser never holds the bearer. Returns the upstream `ValidationResult` JSON
 * (`{ target, reachable, authenticated, model_responds, supports_image, supports_audio, error, ok }`)
 * or the `{ error: { code, message } }` envelope.
 *
 * Note: the live endpoint is `/v1/validate` (mounted by `rogue.api.v1.validate_benchmark`), not a
 * `/v1/scans/validate` sub-route — this proxy lives under `/api/scans/validate` only to sit next to
 * the other scan-flow proxy routes.
 */

import { NextResponse } from "next/server";

import { API_BASE, type TargetSpec } from "@/lib/platform-api";
import { getApiKey } from "@/lib/session";

const ATTEMPT_TIMEOUT_MS = 20_000;

export async function POST(request: Request) {
  const key = await getApiKey();
  if (!key) {
    return NextResponse.json(
      { error: { code: "no_session", message: "not signed in" } },
      { status: 401 },
    );
  }

  let body: TargetSpec;
  try {
    body = (await request.json()) as TargetSpec;
  } catch {
    return NextResponse.json(
      { error: { code: "bad_request", message: "invalid JSON body" } },
      { status: 400 },
    );
  }

  try {
    const upstream = await fetch(`${API_BASE}/v1/validate`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${key}`,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(ATTEMPT_TIMEOUT_MS),
    });

    const payload = await upstream.json().catch(() => null);
    if (payload === null) {
      return NextResponse.json(
        { error: { code: "upstream", message: `validate → ${upstream.status}` } },
        { status: 502 },
      );
    }
    return NextResponse.json(payload, { status: upstream.status });
  } catch (e) {
    const message = e instanceof Error ? e.message : "validate failed";
    return NextResponse.json({ error: { code: "upstream", message } }, { status: 502 });
  }
}
