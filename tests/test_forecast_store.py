from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend import api
from backend.adapters import forecast_store
ID = "a" * 64


def _result() -> dict:
    origin = datetime(2026, 1, 31, 18, tzinfo=timezone.utc)
    return {
        "status": "ok", "fingerprint": f"sha256:{ID}", "turbine_id": "T1",
        "origin": "2026-01-31T18:00:00Z", "horizon_hours": 24,
        "mode": "fixture", "run_id": "test-run", "model_id": "test-model",
        "timezone": "Asia/Almaty", "train_last_interval_start": "2026-01-31T17:00:00Z",
        "weather_provenance": {"provenance_status": "synthetic_fixture"},
        "model_input": {"schema_version": "weather-features-v1", "sha256": "b" * 64,
                        "filename": "b" * 64 + ".csv", "row_count": 24,
                        "columns": ["turbine_id", "valid_at", "wind_speed_ms", "temperature_c"]},
        "analysis": {"peak_power_norm": 0.5, "peak_at": "2026-01-31T19:00:00Z",
                     "min_power_norm": 0.5, "min_at": "2026-01-31T19:00:00Z",
                     "clipped_count": 0, "warnings": []},
        "trace": [],
        "hours": [{"valid_at": (origin + timedelta(hours=i + 1)).isoformat(timespec="seconds").replace("+00:00", "Z"),
                   "lead_hour": i + 1,
                   "wind_speed_ms": 5.0, "temperature_c": 0.0,
                   "power_norm": 0.5, "baseline_norm": 0.25} for i in range(24)],
    }


def test_atomic_store_survives_memory_eviction_and_strips_legacy_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(forecast_store, "artifact_dir", lambda: tmp_path)
    monkeypatch.setattr(api, "run_forecast", lambda body: _result())
    client = TestClient(api.app)
    created = client.post("/api/forecasts", json={
        "turbine_id": "T1", "origin": "2026-01-31T18:00:00Z",
        "horizon_hours": 24, "mode": "fixture",
    })
    assert created.status_code == 200, created.text
    assert all("baseline_norm" not in hour for hour in created.json()["hours"])
    path = tmp_path / "forecasts" / f"{ID}.json"
    assert path.is_file()
    assert not list(path.parent.glob("*.tmp"))

    # Simulate a legacy stored forecast and a process restart.
    legacy = json.loads(path.read_text(encoding="utf-8"))
    for hour in legacy["result"]["hours"]:
        hour["baseline_norm"] = 0.25
    legacy["result"]["analysis"]["warnings"].append("Старая базовая линия")
    legacy["sha256"] = forecast_store._digest(legacy["result"])
    path.write_text(json.dumps(legacy), encoding="utf-8")
    with api._FORECASTS_LOCK:
        api._FORECASTS.clear()
    seen = []
    monkeypatch.setattr(api, "summarize_forecast", lambda result, backend: seen.append(result) or {
        "text": "Тест", "backend": "template", "forecast_fingerprint": result["fingerprint"], "warning": None,
    })
    response = client.post(f"/api/forecasts/{ID}/explanation", json={"backend": "template"})
    assert response.status_code == 200
    assert all("baseline_norm" not in hour for hour in seen[0]["hours"])
    assert seen[0]["analysis"]["warnings"] == []
    download = client.get(f"/api/forecasts/{ID}/download")
    assert download.status_code == 200
    assert "baseline_norm" not in download.text


def test_store_rejects_invalid_and_expired_files(tmp_path, monkeypatch):
    monkeypatch.setattr(forecast_store, "artifact_dir", lambda: tmp_path)
    result = _result()
    assert forecast_store.load("../" + ID) is None
    try:
        forecast_store.save(ID, {**result, "fingerprint": "sha256:" + "b" * 64})
    except ValueError:
        pass
    else:
        raise AssertionError("mismatched forecast identity was accepted")
    forecast_store.save(ID, result)
    path = tmp_path / "forecasts" / f"{ID}.json"
    modified = json.loads(path.read_text(encoding="utf-8"))
    modified["result"]["hours"][0]["power_norm"] = 0.75
    path.write_text(json.dumps(modified), encoding="utf-8")
    assert forecast_store.load(ID) is None
    modified["result"]["unchecked_extra"] = float("nan")
    path.write_text(json.dumps(modified), encoding="utf-8")
    assert forecast_store.load(ID) is None
    path.write_text("{broken", encoding="utf-8")
    assert forecast_store.load(ID) is None
    forecast_store.save(ID, result)
    old = time.time() - forecast_store.MAX_AGE_SECONDS - 1
    os.utime(path, (old, old))
    assert forecast_store.load(ID) is None


def test_store_retention_keeps_newest_256(tmp_path, monkeypatch):
    monkeypatch.setattr(forecast_store, "artifact_dir", lambda: tmp_path)
    directory = tmp_path / "forecasts"
    directory.mkdir()
    for index in range(forecast_store.MAX_FILES):
        path = directory / f"{index:064x}.json"
        path.write_text("{}", encoding="utf-8")
        os.utime(path, (1000 + index, time.time() - 100 + index / 1000))
    forecast_store.save(ID, _result())
    assert len(list(directory.glob("*.json"))) == forecast_store.MAX_FILES
    assert (directory / f"{ID}.json").is_file()


def test_weather_refresh_calls_clear_for_selected_turbine(monkeypatch):
    seen = []
    monkeypatch.setattr(api, "clear_live_weather_cache", seen.append)
    client = TestClient(api.app)
    response = client.post("/api/weather/refresh", json={"turbine_id": "T2"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert seen == ["T2"]
    invalid = client.post("/api/weather/refresh", json={"turbine_id": "T3"})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "INVALID_INPUT"
