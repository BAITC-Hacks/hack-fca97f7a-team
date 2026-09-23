import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.adapters.replay_weather import fetch_replay_weather, prepare_replay_weather
from backend.adapters.weather import SITES
from backend.core.contracts import FIRST_ORIGIN, ForecastError, expected_hours


def response_for(run: str, *, missing: bool = False):
    start = datetime.fromisoformat(run).replace(tzinfo=timezone.utc)
    hours = [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00") for i in range(168)]
    if missing:
        del hours[50]
    return json.dumps({"latitude": 43.620384, "longitude": 78.47891,
                       "utc_offset_seconds": 0, "timezone": "GMT",
                       "hourly_units": {"time": "iso8601", "wind_speed_10m": "m/s",
                                        "temperature_2m": "°C"},
                       "hourly": {"time": hours, "wind_speed_10m": [4.0] * len(hours),
                                  "temperature_2m": [0.0] * len(hours)}}).encode()


class FakeClient:
    def __init__(self, *, missing=False, statuses=None):
        self.calls = []
        self.missing = missing
        self.statuses = list(statuses or [])

    def get(self, url, *, params, timeout, follow_redirects):
        self.calls.append((url, dict(params), timeout, follow_redirects))
        status = self.statuses.pop(0) if self.statuses else 200
        return type("Response", (), {"status_code": status,
                                     "content": response_for(params["run"], missing=self.missing)})()


def test_download_reuse_and_offline_load(tmp_path, monkeypatch):
    client = FakeClient()
    first = prepare_replay_weather(tmp_path, days=1, client=client)
    assert first["status"] == "ok" and first["expected_runs"] == 2
    assert first["downloads"] == 2 and len(client.calls) == 2
    assert all(call[1]["run"] == "2026-01-30T00:00" for call in client.calls)
    assert all(call[2] == 30.0 and call[3] is False for call in client.calls)
    second = prepare_replay_weather(tmp_path, days=1, client=client, cache_only=True)
    assert second["status"] == "ok" and second["downloads"] == 0 and len(client.calls) == 2
    monkeypatch.setenv("REPLAY_WEATHER_DIR", str(tmp_path))
    bundle = fetch_replay_weather(SITES[0], FIRST_ORIGIN, 48, "archive")
    assert [row["valid_at"] for row in bundle["rows"]] == expected_hours(FIRST_ORIGIN, 48)
    assert len(fetch_replay_weather(SITES[0], FIRST_ORIGIN, 24)["rows"]) == 24
    manifest = bundle["manifest"]
    assert manifest["initialized_at"] == "2026-01-30T00:00:00Z"
    assert manifest["available_at"] is None
    assert manifest["assumed_available_by"] == "2026-01-31T00:00:00Z"
    assert manifest["availability_verified"] is False
    assert manifest["provenance_status"] == "provider_documented"
    assert len(manifest["forecast_sha256"]) == 64


def test_corrupted_cache_not_overwritten(tmp_path, monkeypatch):
    client = FakeClient()
    prepare_replay_weather(tmp_path, days=1, client=client)
    entry = next(tmp_path.glob("T1-*"))
    (entry / "raw.json").write_bytes(b"bad")
    report = prepare_replay_weather(tmp_path, days=1, client=client)
    assert report["status"] == "incomplete" and report["cached_runs"] == 1
    assert len(client.calls) == 2 and (entry / "raw.json").read_bytes() == b"bad"
    monkeypatch.setenv("REPLAY_WEATHER_DIR", str(tmp_path))
    with pytest.raises(ForecastError, match="поврежд"):
        fetch_replay_weather(SITES[0], FIRST_ORIGIN, 48)


def test_missing_hour_or_unknown_origin_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("REPLAY_WEATHER_DIR", str(tmp_path))
    report = prepare_replay_weather(tmp_path, days=1, client=FakeClient(missing=True))
    assert report["status"] == "incomplete" and report["cached_runs"] == 0
    assert not list(tmp_path.glob("T1-*"))
    with pytest.raises(ForecastError):
        fetch_replay_weather(SITES[0], "2026-03-01T18:00:00Z", 48)
    with pytest.raises(ForecastError):
        fetch_replay_weather(SITES[0], FIRST_ORIGIN, 48)


def test_retry_transient_response(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.adapters.replay_weather.time.sleep", lambda _: None)
    client = FakeClient(statuses=[429, 503, 200])
    report = prepare_replay_weather(tmp_path, days=1, client=client)
    assert report["status"] == "ok" and len(client.calls) == 4
