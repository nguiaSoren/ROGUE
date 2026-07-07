"""$0 offline validator for Feature 5 — pre-fire prompt pruning (Q12/Q10).

The live headline (breach-per-dollar lift from skipping redundant rollouts) needs a paid A/B. But two
things can be measured for free, against embeddings ROGUE has already paid for, and they are exactly
the two numbers that decide whether the hard cosine gate is safe to turn on:

  1. **Addressable redundancy** — over ROGUE's real ``attack_primitives`` (payload embeddings already
     stored), replay the greedy 0.92 pre-fire gate in harvest order and report the fraction of prompts
     that are near-duplicates of one already admitted (the rollouts an exploring searcher would skip).

  2. **Breach-coverage loss (the safety-critical number)** — of the near-duplicate prompts that
     *breached*, what fraction have an admitted nearest-neighbour that ALSO breached (a FREE prune —
     the breach is still represented) vs one that did NOT (a LOSSY prune — dedup would have dropped a
     breach the kept representative doesn't reproduce)? The gate is only safe if lossy prunes are rare.

This is the same "replay over already-paid rows" discipline as the Q6/Q7/Q11 validators. It reads the
un-redacted ``attack_primitives`` from Neon via raw SQL (no ORM→Pydantic conversion, which the local
redacted snapshot breaks). Both numbers are conservative proxies for the *in-search* redundancy the
gate removes — a real search re-visits the neighbourhood of a seed far more densely than the harvested
corpus samples it — so the live prune rate should meet or exceed the corpus figure.

    uv run python scripts/reproduce/replay_prefire_prune.py                 # $DATABASE_URL (Neon)
    uv run python scripts/reproduce/replay_prefire_prune.py --threshold 0.9
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

import asyncio
import hashlib

from rogue.dedupe.embeddings import DEFAULT_COSINE_THRESHOLD
from rogue.reproduce.search.actions import cheap_mutation_actions
from rogue.reproduce.search.bandit import BanditSearcher
from rogue.reproduce.search.mcts import MCTSSearcher
from rogue.reproduce.search.pruning import PromptPruner
from rogue.reproduce.search.searcher import Budget, RolloutOutcome
from rogue.reproduce.sprt import wilson_interval
from rogue.schemas.breach_result import JudgeVerdict

_DEFAULT_DB = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"


def _parse_vec(raw) -> np.ndarray | None:
    """pgvector comes back as a '[0.1,0.2,…]' string (or a list); parse to a float32 array."""
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        return np.asarray(raw, dtype=np.float32)
    s = str(raw).strip().lstrip("[").rstrip("]")
    if not s:
        return None
    try:
        return np.fromstring(s, sep=",", dtype=np.float32)
    except Exception:  # noqa: BLE001
        return None


def _fetch(database_url: str):
    """(embedding, ever_breached) per primitive with a stored embedding, in harvest order."""
    engine = create_engine(database_url)
    q = text(
        """
        SELECT ap.payload_embedding AS emb,
               COALESCE(bool_or(br.verdict IN ('full_breach', 'partial_breach')), false) AS ever_breached
        FROM attack_primitives ap
        LEFT JOIN breach_results br ON br.primitive_id = ap.primitive_id
        WHERE ap.payload_embedding IS NOT NULL
        GROUP BY ap.primitive_id, ap.payload_embedding, ap.discovered_at
        ORDER BY ap.discovered_at NULLS LAST, ap.primitive_id
        """
    )
    embs, breached = [], []
    with engine.connect() as c:
        for row in c.execute(q):
            v = _parse_vec(row.emb)
            if v is None or v.size == 0:
                continue
            n = np.linalg.norm(v)
            if n == 0:
                continue
            embs.append(v / n)  # L2-normalise ⇒ dot product == cosine
            breached.append(bool(row.ever_breached))
    return embs, breached


def replay(embs: list[np.ndarray], breached: list[bool], threshold: float) -> dict:
    """Greedy pre-fire gate: admit a prompt unless its max cosine to an already-admitted prompt ≥
    threshold. Track prune rate + the free/lossy split of pruned breaching prompts."""
    admitted_vecs: list[np.ndarray] = []
    admitted_breached: list[bool] = []
    n_pruned = 0
    pruned_breach_free = 0   # pruned & breached, nearest admitted neighbour ALSO breached
    pruned_breach_lossy = 0  # pruned & breached, nearest admitted neighbour did NOT breach
    for v, b in zip(embs, breached):
        if admitted_vecs:
            sims = np.asarray(admitted_vecs) @ v
            j = int(np.argmax(sims))
            if sims[j] >= threshold:
                n_pruned += 1
                if b:
                    if admitted_breached[j]:
                        pruned_breach_free += 1
                    else:
                        pruned_breach_lossy += 1
                continue
        admitted_vecs.append(v)
        admitted_breached.append(b)
    n = len(embs)
    lo, hi = wilson_interval(n_pruned, n)
    pruned_breach = pruned_breach_free + pruned_breach_lossy
    return {
        "n": n, "n_admitted": len(admitted_vecs), "n_pruned": n_pruned,
        "prune_rate": n_pruned / n if n else 0.0, "prune_ci": (lo, hi),
        "pruned_breach": pruned_breach, "pruned_breach_free": pruned_breach_free,
        "pruned_breach_lossy": pruned_breach_lossy,
        "lossy_rate": pruned_breach_lossy / pruned_breach if pruned_breach else 0.0,
        "base_breach_rate": sum(breached) / n if n else 0.0,
    }


def _string_embed(prompt: str) -> list[float]:
    """Orthogonal-per-distinct-string embedding — identical strings collide (cosine 1.0), distinct
    strings are (near-)orthogonal. Prunes ONLY exact regenerations ⇒ a clean, config-free LOWER BOUND
    on in-search near-duplication, with zero paid embedding calls."""
    idx = int(hashlib.sha256(prompt.encode()).hexdigest(), 16) % 8192
    v = [0.0] * 8192
    v[idx] = 1.0
    return v


def _fetch_seeds(database_url: str, limit: int) -> list[str]:
    """Real seed payloads to drive the in-search redundancy measurement (raw SQL, no ORM convert)."""
    engine = create_engine(database_url)
    q = text(
        """
        SELECT payload_template FROM attack_primitives
        WHERE payload_template IS NOT NULL AND length(payload_template) BETWEEN 20 AND 4000
        ORDER BY discovered_at NULLS LAST, primitive_id
        LIMIT :lim
        """
    )
    with engine.connect() as c:
        return [r[0] for r in c.execute(q, {"lim": limit})]


def in_search_redundancy(seeds: list[str], max_rollouts: int = 30) -> dict:
    """Run the REAL MCTS + bandit searchers over real seeds with a $0 all-refused rollout and the
    string-identity embed. Reports the exact-regeneration prune rate the pruner removes in its actual
    per-search regime (one seed, one config) — un-confounded, a lower bound on the semantic gate."""

    async def refused_rollout(prompt: str) -> RolloutOutcome:
        return RolloutOutcome(JudgeVerdict.REFUSED, confidence=1.0, response="", cost_usd=0.001)

    async def _run() -> dict:
        actions = cheap_mutation_actions()
        per = {"mcts": [], "bandit": []}
        for i, seed in enumerate(seeds):
            for name, S in (("mcts", MCTSSearcher(seed=i)), ("bandit", BanditSearcher(seed=i))):
                r = await S.search(seed, refused_rollout, actions, Budget(max_rollouts=max_rollouts),
                                   pruner=PromptPruner(_string_embed))
                attempted = r.n_rollouts + r.n_pruned  # fired + skipped = candidate expansions
                per[name].append(r.n_pruned / attempted if attempted else 0.0)
        return {k: (sum(v) / len(v) if v else 0.0) for k, v in per.items()}

    return asyncio.run(_run())


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL", _DEFAULT_DB))
    ap.add_argument("--threshold", type=float, default=DEFAULT_COSINE_THRESHOLD)
    ap.add_argument("--in-search-seeds", type=int, default=40, help="real seeds for the in-search run")
    args = ap.parse_args(argv)

    print(f"Reading attack_primitives embeddings from {args.database_url.split('@')[-1]} …", file=sys.stderr)
    embs, breached = _fetch(args.database_url)
    if not embs:
        print("No stored embeddings — nothing to replay.", file=sys.stderr)
        return 1

    m = replay(embs, breached, args.threshold)
    lo, hi = m["prune_ci"]
    print(f"\n=== Feature 5 pre-fire pruning — offline replay ($0), τ={args.threshold} ===")
    print(f"primitives (embedded)      : {m['n']}   base breach rate {m['base_breach_rate']*100:.1f}%")
    print(f"near-duplicate prune rate  : {m['prune_rate']*100:.1f}%  "
          f"[95% CI {lo*100:.1f}%, {hi*100:.1f}%]  ({m['n_pruned']} of {m['n']})")
    print(f"admitted (fired)           : {m['n_admitted']}")
    print("\n-- breach-coverage safety (of pruned prompts that breached) --")
    print(f"  pruned & breached          : {m['pruned_breach']}")
    print(f"  FREE  (kept nbr breached)  : {m['pruned_breach_free']}")
    print(f"  LOSSY (kept nbr did not)   : {m['pruned_breach_lossy']}  "
          f"→ lossy-prune rate {m['lossy_rate']*100:.1f}% of pruned breaches")
    print("\n  (corpus lossy is config-confounded: two textually-near primitives may differ on "
          "ever_breached only because they were tested against different configs — it overstates the "
          "in-search risk, where the pruner dedups one seed against ONE config.)")

    seeds = _fetch_seeds(args.database_url, args.in_search_seeds)
    if seeds:
        ins = in_search_redundancy(seeds)
        print(f"\n-- in-search redundancy (real searchers over {len(seeds)} real seeds, string-identity "
              "embed = exact-regeneration LOWER bound, $0) --")
        print(f"  MCTS   exact-dup prune rate : {ins['mcts']*100:.1f}% of expansions")
        print(f"  bandit exact-dup prune rate : {ins['bandit']*100:.1f}% of expansions")
        print("  (semantic near-dups the 0.92 gate also catches sit ABOVE these exact-string floors.)")

    print("\nLive breach-per-dollar lift from the hard skip = a gated ~$35 A/B (the flag stays OFF "
          "until then). The safer default in ambiguous regimes is the EvoJail soft λ reward.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
