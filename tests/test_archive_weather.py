"""Offline Single Runs archive checks; evidence is synthetic and NOT real historical proof."""
import hashlib
import json

import httpx
import pytest

import agent
import weather
from contracts import FIRST_ORIGIN, ForecastError, expected_hours


def _payload(origin=FIRST_ORIGIN):
    from datetime import timedelta
    from contracts import iso, utc_time
    stamps = [iso(utc_time(origin) + timedelta(hours=i)).removesuffix("Z") for i in range(72)]
    return {"timezone": "GMT", "latitude": 43.620384, "longitude": 78.47891,
            "utc_offset_seconds": 0,
            "hourly_units": {"time": "iso8601", "wind_speed_10m": "m/s", "temperature_2m": "°C"},
            "hourly": {"time": stamps, "wind_speed_10m": [6.0] * len(stamps),
                       "temperature_2m": [-4.0] * len(stamps)}}


def _bytes(data):
    return json.dumps(data, separators=(",", ":"), allow_nan=True).encode()


@pytest.fixture
def setup_archive(tmp_path, monkeypatch):
    path = tmp_path / "trusted.json"
    monkeypatch.setenv("OPEN_METEO_ARCHIVE_MANIFEST", str(path))
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path / "artifacts"))
    data = _payload()
    site = weather.load_sites("archive")[0]
    record = {"turbine_id": "T1", "origin": FIRST_ORIGIN,
              "latitude": site["latitude"], "longitude": site["longitude"],
              "model": "ecmwf_ifs", "run": "2026-01-31T12:00",
              "initialized_at": "2026-01-31T12:00:00Z", "available_at": "2026-01-31T17:00:00Z",
              "attestation": "reviewed_as_issued", "availability_basis": "external_capture_log",
              "evidence_ref": "operator/capture-001", "forecast_sha256": ""}
    calls = []

    baseline = _payload()

    def save():
        # Evidence digest is the original full 72-hour forecast, NOT mutated responses.
        baseline_rows = {stamp + "Z": {"valid_at": stamp + "Z", "wind_speed_ms": 6.0,
                                      "temperature_c": -4.0} for stamp in baseline["hourly"]["time"]}
        expected_site = next(s for s in weather.load_sites("archive") if s["turbine_id"] == record["turbine_id"])
        record["forecast_sha256"] = weather._forecast_digest(expected_site, record,
                                      baseline["latitude"], baseline["longitude"], baseline_rows)
        path.write_text(json.dumps({"version": 1, "runs": [record]}))

    def get(url, *, params, timeout, follow_redirects):
        calls.append((url, params, timeout, follow_redirects))
        return httpx.Response(200, content=_bytes(data))

    save()
    monkeypatch.setattr(weather.httpx, "get", get)
    return site, data, record, calls, save


@pytest.mark.parametrize("turbine", ["T1", "T2"])
@pytest.mark.parametrize("horizon", [24, 48])
def test_archive_coverage(turbine, horizon, setup_archive):
    site, data, record, calls, save = setup_archive
    site = next(s for s in weather.load_sites("archive") if s["turbine_id"] == turbine)
    record.update(turbine_id=turbine, latitude=site["latitude"], longitude=site["longitude"])
    save()
    result = weather.fetch_weather(site, FIRST_ORIGIN, horizon, "archive")
    assert [row["valid_at"] for row in result["rows"]] == expected_hours(FIRST_ORIGIN, horizon)
    assert result["manifest"]["raw_sha256"] == hashlib.sha256(_bytes(data)).hexdigest()
    assert result["manifest"]["forecast_sha256"] == record["forecast_sha256"]
    assert result["manifest"]["wind_height_status"] == "proxy_not_hub_height"
    assert result["manifest"]["grid_latitude"] == 43.620384
    assert calls[0][1]["run"] == record["run"] and calls[0][1]["models"] == "ecmwf_ifs"
    assert "start_date" not in calls[0][1]


@pytest.mark.parametrize("change", ["missing", "duplicate", "units", "offset", "timezone", "negative", "null", "bool", "string", "nonfinite", "length", "timestamp"])
def test_bad_responses_fail_without_padding(change, setup_archive):
    site, data, record, calls, save = setup_archive
    hourly = data["hourly"]
    if change == "missing":
        for field in hourly:
            hourly[field].pop(1)
    elif change == "duplicate":
        hourly["time"][1] = hourly["time"][0]
    elif change == "units":
        data["hourly_units"]["wind_speed_10m"] = "km/h"
    elif change == "offset":
        data["utc_offset_seconds"] = 21600
    elif change == "timezone":
        data["timezone"] = "Asia/Almaty"
    elif change in ("negative", "null", "bool", "string", "nonfinite"):
        hourly["wind_speed_10m"][1] = {"negative": -1, "null": None, "bool": True,
                                         "string": "6", "nonfinite": 1e999}[change]
        if change == "nonfinite":
            hourly["wind_speed_10m"][1] = float("inf")
            # Nonstandard JSON Infinity is rejected before canonical comparison.
    elif change == "length":
        hourly["wind_speed_10m"].pop()
    else:
        hourly["time"][1] += "+06:00"
    save()
    with pytest.raises(ForecastError) as exc:
        weather.fetch_weather(site, FIRST_ORIGIN, 24, "archive")
    assert exc.value.code == "DATA_INVALID"


@pytest.mark.parametrize("field,value", [
    ("available_at", "2026-01-31T19:00:00Z"), ("attestation", "retrospective"),
    ("model", "other"), ("latitude", 0), ("availability_basis", "initialization_plus_delay"),
    ("forecast_sha256", "fake"), ("evidence_ref", "https://example.org/?key=secret"),
    ("run", "2026-02-01T12:00"), ("initialized_at", "2026-01-31T12:01:00Z")])
def test_evidence_rejected_before_network(field, value, setup_archive):
    site, data, record, calls, save = setup_archive
    record[field] = value
    save() if field != "forecast_sha256" else None
    if field == "forecast_sha256":
        import os
        from pathlib import Path
        Path(os.environ["OPEN_METEO_ARCHIVE_MANIFEST"]).write_text(json.dumps({"version": 1, "runs": [record]}))
    with pytest.raises(ForecastError) as exc:
        weather.fetch_weather(site, FIRST_ORIGIN, 24, "archive")
    assert exc.value.code == "WEATHER_UNAVAILABLE" and not calls


@pytest.mark.parametrize("version", [True, 1.0, "1"])
def test_manifest_version_must_be_integer_one(version, setup_archive, monkeypatch):
    site, data, record, calls, save = setup_archive
    from pathlib import Path
    import os
    Path(os.environ["OPEN_METEO_ARCHIVE_MANIFEST"]).write_text(json.dumps({"version": version, "runs": [record]}))
    with pytest.raises(ForecastError) as exc:
        weather.fetch_weather(site, FIRST_ORIGIN, 24, "archive")
    assert exc.value.code == "WEATHER_UNAVAILABLE" and not calls


def test_canonical_digest_ignores_volatile_metadata_and_serialization(setup_archive):
    site, data, record, calls, save = setup_archive
    first = weather.fetch_weather(site, FIRST_ORIGIN, 24, "archive")
    data["generationtime_ms"] = 942.0
    data["timezone"] = "UTC"  # GMT and UTC both denote zero offset
    data["hourly"] = dict(reversed(list(data["hourly"].items())))
    second = weather.fetch_weather(site, FIRST_ORIGIN, 48, "archive")
    assert first["manifest"]["forecast_sha256"] == second["manifest"]["forecast_sha256"]
    assert first["manifest"]["raw_sha256"] != second["manifest"]["raw_sha256"]
    assert len(second["rows"]) == 48


def test_valid_changed_forecast_fails_closed(setup_archive):
    site, data, record, calls, save = setup_archive
    data["hourly"]["wind_speed_10m"][60] = 7.0  # outside 24/48 target, still part of full run
    with pytest.raises(ForecastError) as exc:
        weather.fetch_weather(site, FIRST_ORIGIN, 24, "archive")
    assert exc.value.code == "WEATHER_UNAVAILABLE"


def test_missing_run_evidence_blocks_before_network(setup_archive, monkeypatch):
    site, data, record, calls, save = setup_archive
    from pathlib import Path
    import os
    Path(os.environ["OPEN_METEO_ARCHIVE_MANIFEST"]).write_text(json.dumps({"version": 1, "runs": []}))
    with pytest.raises(ForecastError) as exc:
        weather.fetch_weather(site, FIRST_ORIGIN, 24, "archive")
    assert exc.value.code == "WEATHER_UNAVAILABLE" and not calls


def test_raw_capture_is_atomic_and_existing_mismatch_blocks(setup_archive, monkeypatch):
    site, data, record, calls, save = setup_archive
    from contracts import artifact_dir
    result = weather.fetch_weather(site, FIRST_ORIGIN, 24, "archive")
    target = artifact_dir() / "weather_raw" / f"{result['manifest']['raw_sha256']}.json"
    assert target.read_bytes() == _bytes(data)
    assert not list(target.parent.glob(".weather-*.tmp"))
    target.write_bytes(b"interrupted or poisoned prior capture")
    with pytest.raises(ForecastError) as exc:
        weather.fetch_weather(site, FIRST_ORIGIN, 24, "archive")
    assert exc.value.code == "WEATHER_UNAVAILABLE"
    assert target.read_bytes() == b"interrupted or poisoned prior capture"


def test_raw_capture_failed_atomic_replace_cleans_temp(setup_archive, monkeypatch):
    site, data, record, calls, save = setup_archive
    from contracts import artifact_dir
    def fail_replace(*args):
        raise OSError("internal-path-secret")
    monkeypatch.setattr(weather.os, "replace", fail_replace)
    with pytest.raises(ForecastError) as exc:
        weather.fetch_weather(site, FIRST_ORIGIN, 24, "archive")
    assert exc.value.code == "WEATHER_UNAVAILABLE"
    assert "internal-path-secret" not in str(exc.value)
    assert not list((artifact_dir() / "weather_raw").glob("*.json"))
    assert not list((artifact_dir() / "weather_raw").glob(".weather-*.tmp"))


def test_no_manifest_or_fixture_site_never_calls_network(setup_archive, monkeypatch):
    site, data, record, calls, save = setup_archive
    monkeypatch.delenv("OPEN_METEO_ARCHIVE_MANIFEST")
    with pytest.raises(ForecastError, match="Архив недоступен"):
        weather.fetch_weather(site, FIRST_ORIGIN, 24, "archive")
    with pytest.raises(ForecastError) as exc:
        weather.fetch_weather({"turbine_id": "T1", "latitude": 0}, FIRST_ORIGIN, 24, "archive")
    assert exc.value.code == "INVALID_INPUT" and not calls


@pytest.mark.parametrize("failure", ["timeout", "limit", "http", "json", "digest"])
def test_provider_failures_sanitized(failure, setup_archive, monkeypatch):
    site, data, record, calls, save = setup_archive
    secret = "test-api-secret"
    def get(*args, **kwargs):
        if failure == "timeout":
            raise httpx.ReadTimeout(secret)
        if failure == "limit":
            return httpx.Response(429, content=secret)
        if failure == "http":
            return httpx.Response(500, content=secret)
        if failure == "json":
            raw = b"{invalid"
        else:
            raw = b"different"
        return httpx.Response(200, content=raw)
    monkeypatch.setattr(weather.httpx, "get", get)
    with pytest.raises(ForecastError) as exc:
        weather.fetch_weather(site, FIRST_ORIGIN, 24, "archive")
    assert exc.value.code == ("DATA_INVALID" if failure in ("json", "digest") else "WEATHER_UNAVAILABLE")
    assert secret not in str(exc.value)


def test_agent_real_csv_and_fitted_model(setup_archive, monkeypatch):
    site, data, record, calls, save = setup_archive
    agent._CACHE.clear()
    request = {"turbine_id": "T1", "origin": FIRST_ORIGIN, "horizon_hours": 24, "mode": "archive"}
    from model import load_model
    with monkeypatch.context() as model_environment:
        model_environment.delenv("ARTIFACT_DIR", raising=False)
        fitted = load_model("T1")
    result = agent.run_forecast(request, model_loader=lambda turbine: fitted)
    assert result["status"] == "ok", result
    assert result["model_input"]["row_count"] == 24
    from model_input import read_model_input
    from contracts import artifact_dir
    rows = read_model_input(artifact_dir() / "model_inputs" / result["model_input"]["filename"],
                            turbine_id="T1", origin=FIRST_ORIGIN, horizon_hours=24,
                            expected_sha256=result["model_input"]["sha256"])
    assert len(rows) == 24 and len(result["hours"]) == 24
    assert any(step["step"] == "predict_power" and step["status"] == "ok" for step in result["trace"])
    assert result["weather_provenance"]["wind_height_m"] == 10
    agent._CACHE.clear()
