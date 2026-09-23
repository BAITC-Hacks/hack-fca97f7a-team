from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

import api


client = TestClient(api.app)
VALID = {
    "turbine_id": "T1",
    "origin": "2026-01-31T18:00:00Z",
    "horizon_hours": 24,
    "mode": "fixture",
}


def test_health_and_sites_do_not_expose_credentials(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-value")
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "llm_configured": True, "summary_backend": "llm"}
    assert "test-secret-value" not in response.text
    assert client.get("/api/sites?mode=fixture").json()["sites"][0]["turbine_id"] == "T1"
    sites = client.get("/api/sites?mode=archive").json()["sites"]
    assert [site["turbine_id"] for site in sites] == ["T1", "T2"]
    assert sites[0]["latitude"] == 43.645150
    assert sites[0]["coordinate_status"] == "user_provided"


def test_forecast_runs_core_and_downloads_forecast_csv():
    response = client.post("/api/forecasts", json=VALID)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "ok"
    assert result["forecast_id"] == result["fingerprint"].removeprefix("sha256:")
    assert len(result["hours"]) == 24
    downloaded = client.get(f"/api/forecasts/{result['forecast_id']}/download")
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("text/csv")
    assert "power_norm" in downloaded.text.splitlines()[0]
    model_input = client.get(f"/api/forecasts/{result['forecast_id']}/download?kind=model-input")
    assert model_input.status_code == 200
    assert model_input.text.splitlines()[0] == "turbine_id,valid_at,wind_speed_ms,temperature_c"
    assert len(model_input.text.splitlines()) == 25


def test_model_input_download_is_confined_and_hash_checked(tmp_path, monkeypatch):
    result = client.post("/api/forecasts", json=VALID).json()
    payload = b"turbine_id,valid_at,wind_speed_ms,temperature_c\nT1,2026-02-01T00:00:00Z,4,2\n"
    digest = hashlib.sha256(payload).hexdigest()
    model_input_dir = tmp_path / "model_inputs"
    model_input_dir.mkdir()
    (model_input_dir / f"{digest}.csv").write_bytes(payload)
    monkeypatch.setattr(api, "artifact_dir", lambda: tmp_path)
    with api._FORECASTS_LOCK:
        api._FORECASTS[result["forecast_id"]]["model_input"] = {
            "schema_version": "weather-features-v1", "filename": f"{digest}.csv", "sha256": digest,
        "row_count": 24, "columns": ["turbine_id", "valid_at", "wind_speed_ms", "temperature_c"],
        }
    response = client.get(f"/api/forecasts/{result['forecast_id']}/download?kind=model-input")
    assert response.status_code == 200
    assert response.content == payload

    (model_input_dir / f"{digest}.csv").write_bytes(payload + b"tampered")
    bad = client.get(f"/api/forecasts/{result['forecast_id']}/download?kind=model-input")
    assert bad.status_code == 422
    assert bad.json()["code"] == "DATA_INVALID"


def test_invalid_forecast_and_download_kind_have_structured_errors():
    invalid = client.post("/api/forecasts", json={**VALID, "horizon_hours": 12})
    assert invalid.status_code == 422
    assert invalid.json()["status"] == "error"
    assert invalid.json()["code"] == "INVALID_INPUT"
    kind = client.get("/api/forecasts/" + "a" * 64 + "/download?kind=anything")
    assert kind.status_code == 422
    assert kind.json()["status"] == "error"
    assert kind.json()["code"] == "INVALID_INPUT"


def test_unknown_forecast_id_returns_404():
    response = client.get("/api/forecasts/" + "f" * 64 + "/download")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_explanations_use_stored_result_and_ignore_client_prediction(monkeypatch):
    created = client.post("/api/forecasts", json=VALID).json()
    seen = []

    def summarize(result, backend):
        seen.append((result, backend))
        return {"text": "mocked", "backend": "template", "forecast_fingerprint": result["fingerprint"], "warning": None}

    monkeypatch.setattr(api, "summarize_forecast", summarize)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = client.post(
        f"/api/forecasts/{created['forecast_id']}/explanation",
        json={"backend": "llm", "result": {"status": "ok", "hours": []}},
    )
    # Extra fields are rejected, so client-provided forecast content cannot replace stored facts.
    assert response.status_code == 422
    response = client.post(f"/api/forecasts/{created['forecast_id']}/explanation", json={"backend": "llm"})
    assert response.status_code == 200
    assert response.json()["text"] == "mocked"
    assert seen[0][0]["fingerprint"] == created["fingerprint"]
    assert seen[0][1] == "llm"


def test_unexpected_tool_failure_is_sanitized_http_500(monkeypatch):
    import agent
    secret = "secret-provider-internal-value"

    def broken_weather(*args):
        raise RuntimeError(secret)

    monkeypatch.setattr(api, "run_forecast", lambda request: agent.run_forecast(request, weather_tool=broken_weather))
    response = client.post("/api/forecasts", json=VALID)
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert secret not in response.text


def test_archive_forecast_maps_missing_weather_to_503():
    response = client.post("/api/forecasts", json={**VALID, "mode": "archive"})
    assert response.status_code == 503
    assert response.json()["status"] == "error"
    assert response.json()["code"] == "WEATHER_UNAVAILABLE"


def test_unknown_api_route_does_not_fall_through_to_frontend():
    response = client.get("/api/no-such-route")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_questions_use_stored_forecast_without_requiring_api_key(monkeypatch):
    created = client.post("/api/forecasts", json=VALID).json()
    seen = []

    def answer(result, question, backend):
        seen.append((result, question, backend))
        return {"text": "grounded answer", "backend": "template",
                "forecast_fingerprint": result["fingerprint"], "warning": None}

    monkeypatch.setattr(api, "answer_question", answer)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = client.post(
        f"/api/forecasts/{created['forecast_id']}/questions",
        json={"question": "When is the forecast peak?", "backend": "llm"},
    )
    assert response.status_code == 200
    assert response.json()["text"] == "grounded answer"
    assert len(seen) == 1
    assert seen[0][1:] == ("When is the forecast peak?", "llm")
    assert seen[0][0]["fingerprint"] == created["fingerprint"]

    invalid = client.post(
        f"/api/forecasts/{created['forecast_id']}/questions",
        json={"question": "   ", "backend": "llm"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "INVALID_INPUT"
