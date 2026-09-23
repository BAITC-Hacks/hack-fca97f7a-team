"""The weather → prediction seam: canonical, validated, downloadable CSV files.

Provider JSON is normalized by weather.py. This module knows nothing about HTTP,
the UI, the estimator, or the explanation model.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import os
import tempfile
from pathlib import Path

from contracts import FEATURES, SITE_IDS, ForecastError, artifact_dir, expected_hours

SCHEMA_VERSION = "weather-features-v1"
COLUMNS = ["turbine_id", "valid_at", *FEATURES]


def _validate_rows(rows: list[dict], turbine_id: str, origin: str, horizon_hours: int) -> list[dict]:
    if turbine_id not in SITE_IDS or horizon_hours not in (24, 48):
        raise ForecastError("DATA_INVALID", "Invalid turbine or horizon for model input.")
    if len(rows) != horizon_hours:
        raise ForecastError("DATA_INVALID", "Model input CSV does not have the requested number of hours.")
    normalized = []
    for row in rows:
        if set(row) != set(COLUMNS) or row["turbine_id"] != turbine_id:
            raise ForecastError("DATA_INVALID", "Model input columns or turbine identity do not match.")
        clean = {"turbine_id": turbine_id, "valid_at": row["valid_at"]}
        for feature in FEATURES:
            try:
                value = row[feature]
                if isinstance(value, bool):
                    raise ValueError("boolean feature")
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError("nonfinite feature")
            except (TypeError, ValueError) as exc:
                raise ForecastError("DATA_INVALID", "Model input features must be finite numbers.") from exc
            clean[feature] = number
        if clean["wind_speed_ms"] < 0:
            raise ForecastError("DATA_INVALID", "Model input wind speed must be nonnegative m/s.")
        normalized.append(clean)
    if [row["valid_at"] for row in normalized] != expected_hours(origin, horizon_hours):
        raise ForecastError("DATA_INVALID", "Model input hours must be unique, ordered and match the requested window.")
    return normalized


def write_model_input(rows: list[dict], turbine_id: str, origin: str, horizon_hours: int) -> dict:
    """Write deterministic CSV bytes atomically and return only portable metadata."""
    canonical = _validate_rows([{**row, "turbine_id": turbine_id} for row in rows],
                               turbine_id, origin, horizon_hours)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(canonical)
    content = stream.getvalue().encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    directory = artifact_dir() / "model_inputs"
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{digest}.csv"
    destination = directory / filename
    # Recreate missing/corrupt artifacts even when the forecast itself is cached.
    if not destination.exists() or destination.read_bytes() != content:
        with tempfile.NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as tmp:
            tmp.write(content)
            temporary = tmp.name
        try:
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return {"schema_version": SCHEMA_VERSION, "filename": filename, "sha256": digest,
            "row_count": len(canonical), "columns": COLUMNS.copy()}


def read_model_input(path: Path, *, turbine_id: str, origin: str, horizon_hours: int,
                     expected_sha256: str) -> list[dict]:
    """Model boundary: inspect exact consumed bytes, schema, site, units and time window."""
    try:
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected_sha256:
            raise ForecastError("DATA_INVALID", "Model input CSV checksum mismatch.")
        reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
        if reader.fieldnames != COLUMNS:
            raise ForecastError("DATA_INVALID", "Model input CSV header must be " + ",".join(COLUMNS))
        rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ForecastError("DATA_INVALID", "Cannot read model input CSV.") from exc
    return _validate_rows(rows, turbine_id, origin, horizon_hours)

