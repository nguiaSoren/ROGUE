"""Resume a stranded judge re-grade batch — no re-spend.

``scripts/calibration/rejudge_batch.py`` submits an Anthropic Message Batch then polls it to
completion with a single long-lived connection. On a flaky network (e.g. the
Korea→us link here) that poll dies on a transient DNS blip *after* the batch is
already submitted/paid — leaving the results stranded on Anthropic (they persist
~29 days) and the live matrix unwritten.

This script recovers that: it polls the *existing* batch with **short, retried,
fresh-client calls** (robust to intermittent DNS — proven to work where the
sustained poll fails), collects the verdicts, falls back to the secondary judge
on refused cells, and writes them to the matrix in drop-resilient chunks. It
NEVER submits a new batch, so there is no additional spend.

    uv run python scripts/calibration/resume_rejudge.py --batch-id msgbatch_xxx           # poll + status, free
    uv run python scripts/calibration/resume_rejudge.py --batch-id msgbatch_xxx --yes     # + collect + write
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy import text as sqltext  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from rogue.db.models import AttackPrimitive as AttackPrimitiveORM  # noqa: E402
from rogue.db.models import BreachResult as BreachResultORM  # noqa: E402
from rogue.reproduce.instantiator import RenderedAttack  # noqa: E402
from rogue.reproduce.judge import JudgeAgent  # noqa: E402
from rogue.reproduce.judge_batch import BatchGradeItem, JudgeBatch  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("rogue.scripts.calibration.resume_rejudge")


def _retry(fn, what: str, tries: int = 10, delay: float = 5.0):
    """Run a short network op with retries (each call makes a fresh request, so
    an intermittent DNS failure is survived rather than killing the whole run)."""
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — network flakiness; retry
            last = exc
            log.warning("%s retry %d/%d: %s: %s", what, i + 1, tries, type(exc).__name__, str(exc)[:90])
            time.sleep(delay)
    raise RuntimeError(f"{what}: exhausted retries") from last


def main(argv: list[str] | None = None) -> int:
    import os

    from anthropic import Anthropic

    p = argparse.ArgumentParser()
    p.add_argument("--batch-id", required=True)
    p.add_argument("--poll-interval", type=float, default=30.0)
    p.add_argument("--yes", action="store_true", help="collect + write to the matrix")
    p.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    args = p.parse_args(argv)

    judge = JudgeAgent()  # default rubric = v3

    def _fresh():  # fresh sync client per call → no stale pooled connection
        return Anthropic()

    # 1) poll to ended with short, retried, fresh-client calls
    while True:
        b = _retry(lambda: _fresh().messages.batches.retrieve(args.batch_id), "retrieve")
        log.info("status=%s counts=%s", b.processing_status, b.request_counts)
        if b.processing_status == "ended":
            break
        time.sleep(args.poll_interval)

    if not args.yes:
        log.info("batch ended — re-run with --yes to collect + write.")
        return 0

    # 2) download the results JSONL in one retried GET, save to disk, parse
    # offline. The SDK's streaming .results() iterator dies mid-stream on the
    # flaky link ("Bad file descriptor"); a single whole-file GET (retried) +
    # local parse is robust, and persisting the file means we never re-fetch.
    import json as _json

    import httpx

    results_path = _REPO_ROOT / "data" / "calibration" / f"batch_results_{args.batch_id}.jsonl"

    def _download() -> str:
        if results_path.exists() and results_path.stat().st_size > 0:
            log.info("using cached results file %s", results_path.name)
            return results_path.read_text()
        b = _fresh().messages.batches.retrieve(args.batch_id)
        resp = httpx.get(
            b.results_url,
            headers={
                "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                "anthropic-version": "2023-06-01",
            },
            timeout=300.0,
        )
        resp.raise_for_status()
        results_path.write_text(resp.text)
        log.info("downloaded %d bytes → %s", len(resp.text), results_path.name)
        return resp.text

    body = _retry(_download, "results-download")
    collected: dict[str, object] = {}
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        entry = _json.loads(line)
        cid = entry["custom_id"]
        res = entry.get("result", {})
        v = None
        if res.get("type") == "succeeded":
            msg = res.get("message", {})
            if msg.get("stop_reason") != "refusal":
                for blk in msg.get("content", []) or []:
                    if blk.get("type") == "tool_use":
                        data = blk.get("input", {})
                        if data.get("verdict"):
                            v = judge._validate_verdict(data)
                            break
        collected[cid] = v
    verdicts = {cid: v for cid, v in collected.items() if v is not None}
    refused = [cid for cid, v in collected.items() if v is None]
    log.info("collected: %d primary verdicts, %d refused/errored", len(verdicts), len(refused))

    # 3) secondary-judge the refused cells inline (small set; flagged like grade())
    if refused:
        eng = create_engine(args.database_url)
        S = sessionmaker(bind=eng)
        from scripts.reproduce.reproduce_once import _orm_to_pydantic_primitive  # noqa: PLC0415

        with S() as s:
            brows = list(
                s.execute(
                    select(BreachResultORM).where(BreachResultORM.breach_id.in_(refused))
                ).scalars()
            )
            prim_orms = list(
                s.execute(
                    select(AttackPrimitiveORM).where(
                        AttackPrimitiveORM.primitive_id.in_({b.primitive_id for b in brows})
                    )
                ).scalars()
            )
            prims = {pp.primitive_id: _orm_to_pydantic_primitive(pp) for pp in prim_orms}
            items = [
                BatchGradeItem(
                    custom_id=b.breach_id,
                    rendered=RenderedAttack(
                        messages=[{"role": "user", "content": b.rendered_payload}],
                        is_multi_turn=False,
                        resolved_slots={},
                        primitive_id=b.primitive_id,
                        deployment_config_id="resume",
                    ),
                    model_response=b.model_response,
                    primitive=prims[b.primitive_id],
                )
                for b in brows
            ]
        jb = JudgeBatch(judge)

        async def _fb_all() -> None:
            sem = asyncio.Semaphore(4)

            async def _one(it: BatchGradeItem) -> None:
                async with sem:
                    try:
                        verdicts[it.custom_id] = await jb._fallback(it)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("fallback failed for %s: %s", it.custom_id, exc)

            await asyncio.gather(*(_one(it) for it in items))

        try:
            asyncio.run(_fb_all())
        except Exception as exc:  # noqa: BLE001
            log.warning("secondary fallback pass failed (refused cells left at prior verdict): %s", exc)

    # 4) write to the matrix in drop-resilient chunks
    eng = create_engine(args.database_url)
    pairs = list(verdicts.items())
    upd = 0
    for i in range(0, len(pairs), 25):
        chunk = pairs[i : i + 25]
        with eng.begin() as conn:
            for bid, v in chunk:
                conn.execute(
                    sqltext(
                        "UPDATE breach_results SET verdict=:vd, judge_rationale=:r, "
                        "judge_confidence=:cf WHERE breach_id=:b"
                    ),
                    {"vd": v.verdict.value, "r": v.rationale[:2000], "cf": v.confidence, "b": bid},
                )
        upd += len(chunk)
    log.info("wrote %d verdicts to breach_results", upd)

    from rogue.db.neon_sync import maybe_auto_sync  # noqa: PLC0415

    maybe_auto_sync(args.database_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
