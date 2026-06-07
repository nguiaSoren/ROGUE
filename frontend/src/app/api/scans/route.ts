/**
 * POST /api/scans, create a scan from a client component (the /scans/new form).
 *
 * Reads the API key from the server session cookie and forwards to `POST /v1/scans`, so the browser
 * never holds the bearer. Returns the created `ScanRecord` (status=queued) or the error envelope.
 */

import { NextResponse } from "next/server";

import { ApiV1Error, platformApi, type ScanSpec } from "@/lib/platform-api";
import { getApiKey } from "@/lib/session";

export async function POST(request: Request) {
  const key = await getApiKey();
  if (!key) {
    return NextResponse.json(
      { error: { code: "no_session", message: "not signed in" } },
      { status: 401 },
    );
  }

  let spec: ScanSpec;
  try {
    spec = (await request.json()) as ScanSpec;
  } catch {
    return NextResponse.json(
      { error: { code: "bad_request", message: "invalid JSON body" } },
      { status: 400 },
    );
  }

  const idem = request.headers.get("Idempotency-Key") ?? undefined;
  try {
    const record = await platformApi.createScan(spec, key, idem);
    return NextResponse.json(record, { status: 202 });
  } catch (e) {
    if (e instanceof ApiV1Error) {
      return NextResponse.json({ error: { code: e.code, message: e.message } }, { status: e.status });
    }
    const message = e instanceof Error ? e.message : "scan create failed";
    return NextResponse.json({ error: { code: "upstream", message } }, { status: 502 });
  }
}
