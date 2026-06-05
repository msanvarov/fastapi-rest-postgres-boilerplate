"""Application package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("fastapi-async-boilerplate")
except PackageNotFoundError:  # pragma: no cover - editable install fallback
    __version__ = "0.0.0+local"
