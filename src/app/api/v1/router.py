"""v1 API router — composes endpoint modules."""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, health, ping, users

router = APIRouter()
router.include_router(ping.router)  # /ping
router.include_router(health.router, prefix="/health")
router.include_router(auth.router, prefix="/auth")
router.include_router(users.router, prefix="/users")
