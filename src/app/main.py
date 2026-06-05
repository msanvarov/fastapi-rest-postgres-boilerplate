"""Application factory + ASGI entrypoint.

Lifespan order matters. Resources are built outside-in and torn down
inside-out:

1. configure logging
2. build concurrency primitives (semaphores, executor)
3. open the DB pool
4. open the shared HTTP client
5. open Redis (used by the rate-limiter)
6. start the background-task supervisor

…the request lifecycle runs in between, then everything reverses on shutdown.

Response serialisation: FastAPI 0.111+ encodes Pydantic models directly to
JSON bytes via Pydantic's Rust core, which is faster than ORJSONResponse —
we don't set a custom default_response_class because doing so now emits a
deprecation warning.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import RequestResponseEndpoint

from app import __version__
from app.api.v1.endpoints.ping import router as ping_router
from app.api.v1.router import router as v1_router
from app.core.concurrency import BackgroundTaskSupervisor, ConcurrencyLimits
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import Database
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_context import RequestContextMiddleware
from app.middleware.timeout import TimeoutMiddleware
from app.utils.http_client import HttpClient


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build and tear down process-wide resources."""
    settings = get_settings()
    configure_logging()
    logger = get_logger("app.lifespan")

    limits = ConcurrencyLimits.create()
    db = await Database(settings, limits).connect()
    http = HttpClient(limits)
    redis_client = redis.from_url(str(settings.redis_url), decode_responses=True)
    supervisor = BackgroundTaskSupervisor()

    # Make everything reachable via deps without module-level globals.
    app.state.settings = settings
    app.state.limits = limits
    app.state.db = db
    app.state.http = http
    app.state.redis = redis_client
    app.state.supervisor = supervisor

    logger.info(
        "application_started",
        env=settings.app_env.value,
        version=__version__,
        debug=settings.app_debug,
    )
    try:
        yield
    finally:
        logger.info("application_shutting_down")
        await supervisor.aclose()
        try:
            await redis_client.aclose()
        except Exception:
            # Best-effort shutdown — don't let a redis hiccup prevent teardown.
            logger.exception("redis_close_failed")
        await http.aclose()
        await db.disconnect()
        await limits.aclose()
        logger.info("application_stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    """ASGI app factory. Importable as ``app.main:create_app`` or used directly."""
    settings = settings or get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        debug=settings.app_debug,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ---- Middleware (outer → inner; reverse of execution order) -----------
    # Trusted host first so spoofed Host headers can't reach inner middleware.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
        )

    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(TimeoutMiddleware, timeout_seconds=settings.request_timeout_seconds)

    if settings.rate_limit_enabled:
        # The middleware needs a redis client built by the lifespan, so we
        # plug a thin function-middleware that calls the limiter's dispatch
        # with the already-running redis instance off app.state.
        @app.middleware("http")
        async def _rate_limit_shim(
            request: Request,
            call_next: RequestResponseEndpoint,
        ) -> Response:
            limiter: RateLimitMiddleware | None = getattr(
                request.app.state,
                "_rate_limit_mw",
                None,
            )
            if limiter is None:
                # ``app`` argument is unused by our dispatch — pass a sentinel.
                limiter = RateLimitMiddleware(
                    app=lambda *_a, **_kw: None,  # type: ignore[arg-type]
                    redis_client=request.app.state.redis,
                    per_minute=settings.rate_limit_per_minute,
                )
                request.app.state._rate_limit_mw = limiter
            return await limiter.dispatch(request, call_next)

    # Request context + access log is the innermost middleware so it sees
    # every other layer's processing in its duration measurement.
    app.add_middleware(RequestContextMiddleware)

    # ---- Routes -----------------------------------------------------------
    app.include_router(v1_router, prefix=settings.api_v1_prefix)

    # Also expose /ping at the root so smoke tooling never has to know about
    # the API version prefix. Both paths return identical payloads.
    app.include_router(ping_router)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "service": settings.app_name,
            "version": __version__,
            "docs": "/docs",
            "health": "/api/v1/health/live",
            "ping": "/ping",
        }

    return app


app = create_app()
