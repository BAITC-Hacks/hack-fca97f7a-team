"""Local JSON persistence: keep the newest 256 forecasts for at most seven days.

The store is per local artifact directory and needs no database. Missing, expired,
or corrupt files behave as unknown forecast IDs; the client can regenerate them.
"""
from __future__ import annotations

import json
import hashlib
import math
import os
import re
import tempfile
import threading
import time
from pathlib import Path

from contracts import ForecastError, artifact_dir, expected_hours

MAX_FILES = 256
MAX_AGE_SECONDS = 7 * 24 * 60 * 60
_ID = re.compile(r"[0-9a-f]{64}\Z")
_LOCK = threading.RLock()
_CSV_COLUMNS = ["turbine_id", "valid_at", "wind_speed_ms", "temperature_c"]


def _directory() -> Path:
    return artifact_dir() / "forecasts"


def _valid(forecast_id: str, result: object) -> bool:
    if not isinstance(forecast_id, str) or not _ID.fullmatch(forecast_id):
        return False
    if not isinstance(result, dict) or result.get("status") != "ok":
        return False
    if result.get("fingerprint") != f"sha256:{forecast_id}":
        return False
    if result.get("turbine_id") not in ("T1", "T2"):
        return False
    if result.get("mode") not in ("fixture", "archive", "live"):
        return False
    if any(not isinstance(result.get(key), str) or not result[key]
           for key in ("timezone", "run_id", "model_id", "train_last_interval_start")):
        return False
    if not isinstance(result.get("weather_provenance"), dict) or not result["weather_provenance"].get("provenance_status"):
        return False
    if not isinstance(result.get("trace"), list):
        return False
    horizon = result.get("horizon_hours")
    hours = result.get("hours")
    if type(horizon) is not int or horizon not in (24, 48) or not isinstance(hours, list) or len(hours) != horizon:
        return False
    try:
        valid_times = expected_hours(result.get("origin"), horizon)
    except ForecastError:
        return False
    for index, hour in enumerate(hours, 1):
        if (not isinstance(hour, dict) or hour.get("lead_hour") != index
                or hour.get("valid_at") != valid_times[index - 1]):
            return False
        for key in ("wind_speed_ms", "temperature_c", "power_norm"):
            value = hour.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                return False
        if not 0 <= hour["power_norm"] <= 1:
            return False
        if hour["wind_speed_ms"] < 0:
            return False
    metadata = result.get("model_input")
    if not isinstance(metadata, dict) or metadata.get("schema_version") != "weather-features-v1":
        return False
    digest = metadata.get("sha256")
    if (not isinstance(digest, str) or not _ID.fullmatch(digest)
            or metadata.get("filename") != f"{digest}.csv"
            or metadata.get("row_count") != horizon
            or metadata.get("columns") != _CSV_COLUMNS):
        return False
    analysis = result.get("analysis")
    if not isinstance(analysis, dict) or not isinstance(analysis.get("warnings"), list):
        return False
    if not all(isinstance(warning, str) for warning in analysis["warnings"]):
        return False
    for key in ("peak_power_norm", "min_power_norm"):
        value = analysis.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            return False
    if analysis.get("peak_at") not in valid_times or analysis.get("min_at") not in valid_times:
        return False
    clipped = analysis.get("clipped_count")
    if type(clipped) is not int or not 0 <= clipped <= horizon:
        return False
    return True


def _digest(result: dict) -> str:
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False,
                         sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _trim(directory: Path) -> None:
    now = time.time()
    files = []
    for path in directory.glob("*.json"):
        if not _ID.fullmatch(path.stem) or path.is_symlink():
            continue
        try:
            mtime = path.stat().st_mtime
            if now - mtime > MAX_AGE_SECONDS:
                path.unlink()
            else:
                files.append((mtime, path))
        except OSError:
            continue
    for _, path in sorted(files, reverse=True)[MAX_FILES:]:
        try:
            path.unlink()
        except OSError:
            pass


def save(forecast_id: str, result: dict) -> None:
    """Atomically save an API result; completed forecasts only."""
    if not _valid(forecast_id, result):
        raise ValueError("invalid completed forecast")
    envelope = {"version": 1, "sha256": _digest(result), "result": result}
    data = json.dumps(envelope, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    with _LOCK:
        directory = _directory()
        directory.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, prefix=".forecast-", suffix=".tmp", delete=False) as handle:
                temporary = handle.name
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, directory / f"{forecast_id}.json")
            temporary = None
            _trim(directory)
        finally:
            if temporary is not None:
                try:
                    Path(temporary).unlink()
                except FileNotFoundError:
                    pass


def load(forecast_id: str) -> dict | None:
    """Return an unexpired, validated result, including older JSON with baseline fields."""
    if not isinstance(forecast_id, str) or not _ID.fullmatch(forecast_id):
        return None
    path = _directory() / f"{forecast_id}.json"
    with _LOCK:
        try:
            if path.is_symlink() or time.time() - path.stat().st_mtime > MAX_AGE_SECONDS:
                return None
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            return None
    if not isinstance(envelope, dict) or type(envelope.get("version")) is not int or envelope["version"] != 1:
        return None
    result = envelope.get("result")
    try:
        if not _valid(forecast_id, result):
            return None
        return result if envelope.get("sha256") == _digest(result) else None
    except (ValueError, TypeError, OverflowError):
        return None
