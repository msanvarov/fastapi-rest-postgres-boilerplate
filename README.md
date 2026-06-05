# FastAPI Async Boilerplate

A production-grade FastAPI starter with PostgreSQL, async SQLAlchemy 2.0,
explicit concurrency limits, and the tooling you actually want on day one.

## Highlights

- **uv** for package management, **ruff** for lint + format, **mypy --strict**
  for typing, **pytest** for tests, **pre-commit** for git hooks (incl.
  `gitleaks` for secret scanning and `conventional-pre-commit` for commit
  message hygiene).
- **Async-first**: SQLAlchemy 2.0 + asyncpg, `httpx.AsyncClient` with HTTP/2,
  Redis-backed sliding-window rate limiting, `structlog` with context-vars
  that flow across `await` boundaries.
- **Bounded concurrency**: process-wide `asyncio.Semaphore` instances guard
  DB connections, outbound HTTP, and a CPU-bound `ThreadPoolExecutor`.
  Helpers (`gather_with_concurrency`, `bounded_map`, `run_cpu_bound`,
  `BackgroundTaskSupervisor`, `timeout_after`) make the safe path the
  default — see `src/app/core/concurrency.py`.
- **Clean architecture**: `endpoints → services → repositories → models`.
  Services own transaction boundaries via an explicit `UnitOfWork`.
- **Observability**: per-request `X-Request-ID`, structured access logs,
  `/health/live` + `/health/ready` for k8s probes, stable JSON error envelope.
- **Hardening**: Argon2id passwords (offloaded to a thread-pool), JWT access
  + refresh with rotation, trusted-host + CORS + gzip middleware, timeout
  middleware that converts hangs to `504 Gateway Timeout`.
- **Ops**: multi-stage non-root Dockerfile (~80 MB), gunicorn + uvicorn
  workers, Alembic with async env, GitHub Actions CI matrix.

## Project layout

```
src/app
├── api/v1            # versioned routers + per-resource endpoints
├── core              # config, logging, security, concurrency primitives
├── db                # async engine, session, UoW, models, base
├── middleware        # request-id, timeout, rate-limit
├── repositories      # data access — no business rules
├── services          # business logic — own the transaction
├── schemas           # pydantic v2 request/response models
└── utils             # http client, etc.
```

## Quickstart

```bash
# 1. Install deps and git hooks
make install
make env          # copies .env.example -> .env
make hooks

# 2. Boot Postgres + Redis
make db-up

# 3. Migrate + run
make migrate
make run          # http://localhost:8000/docs
```

## Common tasks

| Command            | Action                                  |
| ------------------ | --------------------------------------- |
| `make fmt`         | Format + autofix with ruff              |
| `make check`       | Lint + type-check                       |
| `make test`        | Pytest with coverage                    |
| `make migration m="..."` | Generate a new Alembic revision   |
| `make migrate`     | Apply pending migrations                |
| `make docker-up`   | Run the full stack in Docker            |

## Concurrency model — the parts to read first

| Primitive                    | What it guards                                          |
| ---------------------------- | ------------------------------------------------------- |
| `ConcurrencyLimits.db`       | DB connections in flight per worker                     |
| `ConcurrencyLimits.http`     | Outbound HTTP calls per worker                          |
| `ConcurrencyLimits.cpu` + executor | CPU-bound work (Argon2, hashing, image processing) |
| `gather_with_concurrency`    | Bounded `asyncio.gather` — never unbounded fan-out      |
| `BackgroundTaskSupervisor`   | Strong-refs fire-and-forget tasks; logs failures        |
| `timeout_after` + middleware | Per-coroutine and per-request deadlines                 |

Open `src/app/core/concurrency.py` and `src/app/services/user_service.py`
for the canonical usage examples — registration hashes the password via
`run_cpu_bound` *outside* the DB transaction so we never hold a connection
while burning CPU.

## Environment variables

See `.env.example` for the full list. Key knobs:

- `DB_SEMAPHORE_LIMIT` — concurrent DB-bound coroutines per worker
- `HTTP_SEMAPHORE_LIMIT` — concurrent outbound HTTP per worker
- `CPU_SEMAPHORE_LIMIT` — threadpool size for CPU-bound work
- `REQUEST_TIMEOUT_SECONDS` — per-request deadline
- `RATE_LIMIT_PER_MINUTE` — sliding-window cap per client identity

## Testing

```bash
make test          # all
make test-unit     # unit only (no DB)
make test-int     # integration (needs Postgres+Redis)
```

Integration tests boot the full ASGI app via `httpx.ASGITransport` and run
against the Postgres in `docker compose` (locally) or the GitHub Actions
service container (CI).

## License

MIT.
