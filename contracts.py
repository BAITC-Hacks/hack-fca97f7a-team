"""Shared boundaries for the initial local training and inference slice."""

from datetime import datetime, timezone

FIRST_ORIGIN = "2026-01-31T18:00:00Z"
FEATURES = ("wind_speed_ms", "temperature_c")
TURBINE_IDS = ("T1", "T2")


class ForecastError(ValueError):
    """Domain failure that future presentation/API adapters can serialize."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict:
        return {"status": "error", "code": self.code, "message": self.message, "trace": []}


def validate_origin(origin: str) -> datetime:
    """Require explicit timezone and an exact UTC hour; never use today's date."""
    if not isinstance(origin, str):
        raise ForecastError("INVALID_INPUT", "origin must be an ISO 8601 string")
    try:
        parsed = datetime.fromisoformat(origin.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ForecastError("INVALID_INPUT", "origin must be a valid ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ForecastError("INVALID_INPUT", "origin requires an explicit timezone")
    parsed = parsed.astimezone(timezone.utc)
    if parsed.minute or parsed.second or parsed.microsecond:
        raise ForecastError("INVALID_INPUT", "origin must align to a UTC hour")
    return parsed
