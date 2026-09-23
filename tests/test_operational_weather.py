"""Deterministic contract checks; mocked receipts do not attest real publication."""
import hashlib
import json
import math
from datetime import datetime, timezone

import httpx
import pytest

from backend.adapters import operational_weather as weather
from backend.core.contracts import ForecastError, fingerprint
from backend.services.february import origin_for_date

ORIGIN = "2026-01-31T18:00:00Z"


@pytest.mark.parametrize("day,expected", [
    ("2026-02-01", ORIGIN),
    ("2026-02-28", "2026-02-27T18:00:00Z"),
])
def test_february_day_maps_to_previous_evening(day, expected):
    assert origin_for_date(day) == expected


@pytest.mark.parametrize("value", ["2026-01-31", "2026-03-01", "2026-02-29", "20260201", "bad", None])
def test_february_rejects_outside_or_noncanonical_dates(value):
    with pytest.raises(ForecastError):
        origin_for_date(value)


def test_future_object_cannot_attest_historical_availability():
    response = httpx.Response(200, headers={"Last-Modified": "Sat, 31 Jan 2026 18:00:01 GMT"})
    with pytest.raises(ForecastError):
        weather._last_modified(response, datetime(2026, 1, 31, 18, tzinfo=timezone.utc))


@pytest.mark.parametrize("horizon,mode", [(25, "archive"), (True, "archive"), (24, "live"), (48, "fixture")])
def test_operational_rejects_wrong_mode_or_horizon(horizon, mode):
    with pytest.raises(ForecastError):
        weather.fetch_operational_weather(weather.SITES[0], ORIGIN, horizon, mode)


@pytest.mark.parametrize("horizon", [24, 48])
def test_hourly_input_interpolates_vectors_before_speed_and_converts_kelvin(monkeypatch, horizon):
    nodes = {}
    for step in weather.STEPS:
        # Opposite winds at 18h and 21h: interpolated speed is 1, not 3 m/s.
        values = {"2t": 273.15 + step - 18, "10u": 3 if step == 18 else -3,
                  "10v": 0, "grid_latitude": 43.75, "grid_longitude": 78.5}
        nodes[str(step)] = {site["turbine_id"]: values.copy() for site in weather.SITES}
    receipt = {"nodes": nodes, "objects": {"mock": {"last_modified": "2026-01-31T08:00:00Z"}},
               "receipt_sha256": "a" * 64}
    monkeypatch.setattr(weather, "_load_receipt", lambda *args, **kwargs: receipt)
    result = weather.fetch_operational_weather(weather.SITES[0], ORIGIN, horizon)
    rows = result["rows"]
    assert len(rows) == horizon
    assert rows[0]["valid_at"] == "2026-01-31T19:00:00Z"
    assert rows[0]["temperature_c"] == pytest.approx(1)
    assert rows[0]["wind_speed_ms"] == pytest.approx(1)
    assert rows[2]["wind_speed_ms"] == pytest.approx(3)
    assert rows[-1]["valid_at"] == ("2026-02-01T18:00:00Z" if horizon == 24 else "2026-02-02T18:00:00Z")
    assert all(math.isfinite(row["wind_speed_ms"]) for row in rows)


def _mock_receipt(tmp_path, monkeypatch):
    """One mocked decoded GRIB node; exercise real raw/index/hash binding."""
    monkeypatch.setattr(weather, "STEPS", (18,))
    monkeypatch.setattr(weather, "_point", lambda raw, param, step, site, init: (43.75, 78.5, 270 if param == "2t" else 2))
    records = [{"param": param, "levtype": "sfc", "step": "18", "type": "fc",
                "stream": "oper", "time": "0000", "date": "20260131", "_offset": offset,
                "_length": 1} for offset, param in enumerate(weather.PARAMS)]
    raw_index = b"\n".join(json.dumps(row).encode() for row in records)
    stem = weather.BASE + "/20260131/00z/ifs/0p25/oper/20260131000000-18h-oper-fc"
    objects = {}
    for suffix, raw in [("index", raw_index), ("2t", b"t"), ("10u", b"u"), ("10v", b"v")]:
        (tmp_path / f"18-{suffix}.bin").write_bytes(raw)
        objects[f"18-{suffix}"] = {"url": stem + (".index" if suffix == "index" else ".grib2"),
                                    "sha256": hashlib.sha256(raw).hexdigest(),
                                    "last_modified": "2026-01-31T08:00:00Z"}
        if suffix != "index":
            objects[f"18-{suffix}"].update(offset=weather.PARAMS.index(suffix), length=1)
    values = {"2t": 270, "10u": 2, "10v": 2, "grid_latitude": 43.75, "grid_longitude": 78.5}
    data = {"version": 1, "origin": ORIGIN, "run_id": "2026-01-31T00:00:00Z",
            "objects": objects, "nodes": {"18": {site["turbine_id"]: values.copy() for site in weather.SITES}}}
    return data


def _write_receipt(path, data):
    data.pop("receipt_sha256", None)
    data["receipt_sha256"] = fingerprint(data)[7:]
    (path / "receipt.json").write_text(json.dumps(data))


def test_receipt_rejects_changed_values_even_with_recomputed_checksum(tmp_path, monkeypatch):
    data = _mock_receipt(tmp_path, monkeypatch)
    _write_receipt(tmp_path, data)
    weather._load_receipt(tmp_path, ORIGIN, horizon_hours=24)
    data["nodes"]["18"]["T1"]["10u"] = 999
    _write_receipt(tmp_path, data)
    with pytest.raises(ForecastError):
        weather._load_receipt(tmp_path, ORIGIN, horizon_hours=24)


def test_receipt_rejects_future_object_even_with_recomputed_checksum(tmp_path, monkeypatch):
    data = _mock_receipt(tmp_path, monkeypatch)
    data["objects"]["18-10u"]["last_modified"] = "2026-01-31T19:00:00Z"
    _write_receipt(tmp_path, data)
    with pytest.raises(ForecastError):
        weather._load_receipt(tmp_path, ORIGIN, horizon_hours=24)
