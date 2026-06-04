/**
 * POST /api/scans/{scanId}/cancel — cancel a running scan (called by the client cancel button).
 * Forwards to `POST /v1/scans/{id}/cancel` with the session key attached server-side.
 */

import { NextResponse } from "next/server";

import { ApiV1Error, platformApi } from "@/lib/platform-api";
import { getApiKey } from "@/lib/session";

export async function POST(_request: Request, { params }: { params: Promise<{ scanId: string }> }) {
  const key = await getApiKey();
  if (!key) {
    return NextResponse.json({ error: { code: "no_session", message: "not signed in" } }, { status: 401 });
  }
  const { scanId } = await params;
  try {
    const record = await platformApi.cancelScan(scanId, key);
    return NextResponse.json(record);
  } catch (e) {
    if (e instanceof ApiV1Error) {
      return NextResponse.json({ error: { code: e.code, message: e.message } }, { status: e.status });
    }
    const message = e instanceof Error ? e.message : "cancel failed";
    return NextResponse.json({ error: { code: "upstream", message } }, { status: 502 });
  }
}
