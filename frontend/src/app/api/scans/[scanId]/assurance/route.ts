/**
 * GET /api/scans/{scanId}/assurance?format=json, the assurance-report export proxy.
 *
 * Forwards to `GET /v1/scans/{id}/assurance` with the session key attached, then streams the body
 * back with the upstream content-type. Mirrors the report route (app/api/scans/[scanId]/report):
 * the bearer stays server-side, never in a client URL, so the assurance page (and any export link)
 * can be a plain same-origin fetch / `<a href>`. Only `json` is served today.
 */

import { API_BASE } from "@/lib/platform-api";
import { getApiKey } from "@/lib/session";

const ACCEPT: Record<string, string> = {
  json: "application/json",
};

export async function GET(request: Request, { params }: { params: Promise<{ scanId: string }> }) {
  const key = await getApiKey();
  if (!key) {
    return new Response(JSON.stringify({ error: { code: "no_session", message: "not signed in" } }), {
      status: 401,
      headers: { "content-type": "application/json" },
    });
  }
  const { scanId } = await params;
  const fmt = new URL(request.url).searchParams.get("format") ?? "json";
  const accept = ACCEPT[fmt] ?? ACCEPT.json;

  const upstream = await fetch(
    `${API_BASE}/v1/scans/${encodeURIComponent(scanId)}/assurance?format=${encodeURIComponent(fmt)}`,
    { headers: { Authorization: `Bearer ${key}`, Accept: accept }, cache: "no-store", signal: AbortSignal.timeout(20_000) },
  );

  const body = await upstream.arrayBuffer();
  const headers = new Headers();
  headers.set("content-type", upstream.headers.get("content-type") ?? accept);
  return new Response(body, { status: upstream.status, headers });
}
