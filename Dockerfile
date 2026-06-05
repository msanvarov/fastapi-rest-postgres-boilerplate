# syntax=docker/dockerfile:1.7

# ---------------------------------------------------------------------------
# Builder — install deps + the project into a virtualenv under /opt/venv.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# uv binary from the official image — fastest install on the planet.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

WORKDIR /app

# Resolve and install deps first — cached separately from the source tree
# so app code changes don't bust the dependency layer.
COPY pyproject.toml uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Now copy the project and install it.
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---------------------------------------------------------------------------
# Runtime — tiny, non-root, copies only the venv + source.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src

RUN groupadd --system --gid 1000 app \
    && useradd  --system --uid 1000 --gid app --home-dir /app --shell /sbin/nologin app \
    && apt-get update \
    && apt-get install -y --no-install-recommends curl tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder --chown=app:app /opt/venv /opt/venv
COPY --from=builder --chown=app:app /app/src /app/src
COPY --from=builder --chown=app:app /app/alembic /app/alembic
COPY --from=builder --chown=app:app /app/alembic.ini /app/alembic.ini

USER app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --retries=3 --start-period=10s \
    CMD curl --fail --silent http://localhost:8000/api/v1/health/live || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
# Gunicorn manages process lifecycle; uvicorn workers do the actual ASGI work.
# Worker count: tune via $WORKERS env (default 2 * cores + 1 for IO-bound).
CMD ["sh", "-c", "exec gunicorn app.main:app \
    --bind 0.0.0.0:8000 \
    --workers ${WORKERS:-4} \
    --worker-class uvicorn.workers.UvicornWorker \
    --worker-tmp-dir /dev/shm \
    --graceful-timeout 30 \
    --timeout 60 \
    --keep-alive 5 \
    --access-logfile - \
    --error-logfile -"]
