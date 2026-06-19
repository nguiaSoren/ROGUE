/**
 * GET /api/scans/{scanId}/report?format=json|html|pdf, the export proxy.
 *
 * Forwards to `GET /v1/scans/{id}/report` with the session key attached, then streams the body back
 * with the upstream content-type. This lets the report page's export links/buttons be plain
 * same-origin `<a href>`s, the bearer stays server-side, never in a client URL.
 */

import { API_BASE } from "@/lib/platform-api";
import { getApiKey } from "@/lib/session";

const ACCEPT: Record<string, string> = {
  json: "application/json",
  html: "text/html; charset=utf-8",
  pdf: "application/pdf",
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
    `${API_BASE}/v1/scans/${encodeURIComponent(scanId)}/report?format=${encodeURIComponent(fmt)}`,
    { headers: { Authorization: `Bearer ${key}`, Accept: accept }, cache: "no-store", signal: AbortSignal.timeout(20_000) },
  );

  const body = await upstream.arrayBuffer();
  const headers = new Headers();
  headers.set("content-type", upstream.headers.get("content-type") ?? accept);
  if (fmt === "pdf") headers.set("content-disposition", `attachment; filename="rogue-${scanId}.pdf"`);
  return new Response(body, { status: upstream.status, headers });
}
