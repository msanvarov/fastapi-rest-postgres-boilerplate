"""``/ping`` — the cheapest possible signal that the ASGI app is alive.

Distinct from ``/health/live`` and ``/health/ready``:

* **/ping** — zero dependencies, zero allocations beyond the response itself.
  Used by smoke tests after deploy to confirm the container is serving
  traffic. Returns a fixed body so smoke tests can assert on it.
* **/health/live** — also dependency-free, but returns app metadata. Used by
  Kubernetes liveness probes (which restart on failure).
* **/health/ready** — checks downstream dependencies (DB, etc.). Used by
  Kubernetes readiness probes (which pull the pod out of rotation).

Keep this endpoint *boring*. Never add a DB call here.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["ping"])


class PingResponse(BaseModel):
    """Fixed shape — smoke tests pin on it."""

    ping: str = "pong"


@router.get(
    "/ping",
    response_model=PingResponse,
    summary="Smoke-test ping",
    description="Returns `{\"ping\": \"pong\"}`. Zero dependencies.",
)
async def ping() -> PingResponse:
    return PingResponse()
