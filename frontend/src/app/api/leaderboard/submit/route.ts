/**
 * POST /api/leaderboard/submit, opt-in "submit your model" intake — GATED INACTIVE.
 *
 * VIRAL_LAUNCH_SPEC Decision #4: the public leaderboard supports opt-in user
 * submissions that feed the same static board. This is the typed intake surface
 * for that — but it is DELIBERATELY INERT pending owner moderation/abuse review.
 *
 * Gate: returns 503 "submissions not yet open" unless
 * `ROGUE_LEADERBOARD_SUBMISSIONS=1` is set in the server env. Default (unset/"0")
 * = closed. Even when the flag is on this route only validates + echoes the
 * payload back; it does NOT persist to Neon, does NOT enqueue a scan, and there
 * is NO DB migration behind it. Persistence is intentionally left unbuilt so the
 * external-write surface stays inert until the owner signs off on the moderation
 * pipeline.
 *
 * TODO(owner): enable after moderation/abuse review — wire the validated payload
 * to a moderation queue (NOT a direct Neon write), add rate-limiting + a captcha
 * or signed-key check, then flip ROGUE_LEADERBOARD_SUBMISSIONS=1 in Production.
 */

import { NextResponse } from "next/server";

// Route handlers are uncached by default (Next 16). This one must never be
// statically prerendered — it reads env + request body at request time.
export const dynamic = "force-dynamic";

/** True only when the owner has explicitly opened submissions. Default closed. */
const SUBMISSIONS_OPEN = process.env.ROGUE_LEADERBOARD_SUBMISSIONS === "1";

/**
 * Typed opt-in submission payload. A submitter declares which model they ran
 * ROGUE against and (optionally) the breach numbers they measured; once the
 * moderation pipeline exists these are re-verified server-side before they can
 * ever touch the public board (never trust client-reported breach rates).
 */
export type LeaderboardSubmission = {
  /** Display label for the model, e.g. "acme/guard-7b". */
  model_label: string;
  /** Optional org/owner attribution shown next to the row. */
  submitter?: string;
  /** Contact for verification / takedown. Not displayed publicly. */
  contact_email?: string;
  /** Self-reported any-breach rate in [0,1] (re-verified before publish). */
  any_breach_rate?: number;
  /** Self-reported trial count backing the rate. */
  n_trials?: number;
  /** Worst-breaching attack family the submitter observed. */
  worst_family?: string;
  /** Free-text note for the moderator. */
  note?: string;
};

type FieldError = { field: string; message: string };

/**
 * Shape-only validation (no persistence). Keeps the contract honest so that when
 * the route is enabled the moderation queue receives a well-formed payload.
 */
function validate(body: unknown): { ok: true; value: LeaderboardSubmission } | { ok: false; errors: FieldError[] } {
  const errors: FieldError[] = [];
  if (typeof body !== "object" || body === null) {
    return { ok: false, errors: [{ field: "_root", message: "expected a JSON object" }] };
  }
  const b = body as Record<string, unknown>;

  const model_label = b.model_label;
  if (typeof model_label !== "string" || model_label.trim().length === 0) {
    errors.push({ field: "model_label", message: "required, non-empty string" });
  } else if (model_label.length > 120) {
    errors.push({ field: "model_label", message: "max 120 chars" });
  }

  if (b.any_breach_rate !== undefined) {
    const r = b.any_breach_rate;
    if (typeof r !== "number" || Number.isNaN(r) || r < 0 || r > 1) {
      errors.push({ field: "any_breach_rate", message: "must be a number in [0,1]" });
    }
  }
  if (b.n_trials !== undefined) {
    const n = b.n_trials;
    if (typeof n !== "number" || !Number.isInteger(n) || n < 0) {
      errors.push({ field: "n_trials", message: "must be a non-negative integer" });
    }
  }
  for (const k of ["submitter", "contact_email", "worst_family", "note"] as const) {
    if (b[k] !== undefined && typeof b[k] !== "string") {
      errors.push({ field: k, message: "must be a string" });
    }
  }

  if (errors.length > 0) return { ok: false, errors };
  return {
    ok: true,
    value: {
      model_label: (model_label as string).trim(),
      submitter: typeof b.submitter === "string" ? b.submitter : undefined,
      contact_email: typeof b.contact_email === "string" ? b.contact_email : undefined,
      any_breach_rate: typeof b.any_breach_rate === "number" ? b.any_breach_rate : undefined,
      n_trials: typeof b.n_trials === "number" ? b.n_trials : undefined,
      worst_family: typeof b.worst_family === "string" ? b.worst_family : undefined,
      note: typeof b.note === "string" ? b.note : undefined,
    },
  };
}

const CLOSED_BODY = {
  ok: false as const,
  status: "submissions_closed" as const,
  message:
    "Leaderboard submissions are not yet open. We are reviewing moderation and abuse controls before accepting external entries. Check back soon.",
};

export async function POST(request: Request) {
  if (!SUBMISSIONS_OPEN) {
    // INERT by default — no body is read, nothing is persisted.
    return NextResponse.json(CLOSED_BODY, { status: 503 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { ok: false, error: { code: "bad_request", message: "invalid JSON body" } },
      { status: 400 },
    );
  }

  const result = validate(body);
  if (!result.ok) {
    return NextResponse.json(
      { ok: false, error: { code: "validation", message: "invalid submission" }, fields: result.errors },
      { status: 422 },
    );
  }

  // TODO(owner): enable after moderation/abuse review — this is where the
  // validated payload would be handed to the moderation queue for re-verification
  // before it can ever appear on the public board. It is intentionally NOT
  // persisted: even with the flag on, this route only acknowledges receipt.
  return NextResponse.json(
    {
      ok: true,
      status: "received_not_persisted",
      message:
        "Submission accepted for review. Note: persistence is not enabled in this build; this is an acknowledgement only.",
      received: result.value,
    },
    { status: 202 },
  );
}

/** Anything other than POST is not allowed on this route. */
export async function GET() {
  return NextResponse.json(
    { ok: false, error: { code: "method_not_allowed", message: "use POST" } },
    { status: 405 },
  );
}
