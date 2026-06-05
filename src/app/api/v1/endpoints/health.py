"""Health-check endpoints.

* ``/live``  — process is up. Returns 200 unconditionally; used by k8s liveness.
* ``/ready`` — DB is reachable. Used by k8s readiness; returning 503 here
  pulls the pod out of rotation without killing it.

Both run their checks in parallel via :func:`asyncio.gather` so a slow
dependency doesn't add to the other's latency.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from app import __version__
from app.api.deps import DbDep
from app.core.config import Settings, get_settings

router = APIRouter(tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, bool]


@router.get("/live", response_model=LivenessResponse)
async def liveness(
    settings: Annotated[Settings, Depends(get_settings)],
) -> LivenessResponse:
    return LivenessResponse(service=settings.app_name, version=__version__)


@router.get("/ready", response_model=ReadinessResponse)
async def readiness(db: DbDep, response: Response) -> ReadinessResponse:
    # Parallelise checks — when we add more dependencies (cache, queue, etc.)
    # the total cost stays bounded by the slowest one.
    (db_ok,) = await asyncio.gather(db.healthcheck())
    checks = {"database": db_ok}
    all_ok = all(checks.values())
    response.status_code = status.HTTP_200_OK if all_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ok" if all_ok else "degraded", checks=checks)
