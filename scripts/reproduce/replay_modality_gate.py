"""$0 read-only validator: does the Q18 modality gate remove the budget waste on the REAL corpus?

The "verify the fix before paying" check for [[modality gate]] — the sibling of ``replay_acquisition.py``.
Ranks the full ``attack_primitives`` corpus against the given target(s) exactly the way ``reproduce_once``
does (Q7 model or reproducibility fallback for value, no embeddings live — the deployed regime), then counts
how many of the top-``DRYRUN_BUDGET`` (primitive × config) pairs would **modality-skip** at fire (fire zero
trials) under three orderings:

  * reproducibility (baseline)          -- the shipped order, no acquisition
  * acquisition, modality gate OFF      -- reproduces the confound (the value term prefers multimodal)
  * acquisition, modality gate ON       -- the fix (would-skip → 0 in the budget)

No target/judge calls, no writes: pure ranking. Run against ``$DATABASE_URL`` (Neon).

    uv run python scripts/reproduce/replay_modality_gate.py
    DRYRUN_TARGETS=openai/gpt-5.4-mini,openai/gpt-5.4-nano DRYRUN_BUDGET=100 uv run python \
        scripts/reproduce/replay_modality_gate.py
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from reproduce_once import _orm_to_pydantic_primitive  # sibling script (its dir is on sys.path under `uv run`)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from rogue.db.models import AttackPrimitive as AttackPrimitiveORM
from rogue.reproduce.acquisition.gate import (
    AcquisitionGate,
    DEFAULT_MODEL_PATH,
    _modality_compatible,
    build_cell_evidence,
)
from rogue.reproduce.prefire.model import PrefirePredictor
from rogue.schemas import DeploymentConfig

# default = image-capable-but-NOT-audio-capable targets → audio primitives skip
TARGETS = os.environ.get("DRYRUN_TARGETS", "openai/gpt-5.4-mini,openai/gpt-5.4-nano").split(",")
BUDGET = int(os.environ.get("DRYRUN_BUDGET", "100"))


def _count_skip(pairs, k: int) -> tuple[int, int]:
    """Of the top-k (primitive, config) pairs, how many would modality-SKIP at fire (target-aware)."""
    top = pairs[:k]
    skip = sum(1 for p, c in top if not _modality_compatible(p, c))
    return skip, len(top)


def main() -> int:
    load_dotenv()
    eng = create_engine(os.environ["DATABASE_URL"])
    with Session(eng) as session:
        orms = (
            session.query(AttackPrimitiveORM)
            .order_by(AttackPrimitiveORM.reproducibility_score.desc())
            .all()
        )
        prims = [_orm_to_pydantic_primitive(o) for o in orms]
        cell_evidence = build_cell_evidence(session)

    cfgs = [
        DeploymentConfig(config_id=f"dryrun-config-{i}", customer_id="rogue", name="dryrun",
                         target_model=t.strip(), system_prompt="You must refuse harmful requests.")
        for i, t in enumerate(TARGETS)
    ]
    pairs = [(p, c) for c in cfgs for p in prims]  # cartesian, config-major (repro-desc within config)

    predictor = PrefirePredictor.load(DEFAULT_MODEL_PATH) if os.path.exists(DEFAULT_MODEL_PATH) else None
    value_src = "Q7 pre-fire model" if predictor else "reproducibility_score fallback"

    # no embed_fn → diversity neutral (matches live: no embedding column)
    gate_on = AcquisitionGate(predictor=predictor, embed_fn=None, cell_evidence=cell_evidence, modality_gate=True)
    gate_off = AcquisitionGate(predictor=predictor, embed_fn=None, cell_evidence=cell_evidence, modality_gate=False)

    acq_on = gate_on.rank_pairs(pairs)
    acq_off = gate_off.rank_pairs(pairs)

    total_skip = sum(1 for p, c in pairs if not _modality_compatible(p, c))
    print(f"targets={[c.target_model for c in cfgs]}   corpus={len(prims)}   "
          f"total pairs={len(pairs)}   would-skip pairs={total_skip}   value={value_src}")
    print(f"budget (top-K) = {BUDGET}\n")
    print(f"{'ordering':38s} {'would-SKIP in top-K':>20s} {'would-FIRE':>12s}")
    for name, ordered in (
        ("reproducibility (baseline)", pairs),
        ("acquisition, modality gate OFF", acq_off),
        ("acquisition, modality gate ON (fix)", acq_on),
    ):
        sk, n = _count_skip(ordered, BUDGET)
        print(f"{name:38s} {sk:>20d} {n - sk:>12d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
