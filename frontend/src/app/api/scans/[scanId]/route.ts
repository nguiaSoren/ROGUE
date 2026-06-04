/**
 * GET /api/scans/{scanId} — the poller's endpoint (called by the client ScanProgress component).
 *
 * Forwards to `GET /v1/scans/{id}` with the session key attached server-side, so the live-progress
 * poll never exposes the bearer to the browser.
 */

import { NextResponse } from "next/server";

import { ApiV1Error, platformApi } from "@/lib/platform-api";
import { getApiKey } from "@/lib/session";

export async function GET(_request: Request, { params }: { params: Promise<{ scanId: string }> }) {
  const key = await getApiKey();
  if (!key) {
    return NextResponse.json({ error: { code: "no_session", message: "not signed in" } }, { status: 401 });
  }
  const { scanId } = await params;
  try {
    const record = await platformApi.getScan(scanId, key);
    return NextResponse.json(record);
  } catch (e) {
    if (e instanceof ApiV1Error) {
      return NextResponse.json({ error: { code: e.code, message: e.message } }, { status: e.status });
    }
    const message = e instanceof Error ? e.message : "lookup failed";
    return NextResponse.json({ error: { code: "upstream", message } }, { status: 502 });
  }
}
