"""Forecast boundary checks using a small deterministic stand-in estimator."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

import agent
from contracts import FIRST_ORIGIN
from weather import fetch_weather


def request(site="T1", origin=FIRST_ORIGIN, horizon=24, mode="fixture"):
    return {"turbine_id": site, "origin": origin, "horizon_hours": horizon, "mode": mode}


def model_loader(site):
    return SimpleNamespace(metadata={"turbine_id": site, "model_id": "sha256:fake-" + site,
        "train_origin": FIRST_ORIGIN, "train_last_interval_start": "2026-01-31T16:00:00Z",
        "baseline_norm": 0.25})


@pytest.fixture
def predictions(monkeypatch):
    calls = []
    def predict(model, path, **kwargs):
        from model_input import read_model_input
        rows = read_model_input(path, **kwargs)
        calls.append(len(rows))
        return [-0.2, 1.2] + [0.5] * (len(rows) - 2)
    monkeypatch.setattr(agent, "predict_power_csv", predict)
    agent._CACHE.clear()
    yield calls
    agent._CACHE.clear()


def test_all_demo_paths_and_cache(predictions):
    for site in ("T1", "T2"):
        for origin in (FIRST_ORIGIN, "2026-02-01T18:00:00Z"):
            for horizon in (24, 48):
                first = agent.run_forecast(request(site, origin, horizon), model_loader=model_loader)
                again = agent.run_forecast(request(site, origin, horizon), model_loader=model_loader)
                assert first["status"] == "ok" and len(first["hours"]) == horizon
                assert first["hours"][0]["power_norm"] == 0
                assert first["hours"][1]["power_norm"] == 1
                assert first["analysis"]["clipped_count"] == 2
                assert first["cache_hit"] is False and again["cache_hit"] is True
                assert first["fingerprint"] == again["fingerprint"]
    assert predictions == [24, 48] * 4


@pytest.mark.parametrize("damage", ["missing", "duplicate", "nonfinite", "future", "initialization", "wrong_site"])
def test_invalid_weather_rejected_before_cache(predictions, damage):
    assert agent.run_forecast(request(), model_loader=model_loader)["status"] == "ok"
    def bad_weather(site, origin, horizon, mode):
        bundle = deepcopy(fetch_weather(site, origin, horizon, mode))
        if damage == "missing":
            bundle["rows"].pop()
        elif damage == "duplicate":
            bundle["rows"][1] = bundle["rows"][0]
        elif damage == "nonfinite":
            bundle["rows"][0]["wind_speed_ms"] = float("nan")
        elif damage == "future":
            bundle["manifest"]["available_at"] = "2026-02-02T00:00:00Z"
        elif damage == "initialization":
            bundle["manifest"]["initialized_at"] = "2026-01-31T16:00:00Z"
        else:
            bundle["manifest"]["turbine_id"] = "T2"
        return bundle
    result = agent.run_forecast(request(), weather_tool=bad_weather, model_loader=model_loader)
    assert result["status"] == "error"
    assert result["code"] == ("WEATHER_UNAVAILABLE" if damage == "future" else "DATA_INVALID")
    assert len(predictions) == 1


def test_changed_weather_same_run_invalidates_cache(predictions):
    first = agent.run_forecast(request(), model_loader=model_loader)
    def revised(site, origin, horizon, mode):
        bundle = deepcopy(fetch_weather(site, origin, horizon, mode))
        bundle["rows"][0]["wind_speed_ms"] += 0.1
        bundle["manifest"]["raw_sha256"] = "revised-weather-content"
        return bundle
    revised_result = agent.run_forecast(request(), weather_tool=revised, model_loader=model_loader)
    assert revised_result["status"] == "ok"
    assert revised_result["cache_hit"] is False
    assert revised_result["fingerprint"] != first["fingerprint"]
    assert predictions == [24, 24]


def test_model_cutoff_and_archive(predictions):
    def future_model(site):
        fitted = model_loader(site)
        fitted.metadata["train_origin"] = "2026-02-01T00:00:00Z"
        return fitted
    assert agent.run_forecast(request(), model_loader=future_model)["code"] == "MODEL_UNAVAILABLE"
    assert agent.run_forecast(request(origin="2026-02-01T18:00:00Z"), model_loader=future_model)["code"] == "MODEL_UNAVAILABLE"
    archive = agent.run_forecast(request(mode="archive"), model_loader=model_loader)
    assert archive["code"] == "WEATHER_UNAVAILABLE"
    assert predictions == []


def test_explanation_context_uses_model_metadata_without_training_files(predictions):
    def documented_model(site):
        fitted = model_loader(site)
        fitted.metadata.update(training_rows=321, training_source="supplied turbine measurements",
                               feature_names=["wind_speed_ms", "temperature_c"],
                               feature_units={"wind_speed_ms": "m/s", "temperature_c": "°C"},
                               source_csv="/private/training.csv", secret="not for explanations")
        return fitted
    result = agent.run_forecast(request(), model_loader=documented_model)
    context = result["model_context"]
    assert context["training_rows"] == 321
    assert context["feature_names"] == ["wind_speed_ms", "temperature_c"]
    assert context["train_origin"] == FIRST_ORIGIN
    assert "source_csv" not in context and "secret" not in context
    assert any("не доказывает" in limitation for limitation in context["limitations"])
