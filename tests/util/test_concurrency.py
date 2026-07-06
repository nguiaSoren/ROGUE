"""Tests for the shared bounded-concurrency / retry sweep harness."""

from __future__ import annotations

import threading
import time

from rogue.util.concurrency import CallError, concurrent_map, retrying


def test_order_aligned_and_correct():
    out = concurrent_map(lambda x: x * x, list(range(20)), concurrency=8, progress_every=0)
    assert out == [x * x for x in range(20)]


def test_actually_concurrent_is_faster_than_sequential():
    # 16 items that each sleep 50ms; at concurrency=8 this is ~2 waves (~0.1s),
    # vs ~0.8s sequential. Generous bound to avoid CI flakiness.
    items = list(range(16))
    t0 = time.monotonic()
    concurrent_map(lambda _: time.sleep(0.05), items, concurrency=8, progress_every=0)
    assert time.monotonic() - t0 < 0.5  # << 16*0.05 = 0.8s sequential


def test_peak_concurrency_is_bounded():
    live = 0
    peak = 0
    lock = threading.Lock()

    def work(_):
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        time.sleep(0.02)
        with lock:
            live -= 1

    concurrent_map(work, list(range(30)), concurrency=5, progress_every=0)
    assert peak <= 5


def test_failed_item_becomes_callerror_not_abort():
    def maybe_fail(x):
        if x == 3:
            raise ValueError("boom")
        return x

    out = concurrent_map(maybe_fail, list(range(6)), concurrency=4, retries=2, progress_every=0)
    assert isinstance(out[3], CallError)
    assert out[3].index == 3 and "boom" in out[3].error
    assert [o for i, o in enumerate(out) if i != 3] == [0, 1, 2, 4, 5]


def test_retry_eventually_succeeds():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    assert retrying(flaky, retries=5, base_delay=0.0)() == "ok"
    assert calls["n"] == 3
