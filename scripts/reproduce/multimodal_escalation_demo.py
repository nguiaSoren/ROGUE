"""Demo: drive an EXISTING multi-turn escalation child MULTIMODALLY (read-only).

The escalation planner (Claude Sonnet) refuses to author new jailbreak
escalations, so the live ladder exhausts before reaching the image stage. This
demo bypasses the planner: it takes an already-synthesized multi-turn escalation
child from the DB, flags it multimodal with an `image_strategy`, renders it
(final objective turn → image, earlier turns stay text), dispatches to the
vision panel, and judges — so you can watch ARMS *visual* multi-turn escalation
actually hit a vision model. Does NOT write to the DB.

Usage:
    uv run python scripts/reproduce/multimodal_escalation_demo.py <primitive_id> [image_strategy]
e.g. uv run python scripts/reproduce/multimodal_escalation_demo.py 01KSM3ABF1W6R6WN4Y10FJ36EQ mml:wr
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Make the repo root importable so `scripts.*` resolves when run as a file.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from rogue.db.models import AttackPrimitive as AttackPrimitiveORM  # noqa: E402
from rogue.reproduce.instantiator import render  # noqa: E402
from rogue.reproduce.judge import JudgeAgent  # noqa: E402
from rogue.reproduce.target_panel import TargetPanel, supports_image  # noqa: E402
from rogue.schemas import demo_deployment_configs  # noqa: E402
from scripts.reproduce.synthesize_escalations import _orm_to_pydantic_primitive  # noqa: E402


async def main() -> None:
    pid = sys.argv[1]
    image_strategy = sys.argv[2] if len(sys.argv) > 2 else "mml:wr"

    engine = create_engine(os.environ["DATABASE_URL"])
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        orm = session.get(AttackPrimitiveORM, pid)
        if orm is None:
            raise SystemExit(f"primitive not found: {pid}")
        primitive = _orm_to_pydantic_primitive(orm)

    # Flag the existing multi-turn child as multimodal (final turn → image).
    primitive = primitive.model_copy(
        update={
            "requires_multimodal": True,
            "payload_slots": {**(primitive.payload_slots or {}), "image_strategy": image_strategy},
        }
    )

    panel = TargetPanel()
    judge = JudgeAgent()
    configs = [c for c in demo_deployment_configs() if supports_image(c.target_model)]

    # Show the rendered structure once so the multimodal shape is visible.
    sample = render(primitive, configs[0])
    user_turns = [m for m in sample.messages if m["role"] == "user"]
    print(f"\nMULTIMODAL ESCALATION ({image_strategy}) — primitive {pid}")
    print(f"turns={len(user_turns)}  image_b64={'yes (%d b64 chars)' % len(sample.image_b64) if sample.image_b64 else 'NONE'}")
    for m in sample.messages:
        print(f"  [{m['role']:<9}] {m['content'][:74]}")
    print()
    header = f"{'config':<34} {'verdict':<16} response snippet"
    print(header)
    print("-" * len(header))

    try:
        for c in configs:
            rendered = render(primitive, c)
            responses = await panel.run_attack(
                rendered=rendered, config=c, temperature=0.7, n_trials=1,
            )
            r = responses[0]
            snippet = (r.content or "").replace("\n", " ")[:70]
            if r.error:
                verdict = f"ERROR({r.error[:24]})"
            else:
                try:
                    jr = await judge.judge(
                        rendered=rendered, model_response=r.content or "", primitive=primitive,
                    )
                    verdict = jr.verdict.value
                except Exception as exc:  # noqa: BLE001
                    verdict = f"JUDGE_ERR({type(exc).__name__})"
            print(f"{c.target_model:<34} {verdict:<16} {snippet}")
    finally:
        await panel.aclose()


if __name__ == "__main__":
    asyncio.run(main())
