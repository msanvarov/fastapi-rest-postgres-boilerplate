"""Process-wide async concurrency primitives.

This module is the *single owner* of long-lived concurrency state: bounded
semaphores, the background task supervisor, gather helpers, and threadpool
fan-out for CPU-bound work. Centralising these prevents the common FastAPI
foot-guns:

* Unbounded ``asyncio.gather`` — a slow downstream causes head-of-line blocking
  and OOM. We expose ``gather_with_concurrency`` and ``bounded_map`` instead.
* Fire-and-forget ``asyncio.create_task`` — references can be GC'd mid-flight
  (CPython issue #91887). The :class:`BackgroundTaskSupervisor` strong-refs
  every task and surfaces exceptions to a logger.
* Blocking calls on the event loop — :func:`run_cpu_bound` shuttles work to a
  shared ``ThreadPoolExecutor`` guarded by its own semaphore.

All primitives are constructed lazily inside an event loop (semaphores must
be bound to a loop at creation time, which is why we use ``get_running_loop``).
"""

from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Iterable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

_logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Bounded resources
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class ConcurrencyLimits:
    """Holds the bounded semaphores guarding shared resource pools.

    Instances are loop-bound; we build one per app startup and store it on
    ``app.state.concurrency``. Acquire via :func:`get_limits`.
    """

    db: asyncio.Semaphore
    http: asyncio.Semaphore
    cpu: asyncio.Semaphore
    cpu_executor: ThreadPoolExecutor

    @classmethod
    def create(cls) -> ConcurrencyLimits:
        settings = get_settings()
        return cls(
            db=asyncio.Semaphore(settings.db_semaphore_limit),
            http=asyncio.Semaphore(settings.http_semaphore_limit),
            cpu=asyncio.Semaphore(settings.cpu_semaphore_limit),
            cpu_executor=ThreadPoolExecutor(
                max_workers=settings.cpu_semaphore_limit,
                thread_name_prefix="cpu-bound",
            ),
        )

    async def aclose(self) -> None:
        """Drain in-flight work then shut the executor."""
        self.cpu_executor.shutdown(wait=True, cancel_futures=False)


# ---------------------------------------------------------------------------
# Bounded gather / map
# ---------------------------------------------------------------------------
async def gather_with_concurrency[T](
    limit: int,
    *coros: Awaitable[T],
    return_exceptions: bool = False,
) -> list[T]:
    """Like :func:`asyncio.gather` but caps simultaneous awaitables at ``limit``.

    Use this whenever you fan-out over an unbounded collection — e.g. iterating
    a paginated DB result and calling a downstream per row. The semaphore is
    local to the call, so it composes with the global pool semaphores.
    """
    if limit <= 0:
        msg = "limit must be positive"
        raise ValueError(msg)

    sem = asyncio.Semaphore(limit)

    async def _guarded(coro: Awaitable[T]) -> T:
        async with sem:
            return await coro

    # When ``return_exceptions=True`` the runtime list also contains
    # ``BaseException`` instances. Callers that pass the flag must handle
    # that themselves; the cast keeps the public signature ergonomic.
    return await asyncio.gather(  # type: ignore[return-value]
        *(_guarded(c) for c in coros),
        return_exceptions=return_exceptions,
    )


async def bounded_map[T, U](
    func: Callable[[T], Awaitable[U]],
    items: Iterable[T],
    *,
    limit: int,
    return_exceptions: bool = False,
) -> list[U]:
    """Async ``map`` with a concurrency cap. Preserves input order."""
    return await gather_with_concurrency(
        limit,
        *(func(item) for item in items),
        return_exceptions=return_exceptions,
    )


# ---------------------------------------------------------------------------
# Background task supervisor
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class BackgroundTaskSupervisor:
    """Strong-refs background tasks and logs unhandled exceptions.

    FastAPI's built-in BackgroundTasks runs *after* the response is sent but
    blocks the worker until done. This supervisor is for true fire-and-forget
    work (cache refreshes, metric flushes, webhook fan-out) that must outlive
    the request scope but must not silently swallow errors.
    """

    _tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    _closed: bool = False

    def spawn(
        self,
        coro: Coroutine[Any, Any, Any],
        *,
        name: str | None = None,
    ) -> asyncio.Task[Any]:
        if self._closed:
            msg = "supervisor is closed; cannot spawn new tasks"
            raise RuntimeError(msg)

        task: asyncio.Task[Any] = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._on_done)
        return task

    def _on_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            _logger.error(
                "background_task_failed",
                task_name=task.get_name(),
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    async def aclose(self, *, grace_seconds: float = 10.0) -> None:
        """Cancel pending tasks and wait up to ``grace_seconds`` for them to settle."""
        self._closed = True
        pending = list(self._tasks)
        if not pending:
            return

        _logger.info("background_tasks_draining", count=len(pending))
        for task in pending:
            task.cancel()

        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(
                asyncio.gather(*pending, return_exceptions=True),
                timeout=grace_seconds,
            )


# ---------------------------------------------------------------------------
# CPU-bound offload
# ---------------------------------------------------------------------------
async def run_cpu_bound[**P, R](
    limits: ConcurrencyLimits,
    func: Callable[P, R],
    /,
    *args: P.args,
    **kwargs: P.kwargs,
) -> R:
    """Run a blocking/CPU-bound callable in the shared threadpool under a sem.

    The CPU semaphore matches the executor's max_workers — so callers can't
    queue arbitrarily many jobs while their request waits.
    """
    loop = asyncio.get_running_loop()
    bound = functools.partial(func, *args, **kwargs)
    async with limits.cpu:
        return await loop.run_in_executor(limits.cpu_executor, bound)


# ---------------------------------------------------------------------------
# Decorators / helpers
# ---------------------------------------------------------------------------
def with_semaphore[**P, R](
    semaphore_attr: str,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Decorator: wrap a coroutine so it acquires a named limiter from app state.

    Usage::

        @with_semaphore("http")
        async def call_partner_api(...): ...

    Expected to be used on methods of objects holding a ``limits`` attribute,
    or via :func:`get_limits` inside the wrapped function. The decorator
    pattern is provided for symmetry with sync-world rate-limit decorators.
    """

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            limits = _resolve_limits_from_args(args)
            sem: asyncio.Semaphore = getattr(limits, semaphore_attr)
            async with sem:
                return await func(*args, **kwargs)

        return wrapper

    return decorator


def _resolve_limits_from_args(args: tuple[Any, ...]) -> ConcurrencyLimits:
    for arg in args:
        if isinstance(arg, ConcurrencyLimits):
            return arg
        limits = getattr(arg, "limits", None)
        if isinstance(limits, ConcurrencyLimits):
            return limits
    msg = "with_semaphore: no ConcurrencyLimits found on call args"
    raise RuntimeError(msg)


@asynccontextmanager
async def timeout_after(
    seconds: float,
    *,
    name: str = "operation",
) -> AsyncIterator[None]:
    """Context manager that raises ``TimeoutError`` after ``seconds``.

    Thin wrapper around :func:`asyncio.timeout` that adds structured logging
    on expiry so timeouts show up in the same telemetry as everything else.
    """
    start = time.perf_counter()
    try:
        async with asyncio.timeout(seconds):
            yield
    except TimeoutError:
        elapsed = time.perf_counter() - start
        _logger.warning("operation_timeout", name=name, elapsed_s=round(elapsed, 4))
        raise


__all__ = [
    "BackgroundTaskSupervisor",
    "ConcurrencyLimits",
    "bounded_map",
    "gather_with_concurrency",
    "run_cpu_bound",
    "timeout_after",
    "with_semaphore",
]
