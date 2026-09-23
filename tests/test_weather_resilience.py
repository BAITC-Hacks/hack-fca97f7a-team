"""Live HTTP reuse preserves provenance and never relaxes hourly coverage."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from backend.services import agent
from backend.adapters import weather
from backend.core.contracts import FIRST_ORIGIN, ForecastError, expected_hours, iso


@pytest.fixture
def live_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    origin = iso(datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0))
    payload = {"latitude": 43.62, "longitude": 78.48, "timezone": "GMT", "utc_offset_seconds": 0,
               "hourly_units": {"time": "iso8601", "wind_speed_10m": "m/s", "temperature_2m": "°C"},
               "hourly": {"time": [stamp[:-1] for stamp in expected_hours(origin, 48)],
                          "wind_speed_10m": [6.0] * 48, "temperature_2m": [12.0] * 48}}
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, content=json.dumps(payload).encode())

    monkeypatch.setattr(weather.httpx, "get", get)
    return origin, payload, calls


@pytest.fixture
def fitted_model(monkeypatch):
    metadata = {"turbine_id": "T1", "model_id": "test-provider-model",
                "profile": "open_meteo_ecmwf_ifs_10m", "train_origin": FIRST_ORIGIN,
                "train_last_interval_start": "2026-01-31T17:00:00Z",
                "weather_context": {"model": "ecmwf_ifs", "wind_height_m": 10,
                                    "temperature_height_m": 2,
                                    "training_weather_kind": "retrospective_stitched_forecast"}}
    monkeypatch.setattr(agent, "predict_power_csv", lambda *args, **kwargs: [0.5] * kwargs["horizon_hours"])
    return SimpleNamespace(metadata=metadata)


def test_cache_reuses_valid_payload_and_preserves_retrieval(live_payload):
    origin, _, calls = live_payload
    first = weather.fetch_weather(weather.SITES[0], origin, 24, "live")
    second = weather.fetch_weather(weather.SITES[0], origin, 48, "live")
    assert len(calls) == 1
    assert first["manifest"]["weather_cache_hit"] is False
    assert second["manifest"]["weather_cache_hit"] is True
    assert second["manifest"]["retrieved_at"] == first["manifest"]["retrieved_at"]
    assert second["manifest"]["raw_sha256"] == first["manifest"]["raw_sha256"]
    assert len(second["rows"]) == 48


def test_cache_expires_and_can_be_cleared_per_turbine(live_payload, monkeypatch):
    origin, _, calls = live_payload
    weather.fetch_weather(weather.SITES[0], origin, 24, "live")
    weather.fetch_weather(weather.SITES[1], origin, 24, "live")
    weather.clear_live_weather_cache("T1")
    assert weather.fetch_weather(weather.SITES[1], origin, 24, "live")["manifest"]["weather_cache_hit"]
    assert not weather.fetch_weather(weather.SITES[0], origin, 24, "live")["manifest"]["weather_cache_hit"]
    assert len(calls) == 3
    clock = weather.time.monotonic
    monkeypatch.setattr(weather.time, "monotonic", lambda: clock() + weather._LIVE_CACHE_TTL_SECONDS + 1)
    assert not weather.fetch_weather(weather.SITES[0], origin, 24, "live")["manifest"]["weather_cache_hit"]
    assert len(calls) == 4


def test_cache_refetches_when_larger_window_is_not_covered(live_payload):
    origin, payload, calls = live_payload
    for values in payload["hourly"].values():
        del values[24:]
    weather.fetch_weather(weather.SITES[0], origin, 24, "live")
    with pytest.raises(ForecastError) as exc:
        weather.fetch_weather(weather.SITES[0], origin, 48, "live")
    assert exc.value.code == "DATA_INVALID"
    assert len(calls) == 2


def test_failure_is_not_cached(live_payload, monkeypatch):
    origin, _, _ = live_payload
    calls = []

    def get(*args, **kwargs):
        calls.append(1)
        return httpx.Response(429)

    monkeypatch.setattr(weather.httpx, "get", get)
    for _ in range(2):
        with pytest.raises(ForecastError) as exc:
            weather.fetch_weather(weather.SITES[0], origin, 24, "live")
        assert exc.value.code == "WEATHER_UNAVAILABLE"
    assert len(calls) == 2


def test_http_crossing_utc_hour_is_not_cached(live_payload, monkeypatch):
    origin, _, calls = live_payload
    first_now = datetime.now(timezone.utc)
    class CrossingClock:
        calls = 0

        @classmethod
        def now(cls, tz):
            cls.calls += 1
            return first_now if cls.calls == 1 else first_now + timedelta(hours=1)

    monkeypatch.setattr(weather, "datetime", CrossingClock)
    with pytest.raises(ForecastError) as exc:
        weather.fetch_weather(weather.SITES[0], origin, 24, "live")
    assert exc.value.code == "LIVE_ORIGIN_CHANGED"
    assert len(calls) == 1
    assert not weather._LIVE_CACHE


def test_agent_exposes_weather_cache_hit_and_reuses_prediction(live_payload, fitted_model):
    origin, _, calls = live_payload
    request = {"turbine_id": "T1", "origin": origin, "horizon_hours": 24, "mode": "live"}
    agent._CACHE.clear()
    first = agent.run_forecast(request, model_loader=lambda _: fitted_model)
    second = agent.run_forecast(request, model_loader=lambda _: fitted_model)
    assert first["status"] == second["status"] == "ok"
    assert not first["weather_provenance"]["weather_cache_hit"]
    assert second["weather_provenance"]["weather_cache_hit"]
    assert second["weather_provenance"]["retrieved_at"] == first["weather_provenance"]["retrieved_at"]
    assert second["cache_hit"] and first["fingerprint"] == second["fingerprint"]
    assert len(calls) == 1


def test_agent_retries_origin_change_once(live_payload, fitted_model):
    origin, _, _ = live_payload
    site = weather.SITES[0]
    calls = []

    def fetch(site_arg, origin_arg, horizon, mode):
        calls.append(origin_arg)
        if len(calls) == 1:
            raise ForecastError("LIVE_ORIGIN_CHANGED", "Новый час UTC.")
        return weather.fetch_weather(site_arg, origin_arg, horizon, mode)

    result = agent.run_forecast({"turbine_id": site["turbine_id"], "origin": origin,
                                 "horizon_hours": 24, "mode": "live"},
                                weather_tool=fetch, model_loader=lambda _: fitted_model)
    assert result["status"] == "ok"
    assert len(calls) == 2
    assert [step["status"] for step in result["trace"] if step["step"] == "fetch_weather"] == ["retry", "ok"]

    def always_changed(*args):
        calls.append(1)
        raise ForecastError("LIVE_ORIGIN_CHANGED", "Новый час UTC.")

    failure = agent.run_forecast({"turbine_id": site["turbine_id"], "origin": origin,
                                  "horizon_hours": 24, "mode": "live"}, weather_tool=always_changed)
    assert failure["status"] == "error" and failure["code"] == "WEATHER_UNAVAILABLE"
    assert len(calls) == 4
