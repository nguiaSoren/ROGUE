"""Seed `data/discovery_bandit.json` from the existing canonical-primitive corpus.

Post-hoc attribution: for each canonical AttackPrimitive in the DB, find which
bandit arms COULD have surfaced it by matching the arm's `site:DOMAIN/path`
SERP operator against the primitive's source URL. Credit the matching arm(s)
with `novel += 1`. Assume a fixed pulls-per-arm baseline (estimating that
every warm arm has been exercised the same number of times across our harvest
history) so `mean_yield = total_novel / total_cost_usd` differentiates arms
by their corpus productivity.

Rationale: the live bandit-record loop in `scripts/harvest_once.py:506-525`
uses an EVEN-SPLIT heuristic across the 10 picked arms (`per_arm_novel =
stats.new_clusters // n_arms`). That heuristic produces a uniform yield
across the warmed arms — useless for the dashboard `/feed` widget that wants
top-3 / bottom-3 differentiation. The Day-3 follow-up flagged in that comment
is per-arm attribution at HARVEST time; this script does the same attribution
RETROACTIVELY against the corpus we already have.

Arms with no `site:` operator (e.g., pure keyword queries like
``"OWASP" "LLM Top 10" "2026"``) are left cold — they need keyword-matching
against primitive title/family which is fragile and not in scope here.

Run:
    uv run python scripts/seed_bandit_from_corpus.py
    # Or with overrides:
    uv run python scripts/seed_bandit_from_corpus.py \\
        --pulls-per-arm 5 --output data/discovery_bandit.json
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Ensure repo root on sys.path so `import rogue.*` works when invoked as
# `uv run python scripts/seed_bandit_from_corpus.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from rogue.db.models import AttackPrimitive, SourceProvenance  # noqa: E402
from rogue.harvest.bandit import EpsilonGreedyBandit, _ArmStats  # noqa: E402
from rogue.harvest.bandit_attribution import (  # noqa: E402
    build_arm_pattern_map,
)
from rogue.harvest.discovery_agent import default_bandit_arms  # noqa: E402


logger = logging.getLogger("seed_bandit")

DEFAULT_DATABASE_URL = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"
DEFAULT_OUTPUT_PATH = Path("data/discovery_bandit.json")
DEFAULT_PULLS_PER_ARM = 5  # estimate of harvest-history depth per arm
DEFAULT_COST_PER_PULL = 0.0015  # SERP API per-call cost (§6.1)

def _attribute_primitives_via_id_sets(
    primitive_urls: list[tuple[str, str]],
    arm_id_to_pattern: dict[str, str],
) -> dict[str, set[str]]:
    """Per-arm primitive-id sets (one-shot offline path).

    Thin wrapper around :func:`attribute_urls_to_arms` that preserves
    primitive-id grouping for the seed-script summary log (so we can show
    "arm X surfaced primitives [a, b, c]" not just counts).
    """
    from collections import defaultdict

    from rogue.harvest.bandit_attribution import (
        normalize_url_for_matching,
        url_matches_arm,
    )

    attribution: dict[str, set[str]] = defaultdict(set)
    for primitive_id, url in primitive_urls:
        normalized = normalize_url_for_matching(url)
        matches: list[tuple[str, int]] = [
            (arm_id, len(pattern))
            for arm_id, pattern in arm_id_to_pattern.items()
            if url_matches_arm(normalized, pattern)
        ]
        if not matches:
            continue
        max_len = max(length for _, length in matches)
        for arm_id, length in matches:
            if length == max_len:
                attribution[arm_id].add(primitive_id)
    return attribution


def load_canonical_primitive_urls(database_url: str) -> list[tuple[str, str]]:
    """Read (primitive_id, url) for every (canonical primitive × source)."""
    engine = create_engine(database_url)
    SessionLocal = sessionmaker(bind=engine)
    try:
        with SessionLocal() as session:
            rows = session.execute(
                select(SourceProvenance.primitive_id, SourceProvenance.url)
                .join(
                    AttackPrimitive,
                    AttackPrimitive.primitive_id == SourceProvenance.primitive_id,
                )
                .where(AttackPrimitive.canonical.is_(True))
            ).all()
        return [(pid, url) for pid, url in rows]
    finally:
        engine.dispose()


def build_seeded_bandit(
    pulls_per_arm: int,
    cost_per_pull: float,
    attribution: dict[str, set[str]],
) -> EpsilonGreedyBandit:
    """Construct a bandit, seed warm arms with their attribution counts.

    Arms with no attribution stay cold (pulls=0) so cold-start preference
    still picks them up on the next live harvest run. Stamps
    ``seeded_from_corpus_at`` so the dashboard can show "warm-prior from
    corpus" provenance distinct from live-pull state.
    """
    from datetime import datetime, timezone

    arms = default_bandit_arms()
    bandit = EpsilonGreedyBandit(arms=arms)
    bandit.seeded_from_corpus_at = datetime.now(timezone.utc).isoformat()
    cost = pulls_per_arm * cost_per_pull
    for arm_id, primitive_ids in attribution.items():
        n_novel = len(primitive_ids)
        if n_novel == 0:
            continue
        bandit.stats[arm_id] = _ArmStats(
            pulls=pulls_per_arm,
            total_novel=n_novel,
            total_cost_usd=cost,
        )
    return bandit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Seed data/discovery_bandit.json from canonical-primitive corpus. "
            "Post-hoc per-arm attribution via SERP `site:` operator matching."
        ),
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
    )
    parser.add_argument(
        "--pulls-per-arm",
        type=int,
        default=DEFAULT_PULLS_PER_ARM,
        help=(
            "Synthetic pull count per warm arm. Estimates how many times "
            "each arm was 'exercised' across our harvest history; the bandit's "
            "mean_yield = total_novel / (pulls * cost) so this constant fixes "
            "the denominator, letting total_novel drive the ranking. "
            f"Default {DEFAULT_PULLS_PER_ARM}."
        ),
    )
    parser.add_argument(
        "--cost-per-pull",
        type=float,
        default=DEFAULT_COST_PER_PULL,
        help=f"Per-SERP cost (§6.1). Default ${DEFAULT_COST_PER_PULL:.4f}.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print attribution summary; do not write the bandit file.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    # --- Step 1: parse arms → site patterns ---
    arms = default_bandit_arms()
    arm_id_to_pattern = build_arm_pattern_map(arms)
    no_site_arms = [a.arm_id for a in arms if a.arm_id not in arm_id_to_pattern]
    logger.info(
        "arms: %d total, %d with site: operator, %d cold (no site:)",
        len(arms), len(arm_id_to_pattern), len(no_site_arms),
    )
    if no_site_arms:
        logger.info("cold arms (kept at pulls=0): %s", ", ".join(no_site_arms))

    # --- Step 2: load corpus URLs ---
    primitive_urls = load_canonical_primitive_urls(args.database_url)
    logger.info(
        "corpus: %d (canonical_primitive × source) URL rows",
        len(primitive_urls),
    )

    # --- Step 3: attribute (id-set form so we can log per-arm primitive_ids) ---
    attribution = _attribute_primitives_via_id_sets(primitive_urls, arm_id_to_pattern)
    n_warm = len(attribution)
    n_unattributed = len(arm_id_to_pattern) - n_warm
    logger.info(
        "attribution: %d arms warmed, %d site-arms unattributed, %d cold no-site arms",
        n_warm, n_unattributed, len(no_site_arms),
    )

    # --- Step 4: build + persist bandit ---
    bandit = build_seeded_bandit(
        pulls_per_arm=args.pulls_per_arm,
        cost_per_pull=args.cost_per_pull,
        attribution=attribution,
    )

    # Surface the resulting top/bottom-5 so the operator sees the ranking
    # before the file lands.
    warm_arms = bandit.top_arms(n=5)
    cold_in_corpus = bandit.bottom_arms(n=5)
    logger.info("--- top 5 by mean_yield ---")
    for a in warm_arms:
        s = bandit.stats[a.arm_id]
        logger.info(
            "  %-32s pulls=%d novel=%d yield=%.1f",
            a.arm_id, s.pulls, s.total_novel, s.mean_yield,
        )
    logger.info("--- bottom 5 by mean_yield (warm only) ---")
    for a in cold_in_corpus:
        s = bandit.stats[a.arm_id]
        logger.info(
            "  %-32s pulls=%d novel=%d yield=%.1f",
            a.arm_id, s.pulls, s.total_novel, s.mean_yield,
        )

    if args.dry_run:
        logger.info("DRY RUN — not writing %s", args.output)
        return 0

    bandit.to_disk(args.output)
    logger.info("persisted bandit state → %s", args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
