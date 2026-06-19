import { revalidatePath } from "next/cache";
import { NextResponse } from "next/server";

/**
 * On-demand ISR revalidation hook.
 *
 * The data pages (/matrix, /brief, /feed, /) are statically prerendered + 5-min
 * ISR, so new breaches otherwise surface within ~5 min. The harvest / reproduce
 * scripts POST here after they write new rows so the pages regenerate
 * immediately, "latest data, no waiting, no polling".
 *
 *   curl -X POST "$FRONTEND/api/revalidate" -H "x-revalidate-token: $REVALIDATE_TOKEN"
 *
 * Auth: a shared secret in REVALIDATE_TOKEN (Vercel env). Fails closed, if the
 * env var is unset or the token mismatches, nothing is revalidated. POST-only so
 * it can't be triggered by a stray GET / prefetch.
 */
const PATHS = ["/matrix", "/brief", "/feed", "/"];

export async function POST(request: Request): Promise<NextResponse> {
  const token =
    request.headers.get("x-revalidate-token") ??
    new URL(request.url).searchParams.get("token");

  const expected = process.env.REVALIDATE_TOKEN;
  if (!expected || token !== expected) {
    return NextResponse.json({ ok: false, error: "unauthorized" }, { status: 401 });
  }

  for (const path of PATHS) revalidatePath(path);
  return NextResponse.json({ ok: true, revalidated: PATHS });
}
