"""Batch-API judging — grade many cells through Anthropic's Message Batches API.

Grading is offline batch work, so the Batch API (flat **50% off**, and prompt
caching still applies inside it) is the natural cost lever for large reproduce
sweeps or re-grades. This module submits one batch of judge requests, polls to
completion, collects verdicts, and — for the cells the primary (Anthropic)
judge REFUSES (``stop_reason="refusal"``) or that error out — falls back to the
permissive secondary judge inline (OpenRouter), exactly like the synchronous
:meth:`JudgeAgent.judge` path. The two share :meth:`JudgeAgent.anthropic_grade_kwargs`
so the batch request is byte-identical to the inline one.

Tradeoff vs the inline judge: a batch can take minutes–24h to finish (usually
fast), so this is for **latency-tolerant** work — overnight reproduce, bulk
re-grades — not interactive demo runs. Fully programmatic: no platform UI.

Typical use::

    jb = JudgeBatch(JudgeAgent())                 # anthropic primary judge
    verdicts = await jb.grade(items)              # {custom_id: JudgeResult}

Spec: ROGUE_PLAN.md §10.2 (judge) + the judge cost-ladder note.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from rogue.reproduce.instantiator import RenderedAttack
from rogue.reproduce.judge import JudgeAgent, JudgeResult
from rogue.schemas import AttackPrimitive

__all__ = ["BatchGradeItem", "JudgeBatch"]

_log = logging.getLogger("rogue.reproduce.judge_batch")


@dataclass(frozen=True)
class BatchGradeItem:
    """One cell to grade. ``custom_id`` must be unique within a batch and is
    how results are mapped back (use the breach_id / cell key)."""

    custom_id: str
    rendered: RenderedAttack
    model_response: str
    primitive: AttackPrimitive


class JudgeBatch:
    """Grade a set of cells via the Anthropic Message Batches API, with the
    same refusal→secondary-judge fallback as the inline :meth:`JudgeAgent.judge`.

    Requires the wrapped judge to be an Anthropic (``anthropic/...``) primary —
    the Batch API is Anthropic-only; the OpenRouter fallback for refused cells
    runs inline (it is rare and not batchable here).
    """

    def __init__(self, judge: JudgeAgent | None = None) -> None:
        self.judge = judge or JudgeAgent()
        if not self.judge.model.startswith("anthropic/"):
            raise ValueError(
                "JudgeBatch needs an Anthropic primary judge (the Batch API is "
                f"Anthropic-only); got model={self.judge.model!r}"
            )

    def _client(self):
        from anthropic import AsyncAnthropic  # noqa: PLC0415

        if self.judge._anthropic_client is None:
            self.judge._anthropic_client = AsyncAnthropic()
        return self.judge._anthropic_client

    def _request(self, item: BatchGradeItem) -> dict:
        user_message = self.judge._build_user_message(
            rendered=item.rendered,
            model_response=item.model_response,
            primitive=item.primitive,
        )
        return {
            "custom_id": item.custom_id,
            "params": self.judge.anthropic_grade_kwargs(user_message),
        }

    async def submit(self, items: list[BatchGradeItem]) -> str:
        """Create the batch; returns the batch id."""
        requests = [self._request(it) for it in items]
        batch = await self._client().messages.batches.create(requests=requests)
        _log.info("submitted judge batch %s (%d requests)", batch.id, len(requests))
        return batch.id

    async def wait(
        self, batch_id: str, poll_interval: float = 15.0, timeout: float = 86_400.0
    ) -> None:
        """Poll until the batch's ``processing_status`` is ``ended``."""
        waited = 0.0
        while True:
            batch = await self._client().messages.batches.retrieve(batch_id)
            if batch.processing_status == "ended":
                _log.info("judge batch %s ended (counts=%s)", batch_id, batch.request_counts)
                return
            if waited >= timeout:
                raise TimeoutError(f"judge batch {batch_id} not done after {timeout}s")
            await asyncio.sleep(poll_interval)
            waited += poll_interval

    def _verdict_from_message(self, message) -> JudgeResult | None:
        """Parse a succeeded batch message → JudgeResult, or None if the judge
        refused / emitted no usable tool-call (caller falls back)."""
        if getattr(message, "stop_reason", None) == "refusal":
            return None
        for block in getattr(message, "content", []) or []:
            if getattr(block, "type", None) == "tool_use":
                data = dict(block.input)
                if data.get("verdict"):
                    return self.judge._validate_verdict(data)
        return None

    async def collect(self, batch_id: str) -> dict[str, JudgeResult | None]:
        """Stream results → ``{custom_id: JudgeResult | None}`` (None = refused /
        errored / unparseable; the caller routes those to the fallback)."""
        out: dict[str, JudgeResult | None] = {}
        async for entry in await self._client().messages.batches.results(batch_id):
            cid = entry.custom_id
            result = entry.result
            if getattr(result, "type", None) == "succeeded":
                try:
                    out[cid] = self._verdict_from_message(result.message)
                except Exception:  # noqa: BLE001 — bad payload → fall back
                    out[cid] = None
            else:
                out[cid] = None  # errored / expired / canceled
        return out

    async def _fallback(self, item: BatchGradeItem) -> JudgeResult:
        """Grade one batch-refused cell via the secondary judge (inline),
        flagging the rationale like :meth:`JudgeAgent.judge` does."""
        user_message = self.judge._build_user_message(
            rendered=item.rendered,
            model_response=item.model_response,
            primitive=item.primitive,
        )
        data = await self.judge._grade_via_openrouter(
            user_message, self.judge.fallback_model
        )
        result = self.judge._validate_verdict(data)
        flag = f"[JUDGE_REFUSED→{self.judge.fallback_model}] "
        return result.model_copy(
            update={"rationale": (flag + result.rationale)[:2_000]}
        )

    async def grade(
        self, items: list[BatchGradeItem], fallback_concurrency: int = 6
    ) -> dict[str, JudgeResult]:
        """End-to-end: submit → wait → collect → fall back on refused cells.

        Returns ``{custom_id: JudgeResult}`` for every item. Cells the primary
        judge refused are re-graded by the secondary judge and flagged
        ``[JUDGE_REFUSED→…]``; cells that still can't be graded are dropped from
        the result (the caller records them as ERROR).
        """
        if not items:
            return {}
        batch_id = await self.submit(items)
        await self.wait(batch_id)
        collected = await self.collect(batch_id)

        by_id = {it.custom_id: it for it in items}
        refused = [by_id[cid] for cid, v in collected.items() if v is None and cid in by_id]
        _log.info(
            "judge batch %s: %d graded by primary, %d refused → secondary",
            batch_id, len(collected) - len(refused), len(refused),
        )

        verdicts: dict[str, JudgeResult] = {
            cid: v for cid, v in collected.items() if v is not None
        }
        if refused:
            sem = asyncio.Semaphore(fallback_concurrency)

            async def _one(it: BatchGradeItem) -> None:
                async with sem:
                    try:
                        verdicts[it.custom_id] = await self._fallback(it)
                    except Exception as exc:  # noqa: BLE001
                        _log.warning("fallback failed for %s: %s", it.custom_id, exc)

            await asyncio.gather(*(_one(it) for it in refused))
        return verdicts
