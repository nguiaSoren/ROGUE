/**
 * GET /m/{slug} — a short, QR-friendly redirect to a model's all-time breach cell on the matrix.
 *
 * The shareable breach card's QR encodes this short URL (`/m/<model-slug>`) rather than the full
 * `/matrix/cell?family=…&config=…&scope=…&attacker=…` deep-link, so the QR stays low-density and
 * actually scans at card size. We resolve <slug> → {family, config} from the generated map and 307
 * to the full cell deep-link (all-time × augmented — the worst attacker view). An unknown slug falls
 * back to the public leaderboard, so the route can never error.
 *
 * The slug→{family,config} map (`@/data/model-cards.json`) is emitted by
 * `scripts/cards/generate_model_cards.py` in the same pass that renders the cards — single source,
 * no drift.
 */

import { NextResponse } from "next/server";

import MODELS from "@/data/model-cards.json";

type CellTarget = { family: string; config: string };

export async function GET(request: Request, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const origin = new URL(request.url).origin;
  const entry = (MODELS as Record<string, CellTarget>)[slug];

  if (!entry) {
    return NextResponse.redirect(new URL("/leaderboard", origin), 307);
  }

  const target = new URL("/matrix/cell", origin);
  target.searchParams.set("family", entry.family);
  target.searchParams.set("config", entry.config);
  target.searchParams.set("scope", "all-time");
  target.searchParams.set("attacker", "augmented");
  target.searchParams.set("from", "card");
  return NextResponse.redirect(target, 307);
}
