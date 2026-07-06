"""Bounded-concurrency, auto-retrying map for API sweeps — stop hand-rolling it.

Every paid sweep has the same shape: call an API once per item over hundreds or
thousands of *independent* items where the bottleneck is network latency, not CPU
(minting corpora, leakage runs, transfer tests, judging through a provider with no
batch API). Done sequentially that is hours; with bounded concurrency it is minutes.
Done without retries it dies on the first 429 / timeout / 5xx and you lose the whole
run. This is the one reusable harness for that shape, so no script reinvents it (and
gets it subtly wrong, or buffers its progress invisibly) again.

Provider-agnostic: the worker function makes whatever call (OpenAI, OpenRouter via the
openai SDK, Anthropic, ``requests``, ...); this owns only concurrency + retry/backoff
+ flushed progress + not letting one failed item kill the sweep. Thread-based, so it
works with any *sync* client (the GIL is released during network I/O, and the OpenAI /
Anthropic clients are thread-safe). For already-async code use :func:`gather_bounded`.

Typical use::

    from rogue.util.concurrency import concurrent_map, CallError
    outs = concurrent_map(lambda c: agent_call(client, c), cases,
                          concurrency=12, label="agent")
    ok = [o for o in outs if not isinstance(o, CallError)]   # outs[i] aligns to cases[i]

Design choices worth knowing:
  * results are **order-aligned** to the input (outs[i] is for items[i]).
  * a failed item (exhausted every retry) becomes a :class:`CallError` sentinel in
    place rather than raising — one bad row never aborts a 1000-row sweep (flip with
    ``raise_on_error=True`` if you want fail-fast).
  * progress prints **flushed** so a backgrounded sweep is actually observable.
  * set the per-call timeout on the *client* (e.g. ``OpenAI(timeout=60)``) for true
    cancellation; a thread-pool future timeout cannot cancel an in-flight socket read.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Sequence, TypeVar

T = TypeVar("T")
R = TypeVar("R")

__all__ = ["CallError", "retrying", "concurrent_map", "gather_bounded"]


@dataclass(frozen=True)
class CallError:
    """An item that failed every retry. Filter with ``isinstance(x, CallError)``."""

    index: int
    error: str
    attempts: int


def retrying(
    fn: Callable[..., R],
    *,
    retries: int = 3,
    backoff: float = 1.5,
    base_delay: float = 1.0,
    max_backoff: float = 30.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[..., R]:
    """Wrap ``fn`` so it retries on ``retry_on`` with exponential backoff, then
    re-raises the last error. Standalone-usable; :func:`concurrent_map` uses it."""

    def wrapped(*args, **kwargs):  # type: ignore[no-untyped-def]
        delay = base_delay
        last: BaseException | None = None
        for attempt in range(1, max(1, retries) + 1):
            try:
                return fn(*args, **kwargs)
            except retry_on as exc:  # noqa: PERF203 — retry is the point
                last = exc
                if attempt >= retries:
                    break
                time.sleep(min(delay, max_backoff))
                delay *= backoff
        assert last is not None
        raise last

    return wrapped


def concurrent_map(
    fn: Callable[[T], R],
    items: Sequence[T],
    *,
    concurrency: int = 8,
    retries: int = 3,
    backoff: float = 1.5,
    max_backoff: float = 30.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    progress_every: int = 25,
    label: str = "calls",
    raise_on_error: bool = False,
) -> list[R | CallError]:
    """Run ``fn(item)`` over ``items`` with bounded thread concurrency + retry/backoff.

    Returns a list aligned to ``items``; an item that fails every retry holds a
    :class:`CallError` (unless ``raise_on_error=True``, which re-raises). Prints a
    flushed ``label: done/total (rate, failed)`` line every ``progress_every``.
    """
    items = list(items)
    n = len(items)
    if n == 0:
        return []
    worker = retrying(
        fn, retries=retries, backoff=backoff,
        max_backoff=max_backoff, retry_on=retry_on,
    )
    results: list[R | CallError] = [None] * n  # type: ignore[list-item]

    def _run(i: int, item: T):  # type: ignore[no-untyped-def]
        try:
            return i, worker(item)
        except Exception as exc:  # exhausted retries -> sentinel, keep the sweep alive
            return i, CallError(i, f"{type(exc).__name__}: {exc}"[:300], retries)

    done = 0
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        futures = [ex.submit(_run, i, it) for i, it in enumerate(items)]
        for fut in as_completed(futures):
            i, res = fut.result()
            results[i] = res
            if raise_on_error and isinstance(res, CallError):
                raise RuntimeError(f"{label}[{i}] failed every retry: {res.error}")
            done += 1
            if progress_every and (done % progress_every == 0 or done == n):
                elapsed = max(1e-9, time.monotonic() - t0)
                errs = sum(1 for r in results if isinstance(r, CallError))
                print(
                    f"  {label}: {done}/{n}  ({done / elapsed:.1f}/s, {errs} failed)",
                    flush=True,
                )
    return results


async def gather_bounded(coro_thunks, *, concurrency: int = 8):
    """Async sibling of :func:`concurrent_map` for code that is already async.

    ``coro_thunks``: an iterable of zero-arg callables each returning a coroutine
    (thunks, not bare coroutines, so nothing starts until a slot is free). Returns
    results in order; an exception is returned in place (never raised), like
    ``asyncio.gather(return_exceptions=True)`` but with a concurrency cap.
    """
    import asyncio

    sem = asyncio.Semaphore(max(1, concurrency))

    async def _run(thunk):
        async with sem:
            try:
                return await thunk()
            except Exception as exc:  # noqa: BLE001 — return in place, never abort
                return exc

    thunks = list(coro_thunks)
    return await asyncio.gather(*[_run(t) for t in thunks])
