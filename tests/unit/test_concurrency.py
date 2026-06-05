"""Concurrency primitives — these are load-bearing, so we test them directly."""

from __future__ import annotations

import asyncio
import time

import pytest

from app.core.concurrency import (
    BackgroundTaskSupervisor,
    ConcurrencyLimits,
    bounded_map,
    gather_with_concurrency,
    run_cpu_bound,
    timeout_after,
)

pytestmark = pytest.mark.unit


async def test_gather_with_concurrency_caps_inflight():
    in_flight = 0
    peak = 0
    lock = asyncio.Lock()

    async def work(_: int) -> int:
        nonlocal in_flight, peak
        async with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        async with lock:
            in_flight -= 1
        return 1

    results = await gather_with_concurrency(3, *(work(i) for i in range(20)))
    assert sum(results) == 20
    assert peak <= 3


async def test_bounded_map_preserves_order():
    async def square(x: int) -> int:
        await asyncio.sleep(0.001 * (10 - x))  # later items finish first
        return x * x

    out = await bounded_map(square, range(10), limit=4)
    assert out == [i * i for i in range(10)]


async def test_supervisor_logs_exceptions_without_propagating(caplog):
    sup = BackgroundTaskSupervisor()

    async def boom() -> None:
        raise RuntimeError("kaboom")

    task = sup.spawn(boom(), name="boom-task")
    await asyncio.sleep(0)  # let scheduler run
    await asyncio.sleep(0)
    assert task.done()
    # Exception is captured by the supervisor — should not raise to the caller.
    await sup.aclose()


async def test_supervisor_cancels_pending_on_close():
    sup = BackgroundTaskSupervisor()
    started = asyncio.Event()

    async def long_running() -> None:
        started.set()
        await asyncio.sleep(60)

    task = sup.spawn(long_running())
    await started.wait()
    await sup.aclose(grace_seconds=1.0)
    assert task.cancelled()


async def test_run_cpu_bound_respects_semaphore():
    limits = ConcurrencyLimits.create()
    try:
        # Sem is set to cpu_semaphore_limit (default 4). 8 tasks → 2 batches.
        def busy(n: int) -> int:
            time.sleep(0.05)
            return n * n

        start = time.perf_counter()
        results = await asyncio.gather(*(run_cpu_bound(limits, busy, i) for i in range(8)))
        elapsed = time.perf_counter() - start
        assert results == [i * i for i in range(8)]
        # 8 jobs of 50ms with 4 workers ≈ 100ms minimum (two waves).
        assert elapsed >= 0.09
    finally:
        await limits.aclose()


async def test_timeout_after_raises():
    with pytest.raises(TimeoutError):
        async with timeout_after(0.01, name="tiny"):
            await asyncio.sleep(1)
