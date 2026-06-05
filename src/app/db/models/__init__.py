"""ORM models. Import every model here so Alembic autogenerate sees them."""

from app.db.models.user import User

__all__ = ["User"]
