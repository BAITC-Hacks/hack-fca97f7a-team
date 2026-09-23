"""Cache retrospective Open-Meteo forecasts for training; never archive evidence.

The Historical Forecast API stitches early hours of successive model runs. It
does not prove when a value became available for a particular forecast origin.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pandas as pd

from backend.core.contracts import FIRST_ORIGIN, artifact_dir, utc_time
from backend.adapters.weather import SITES

URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
MODEL = "ecmwf_ifs"
FIELDS = ("turbine_id", "timestamp", "wind_speed_ms", "temperature_c")
FIRST_DATE = date(2024, 1, 1)
LAST_DATE = date(2026, 1, 31)
_HOUR = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:00(?::00)?(?:Z)?$")


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_once(path: Path, raw: bytes) -> None:
    """Never overwrite an existing cache entry with different bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError(f"Cache entry changed: {path}")
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".weather-", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        if path.exists():
            if path.read_bytes() != raw:
                raise ValueError(f"Cache entry changed: {path}")
        else:
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_output(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".weather-", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _months(start: date, end: date):
    current = start
    while current <= end:
        next_month = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
        last = min(end, next_month - timedelta(days=1))
        yield current, last
        current = last + timedelta(days=1)


def _params(site: dict, start: date, end: date) -> dict:
    return {"latitude": site["latitude"], "longitude": site["longitude"],
            "models": MODEL, "hourly": "temperature_2m,wind_speed_10m",
            "wind_speed_unit": "ms", "temperature_unit": "celsius",
            "timezone": "UTC", "start_date": start.isoformat(), "end_date": end.isoformat()}


def _request_identity(site: dict, params: dict) -> dict:
    return {"url": URL, "turbine_id": site["turbine_id"], "params": params}


def _load_or_fetch(site: dict, start: date, end: date, output_dir: Path,
                   *, cache_only: bool, client: httpx.Client) -> tuple[bytes, dict]:
    identity = _request_identity(site, _params(site, start, end))
    key = _sha(_json_bytes(identity))
    index_path = output_dir / "requests" / f"{key}.json"
    if index_path.exists():
        record = json.loads(index_path.read_bytes(), parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))
        if (record.get("request") != identity
                or record.get("provenance_status") != "retrospective_forecast_archive"
                or record.get("availability_at_origin") != "UNVERIFIED"
                or not isinstance(record.get("retrieved_at"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", record.get("raw_sha256", ""))):
            raise ValueError(f"Invalid request cache index: {index_path}")
        raw_path = output_dir / "raw" / f"{record['raw_sha256']}.json"
        raw = raw_path.read_bytes()
        if _sha(raw) != record["raw_sha256"]:
            raise ValueError(f"Corrupt weather cache: {raw_path}")
        data = json.loads(raw)
        if (record.get("grid_latitude") != data.get("latitude")
                or record.get("grid_longitude") != data.get("longitude")):
            raise ValueError(f"Weather cache grid mismatch: {raw_path}")
        return raw, record
    if cache_only:
        raise FileNotFoundError(f"No cached historical forecast for {site['turbine_id']} {start}..{end}")
    response = client.get(URL, params=identity["params"], timeout=45.0, follow_redirects=False)
    response.raise_for_status()
    raw = response.content
    # Parse and validate before caching the response as a successful request.
    _parse_response(raw, site, start, end)
    digest = _sha(raw)
    retrieved = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    record = {"request": identity, "raw_sha256": digest, "retrieved_at": retrieved,
              "grid_latitude": None, "grid_longitude": None,
              "provenance_status": "retrospective_forecast_archive",
              "availability_at_origin": "UNVERIFIED"}
    data = json.loads(raw)
    record["grid_latitude"] = data["latitude"]
    record["grid_longitude"] = data["longitude"]
    _write_once(output_dir / "raw" / f"{digest}.json", raw)
    _write_once(index_path, _json_bytes(record))
    return raw, record


def _parse_response(raw: bytes, site: dict, start: date, end: date) -> list[dict]:
    def reject_constant(value):
        raise ValueError(f"Non-finite JSON value: {value}")

    data = json.loads(raw, parse_constant=reject_constant)
    if not isinstance(data, dict):
        raise ValueError("Weather response must be an object")
    lat, lon = data.get("latitude"), data.get("longitude")
    if (type(lat) not in (float, int) or type(lon) not in (float, int)
            or not math.isfinite(lat) or not math.isfinite(lon)
            or not -90 <= lat <= 90 or not -180 <= lon <= 180
            or abs(lat - site["latitude"]) > 1 or abs(lon - site["longitude"]) > 1):
        raise ValueError("Invalid or distant provider grid coordinates")
    units, hourly = data.get("hourly_units"), data.get("hourly")
    if (data.get("timezone") not in ("GMT", "UTC")
            or type(data.get("utc_offset_seconds")) is not int or data["utc_offset_seconds"] != 0
            or not isinstance(units, dict) or not isinstance(hourly, dict)
            or units.get("time") not in ("iso8601", "ISO8601")
            or units.get("wind_speed_10m") != "m/s" or units.get("temperature_2m") != "°C"):
        raise ValueError("Unexpected weather units or timezone")
    stamps, winds, temps = (hourly.get(key) for key in ("time", "wind_speed_10m", "temperature_2m"))
    expected_count = (end - start).days * 24 + 24
    if (not all(isinstance(values, list) for values in (stamps, winds, temps))
            or not len(stamps) == len(winds) == len(temps) == expected_count):
        raise ValueError("Missing or extra weather hours")
    rows = []
    first = datetime.combine(start, datetime.min.time(), timezone.utc)
    for index, (stamp, wind, temp) in enumerate(zip(stamps, winds, temps)):
        if not isinstance(stamp, str) or not _HOUR.fullmatch(stamp):
            raise ValueError("Invalid weather timestamp")
        canonical = (first + timedelta(hours=index)).isoformat(timespec="seconds").replace("+00:00", "Z")
        if stamp.rstrip("Z") not in (canonical.removesuffix("Z")[:-3], canonical.removesuffix("Z")):
            raise ValueError("Missing, duplicate or unordered weather hour")
        if (type(wind) not in (int, float) or type(temp) not in (int, float)
                or not math.isfinite(wind) or not math.isfinite(temp) or wind < 0):
            raise ValueError("Invalid weather measurements")
        rows.append({"turbine_id": site["turbine_id"], "timestamp": canonical,
                     "wind_speed_ms": float(wind), "temperature_c": float(temp)})
    return rows


def fetch_training_weather(start: date, end: date, output_dir: Path,
                           *, cache_only: bool = False, client: httpx.Client | None = None) -> dict:
    """Fetch/cache requested UTC calendar days and export only completed pre-origin hours."""
    if not FIRST_DATE <= start <= end <= LAST_DATE:
        raise ValueError(f"Date range must be within {FIRST_DATE}..{LAST_DATE}")
    output_dir = Path(output_dir)
    own_client = client is None
    if own_client:
        client = httpx.Client()
    rows, requests = [], []
    try:
        for site in SITES:
            for chunk_start, chunk_end in _months(start, end):
                raw, record = _load_or_fetch(site, chunk_start, chunk_end, output_dir,
                                             cache_only=cache_only, client=client)
                chunk_rows = _parse_response(raw, site, chunk_start, chunk_end)
                rows.extend(row for row in chunk_rows
                            if utc_time(row["timestamp"]) + timedelta(hours=1) <= utc_time(FIRST_ORIGIN))
                requests.append(record)
    finally:
        if own_client:
            client.close()
    rows.sort(key=lambda row: (row["turbine_id"], row["timestamp"]))
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    csv_bytes = out.getvalue().encode("utf-8")
    manifest = {"version": 1, "source": "Open-Meteo Historical Forecast API",
                "source_url": URL, "model": MODEL, "start_date": start.isoformat(),
                "end_date": end.isoformat(), "training_cutoff": FIRST_ORIGIN,
                "weather_kind": "retrospective_stitched_forecast_archive",
                "availability_at_origin": "UNVERIFIED",
                "not_runtime_archive_evidence": True,
                "wind_height_m": 10, "wind_height_status": "proxy_not_hub_height",
                "temperature_height_m": 2, "wind_unit": "m/s", "temperature_unit": "°C",
                "timezone": "UTC", "interpolation_by_adapter": "none",
                "csv_file": "training_weather.csv", "csv_sha256": _sha(csv_bytes),
                "row_count": len(rows), "excluded_uncompleted_hours":
                sum((end_chunk - start_chunk).days * 24 + 24 for start_chunk, end_chunk in _months(start, end))
                * len(SITES) - len(rows), "requests": requests}
    _write_output(output_dir / "training_weather.csv", csv_bytes)
    _write_output(output_dir / "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8") + b"\n")
    return manifest


def load_training_weather(output_dir: Path) -> tuple[pd.DataFrame, dict]:
    """Verify exported CSV against cached HTTP bytes and fixed site/request identity."""
    output_dir = Path(output_dir)
    manifest = json.loads((output_dir / "manifest.json").read_bytes())
    if (not isinstance(manifest, dict) or type(manifest.get("version")) is not int
            or manifest["version"] != 1 or manifest.get("source_url") != URL
            or manifest.get("model") != MODEL
            or manifest.get("source") != "Open-Meteo Historical Forecast API"
            or manifest.get("weather_kind") != "retrospective_stitched_forecast_archive"
            or manifest.get("availability_at_origin") != "UNVERIFIED"
            or manifest.get("not_runtime_archive_evidence") is not True
            or manifest.get("training_cutoff") != FIRST_ORIGIN
            or manifest.get("csv_file") != "training_weather.csv"
            or manifest.get("wind_unit") != "m/s" or manifest.get("temperature_unit") != "°C"
            or manifest.get("timezone") != "UTC" or manifest.get("wind_height_m") != 10
            or manifest.get("temperature_height_m") != 2):
        raise ValueError("Invalid training weather provenance manifest")
    start, end = date.fromisoformat(manifest["start_date"]), date.fromisoformat(manifest["end_date"])
    if not FIRST_DATE <= start <= end <= LAST_DATE:
        raise ValueError("Training weather date range is invalid")
    expected_requests = [(site, chunk_start, chunk_end) for site in SITES
                         for chunk_start, chunk_end in _months(start, end)]
    records = manifest.get("requests")
    if not isinstance(records, list) or len(records) != len(expected_requests):
        raise ValueError("Training weather request coverage is incomplete")
    verified_rows = []
    for record, (site, chunk_start, chunk_end) in zip(records, expected_requests):
        identity = _request_identity(site, _params(site, chunk_start, chunk_end))
        if (not isinstance(record, dict) or record.get("request") != identity
                or record.get("provenance_status") != "retrospective_forecast_archive"
                or record.get("availability_at_origin") != "UNVERIFIED"
                or not isinstance(record.get("retrieved_at"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", record.get("raw_sha256", ""))):
            raise ValueError("Training weather request identity or provenance mismatch")
        raw = (output_dir / "raw" / f"{record['raw_sha256']}.json").read_bytes()
        if _sha(raw) != record["raw_sha256"]:
            raise ValueError("Training weather raw checksum mismatch")
        data = json.loads(raw)
        if (record.get("grid_latitude") != data.get("latitude")
                or record.get("grid_longitude") != data.get("longitude")):
            raise ValueError("Training weather grid mismatch")
        verified_rows.extend(row for row in _parse_response(raw, site, chunk_start, chunk_end)
                             if utc_time(row["timestamp"]) + timedelta(hours=1) <= utc_time(FIRST_ORIGIN))
    verified_rows.sort(key=lambda row: (row["turbine_id"], row["timestamp"]))
    csv_bytes = (output_dir / "training_weather.csv").read_bytes()
    if _sha(csv_bytes) != manifest.get("csv_sha256"):
        raise ValueError("Training weather CSV checksum mismatch")
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8")))
    if reader.fieldnames != list(FIELDS):
        raise ValueError("Training weather CSV schema mismatch")
    csv_rows = list(reader)
    if len(csv_rows) != len(verified_rows) or len(csv_rows) != manifest.get("row_count"):
        raise ValueError("Training weather CSV row count mismatch")
    for actual, expected in zip(csv_rows, verified_rows):
        if (set(actual) != set(FIELDS) or actual["turbine_id"] != expected["turbine_id"]
                or actual["timestamp"] != expected["timestamp"]):
            raise ValueError("Training weather CSV site or timestamp mismatch")
        for feature in ("wind_speed_ms", "temperature_c"):
            try:
                value = float(actual[feature])
            except (TypeError, ValueError) as exc:
                raise ValueError("Invalid training weather CSV feature") from exc
            if not math.isfinite(value) or value != expected[feature]:
                raise ValueError("Training weather CSV differs from raw provider response")
    frame = pd.DataFrame(verified_rows, columns=FIELDS)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    return frame, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--output-dir", type=Path, default=artifact_dir() / "training_weather")
    parser.add_argument("--cache-only", action="store_true", help="Fail if any request is absent from cache")
    args = parser.parse_args()
    result = fetch_training_weather(args.start_date, args.end_date, args.output_dir,
                                    cache_only=args.cache_only)
    print(f"{result['row_count']} rows; sha256={result['csv_sha256']}; {args.output_dir}")


if __name__ == "__main__":
    main()
