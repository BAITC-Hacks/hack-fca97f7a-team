"""UI-independent boundaries shared by the three workstreams."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, TypedDict

ROOT = Path(__file__).resolve().parent
FIRST_ORIGIN = "2026-01-31T18:00:00Z"
SITE_TIMEZONE = "Asia/Almaty"
FEATURES = ["wind_speed_ms", "temperature_c"]
SITE_IDS = ("T1", "T2")
CSV_FIELDS = ["turbine_id", "origin", "valid_at", "lead_hour", "power_norm",
              "baseline_norm", "run_id", "model_id", "mode", "provenance_status"]


class ForecastRequest(TypedDict):
    turbine_id: str
    origin: str
    horizon_hours: int
    mode: Literal["fixture", "archive"]


class WeatherRow(TypedDict):
    valid_at: str
    wind_speed_ms: float
    temperature_c: float


class WeatherBundle(TypedDict):
    manifest: dict
    rows: list[WeatherRow]


class Explanation(TypedDict):
    text: str
    backend: Literal["template", "llm"]
    forecast_fingerprint: str
    warning: str | None


class ForecastError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", str(ROOT / "data")))


def artifact_dir() -> Path:
    return Path(os.getenv("ARTIFACT_DIR", str(ROOT / "artifacts")))


def fixture_dir() -> Path:
    return Path(os.getenv("FIXTURE_DIR", str(ROOT / "fixtures")))


def utc_time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() != timedelta(0):
            raise ValueError("UTC offset required")
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ForecastError("INVALID_INPUT", f"Expected UTC timestamp, got {value!r}.") from exc


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def validate_request(request: dict) -> ForecastRequest:
    if not isinstance(request, dict) or set(request) != {"turbine_id", "origin", "horizon_hours", "mode"}:
        raise ForecastError("INVALID_INPUT", "Request must contain turbine_id, origin, horizon_hours and mode.")
    if request["turbine_id"] not in SITE_IDS:
        raise ForecastError("INVALID_INPUT", "Select a registered turbine (T1 or T2).")
    if type(request["horizon_hours"]) is not int or request["horizon_hours"] not in (24, 48):
        raise ForecastError("INVALID_INPUT", "Horizon must be 24 or 48 hours.")
    if request["mode"] not in ("fixture", "archive"):
        raise ForecastError("INVALID_INPUT", "Mode must be fixture or archive.")
    origin = utc_time(request["origin"])
    if origin.minute or origin.second or origin.microsecond:
        raise ForecastError("INVALID_INPUT", "Forecast origin must be aligned to a UTC hour.")
    if origin < utc_time(FIRST_ORIGIN):
        raise ForecastError("INVALID_INPUT", "Origin precedes the frozen model cutoff; retrain for earlier origins.")
    return {**request, "origin": iso(origin)}


def expected_hours(origin: str, horizon: int) -> list[str]:
    start = utc_time(origin)
    return [iso(start + timedelta(hours=i)) for i in range(1, horizon + 1)]


def fingerprint(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def forecast_csv(result: dict) -> str:
    if result.get("status") != "ok":
        raise ForecastError("INVALID_INPUT", "Only successful forecasts can be exported.")
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for hour in result["hours"]:
        row = {key: result[key] for key in ("turbine_id", "origin", "run_id", "model_id", "mode")}
        row.update({key: hour[key] for key in ("valid_at", "lead_hour", "power_norm", "baseline_norm")})
        row["provenance_status"] = result["weather_provenance"]["provenance_status"]
        writer.writerow(row)
    return output.getvalue()

