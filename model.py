"""Compatibility for locally saved legacy model pickles. New code uses backend.ml.model."""
from backend.ml.model import ModelBundle, PowerModel

__all__ = ["ModelBundle", "PowerModel"]
