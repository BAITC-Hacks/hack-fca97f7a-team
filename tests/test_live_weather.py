"""Offline coverage of current Open-Meteo retrieval and the real CSV/model seam."""
import hashlib
import json
import shutil
from pathlib import Path
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

import agent
import api
import contracts
import weather
from contracts import expected_hours, next_live_origin

NOW = datetime(2026, 9, 23, 10, 34, 56, tzinfo=timezone.utc)
ORIGIN = "2026-09-23T11:00:00Z"


def payload(origin=ORIGIN):
    start = datetime.fromisoformat(origin.replace("Z", "+00:00"))
    times = [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(73)]
    return {"latitude": 43.62, "longitude": 78.48, "utc_offset_seconds": 0,
            "timezone": "GMT", "hourly_units": {"time": "iso8601", "wind_speed_10m": "m/s",
            "temperature_2m": "°C"}, "hourly": {"time": times, "wind_speed_10m": [5.0] * 73,
            "temperature_2m": [10.0] * 73}}


@pytest.fixture
def mocked(monkeypatch, tmp_path, provider_model_factory):
    monkeypatch.setattr(contracts, "utc_now", lambda: NOW)
    monkeypatch.setattr(weather, "utc_now", lambda: NOW)
    shutil.copytree(Path(__file__).resolve().parents[1] / "artifacts" / "models", tmp_path / "models")
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    models = {}
    def load(turbine, *, profile):
        assert profile == "open_meteo_ecmwf_ifs_10m"
        if turbine not in models:
            models[turbine] = provider_model_factory(turbine)
        return models[turbine]
    monkeypatch.setattr(agent, "load_model", load)
    calls = []

    def get(url, *, params, timeout, follow_redirects):
        calls.append((url, params, timeout, follow_redirects))
        return httpx.Response(200, content=json.dumps(payload()).encode())

    monkeypatch.setattr(weather.httpx, "get", get)
    agent._CACHE.clear()
    yield calls, tmp_path
    agent._CACHE.clear()


def test_live_sites_and_full_csv_inference(mocked):
    calls, directory = mocked
    client = TestClient(api.app)
    sites = client.get("/api/sites?mode=live").json()["sites"]
    assert sites == weather.load_sites("archive")
    for site in sites:
        for horizon in (24, 48):
            response = client.post("/api/forecasts", json={"turbine_id": site["turbine_id"],
                                   "horizon_hours": horizon, "mode": "live"})
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["origin"] == ORIGIN
            assert [hour["valid_at"] for hour in result["hours"]] == expected_hours(ORIGIN, horizon)
            provenance = result["weather_provenance"]
            assert provenance["initialized_at"] is None
            assert provenance["available_at"] == provenance["fetched_at"]
            assert provenance["retrieved_at"] == provenance["fetched_at"]
            assert provenance["provenance_status"] == "live"
            assert provenance["run_id"].startswith("live-best-match/")
            assert result["model_provenance"]["forecast_accuracy_verified"] is False
            raw = (directory / "weather_raw" / (provenance["raw_sha256"] + ".json")).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == provenance["raw_sha256"]
            download = client.get(f"/api/forecasts/{result['forecast_id']}/download?kind=model-input")
            assert download.status_code == 200
            assert len(download.text.splitlines()) == horizon + 1
    assert len(calls) == 2  # second horizon reuses each turbine's recent response
    assert all(url == weather.LIVE_URL and params["forecast_hours"] == 72 and
               params["wind_speed_unit"] == "ms" and params["models"] == "ecmwf_ifs"
               and timeout == 8 and not redirects
               for url, params, timeout, redirects in calls)


@pytest.mark.parametrize("cross_at", ["agent", "weather"])
def test_api_reissues_origin_if_boundary_crosses_before_http(mocked, monkeypatch, cross_at):
    before = datetime(2026, 9, 23, 10, 59, 59, 999999, tzinfo=timezone.utc)
    after = datetime(2026, 9, 23, 11, 0, 0, 1, tzinfo=timezone.utc)
    clock = [before]
    monkeypatch.setattr(contracts, "utc_now", lambda: clock[0])
    monkeypatch.setattr(weather, "utc_now", lambda: clock[0])
    origins = []
    original_run = api.run_forecast
    def run(request):
        origins.append(request["origin"])
        if cross_at == "agent" and len(origins) == 1:
            clock[0] = after
        return original_run(request)
    monkeypatch.setattr(api, "run_forecast", run)
    if cross_at == "weather":
        original_next = weather.next_live_origin
        def next_origin():
            clock[0] = after
            return original_next()
        monkeypatch.setattr(weather, "next_live_origin", next_origin)
    response = TestClient(api.app).post("/api/forecasts", json={
        "turbine_id": "T1", "horizon_hours": 24, "mode": "live"})
    assert response.status_code == 200, response.text
    assert origins == ["2026-09-23T11:00:00Z", "2026-09-23T12:00:00Z"]
    assert response.json()["origin"] == origins[-1]
    assert len(mocked[0]) == 1  # no network for stale origin


def test_live_rejects_client_origin_and_direct_stale_request(mocked):
    client = TestClient(api.app)
    body = {"turbine_id": "T1", "horizon_hours": 24, "mode": "live"}
    rejected = client.post("/api/forecasts", json={**body, "origin": ORIGIN})
    assert rejected.status_code == 400 and rejected.json()["code"] == "INVALID_INPUT"
    assert client.post("/api/forecasts", json={**body, "origin": None}).status_code == 400
    missing = client.post("/api/forecasts", json={**body, "mode": "fixture"})
    assert missing.status_code == 422 and missing.json()["code"] == "INVALID_INPUT"
    stale = agent.run_forecast({**body, "origin": "2026-01-31T18:00:00Z"})
    assert stale["code"] == "INVALID_INPUT"
    assert not mocked[0]


@pytest.mark.parametrize("origin", ["2026-01-31T18:00:00Z", "2026-09-23T12:00:00Z"])
def test_direct_weather_live_rejects_noncurrent_origin_before_http(mocked, origin):
    with pytest.raises(contracts.ForecastError) as error:
        weather.fetch_weather(weather.load_sites("live")[0], origin, 24, "live")
    assert error.value.code == "INVALID_INPUT"
    assert not mocked[0]


@pytest.mark.parametrize("damage", ["units", "null", "duplicate", "hole", "negative", "nan", "bool", "grid", "error"])
def test_malformed_response_never_falls_back(mocked, monkeypatch, damage):
    data = payload()
    if damage == "units": data["hourly_units"]["wind_speed_10m"] = "km/h"
    elif damage == "null": data["hourly"]["temperature_2m"][1] = None
    elif damage == "duplicate": data["hourly"]["time"][1] = data["hourly"]["time"][0]
    elif damage == "hole": data["hourly"]["time"].pop(1); data["hourly"]["wind_speed_10m"].pop(1); data["hourly"]["temperature_2m"].pop(1)
    elif damage == "negative": data["hourly"]["wind_speed_10m"][1] = -1
    elif damage == "nan": data["hourly"]["wind_speed_10m"][1] = float("nan")
    elif damage == "bool": data["hourly"]["wind_speed_10m"][1] = True
    elif damage == "grid": data["latitude"] = float("nan")
    else: data = {"error": True, "reason": "secret"}
    monkeypatch.setattr(weather.httpx, "get", lambda *a, **kw: httpx.Response(200, content=json.dumps(data).encode()))
    result = agent.run_forecast({"turbine_id": "T1", "origin": ORIGIN, "horizon_hours": 24, "mode": "live"})
    assert result["code"] == "DATA_INVALID"
    assert "secret" not in result["message"]


@pytest.mark.parametrize("error,status", [(429, 503), (500, 503), ("timeout", 503), ("json", 422)])
def test_provider_errors_are_structured(mocked, monkeypatch, error, status):
    def get(*a, **kw):
        if error == "timeout": raise httpx.ReadTimeout("private-provider-data")
        return httpx.Response(error if isinstance(error, int) else 200,
                              content=b"{invalid" if error == "json" else b"private-provider-data")
    monkeypatch.setattr(weather.httpx, "get", get)
    response = TestClient(api.app).post("/api/forecasts", json={"turbine_id": "T1", "mode": "live", "horizon_hours": 24})
    assert response.status_code == status
    assert response.json()["code"] == ("DATA_INVALID" if status == 422 else "WEATHER_UNAVAILABLE")
    assert "private-provider-data" not in response.text


def test_crossed_origin_retries_with_new_hour(mocked, monkeypatch):
    clock = [NOW]
    monkeypatch.setattr(contracts, "utc_now", lambda: clock[0])
    monkeypatch.setattr(weather, "utc_now", lambda: clock[0])
    provider = weather.httpx.get
    def get(*args, **kwargs):
        response = provider(*args, **kwargs)
        clock[0] = NOW + timedelta(minutes=27)  # first HTTP completes after 11:00
        return response
    monkeypatch.setattr(weather.httpx, "get", get)
    origins = []

    def tool(site, origin, horizon, mode):
        origins.append(origin)
        return weather.fetch_weather(site, origin, horizon, mode)

    result = agent.run_forecast({"turbine_id": "T1", "origin": ORIGIN, "horizon_hours": 24,
                                 "mode": "live"}, weather_tool=tool)
    assert result["origin"] == "2026-09-23T12:00:00Z"
    assert origins == [ORIGIN, "2026-09-23T12:00:00Z"]


def test_second_crossing_fails_without_backdating(mocked, monkeypatch):
    clock = [NOW]
    monkeypatch.setattr(contracts, "utc_now", lambda: clock[0])
    monkeypatch.setattr(weather, "utc_now", lambda: clock[0])
    provider = weather.httpx.get
    def get(*args, **kwargs):
        response = provider(*args, **kwargs)
        clock[0] = NOW + timedelta(hours=1, minutes=27) if clock[0] > NOW else NOW + timedelta(minutes=27)
        return response
    monkeypatch.setattr(weather.httpx, "get", get)
    result = agent.run_forecast({"turbine_id": "T1", "origin": ORIGIN,
                                 "horizon_hours": 24, "mode": "live"})
    assert result["status"] == "error"
    assert result["code"] == "WEATHER_UNAVAILABLE"
    assert len(mocked[0]) == 2


@pytest.mark.parametrize("missing", [False, True])
def test_live_rejects_false_or_missing_initialization(mocked, missing):
    def bad(site, origin, horizon, mode):
        bundle = weather.fetch_weather(site, origin, horizon, mode)
        if missing:
            bundle["manifest"].pop("initialized_at")
        else:
            bundle["manifest"]["initialized_at"] = ORIGIN
        return bundle
    result = agent.run_forecast({"turbine_id": "T1", "origin": ORIGIN,
                                 "horizon_hours": 24, "mode": "live"}, weather_tool=bad)
    assert result["code"] == "DATA_INVALID"


def test_corrupt_existing_raw_blocks_inference(mocked):
    raw = json.dumps(payload()).encode()
    digest = hashlib.sha256(raw).hexdigest()
    path = mocked[1] / "weather_raw" / (digest + ".json")
    path.parent.mkdir()
    path.write_bytes(b"corrupted")
    result = agent.run_forecast({"turbine_id": "T1", "origin": ORIGIN, "horizon_hours": 24, "mode": "live"})
    assert result["code"] == "WEATHER_UNAVAILABLE"
    assert path.read_bytes() == b"corrupted"
