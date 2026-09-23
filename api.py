"""Compatibility entry point. Prefer uvicorn backend.api:app."""
from backend.api import app

__all__ = ["app"]
