from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Event

import pytest
from fastapi.testclient import TestClient

import api
import forecast_store


@pytest.fixture
def dialog(monkeypatch, tmp_path):
    monkeypatch.setattr(forecast_store, "artifact_dir", lambda: tmp_path)
    start = datetime(2026, 2, 1, tzinfo=timezone.utc)
    hours = [{
        "valid_at": (start + timedelta(hours=i)).isoformat().replace("+00:00", "Z"),
        "lead_hour": i + 1,
        "power_norm": 0.8 if 4 <= i < 8 else 0.2,
        "wind_speed_ms": 8.0 if 4 <= i < 8 else 3.0,
        "temperature_c": -2.0 if 4 <= i < 8 else 1.0,
    } for i in range(24)]
    result = {"status": "ok", "fingerprint": "sha256:" + "a" * 64,
              "turbine_id": "T1", "timezone": "Asia/Almaty", "hours": hours,
              "origin": "2026-01-31T23:00:00Z", "horizon_hours": 24, "mode": "fixture",
              "run_id": "test-run", "model_id": "test-model", "trace": [],
              "train_last_interval_start": "2026-01-31T17:00:00Z",
              "model_input": {"schema_version": "weather-features-v1", "sha256": "d" * 64,
                              "filename": "d" * 64 + ".csv", "row_count": 24,
                              "columns": ["turbine_id", "valid_at", "wind_speed_ms", "temperature_c"]},
              "weather_provenance": {"provenance_status": "fixture"},
              "analysis": {"peak_at": hours[4]["valid_at"], "peak_power_norm": 0.8,
                           "min_at": hours[0]["valid_at"], "min_power_norm": 0.2,
                           "clipped_count": 0, "warnings": []}}
    other = deepcopy(result)
    other.update(fingerprint="sha256:" + "b" * 64, turbine_id="T2")
    monkeypatch.setattr(api, "_FORECASTS", OrderedDict([("a" * 64, result), ("b" * 64, other)]))
    monkeypatch.setattr(api, "_CONVERSATIONS", OrderedDict())
    return TestClient(api.app), "/api/forecasts/" + "a" * 64 + "/questions", result


def test_acceptance_dialog_uses_the_selected_four_hours(dialog):
    client, url, _ = dialog
    first = client.post(url, json={"question": "Найди лучшие четыре часа подряд."}).json()
    assert first["backend"] == "template"
    assert first["selection"] == {"start": "2026-02-01T04:00:00Z", "end": "2026-02-01T08:00:00Z"}
    assert "0,800" in first["text"]
    token = first["conversation_id"]
    second = client.post(url, json={"question": "А какой там ветер?", "conversation_id": token}).json()
    assert second["selection"] == first["selection"]
    assert "8,00" in second["text"]
    third = client.post(url, json={"question": "Сравни с последующими четырьмя часами.", "conversation_id": token}).json()
    assert third["conversation_id"] == token
    tables = [item["table"] for item in third["tool_results"] if "table" in item]
    assert len(tables) == 1
    cells = str(tables[0]["rows"])
    assert "0,800" in cells and "0,200" in cells
    assert len(api._CONVERSATIONS[token].messages) == 6


def test_history_is_server_owned_bounded_and_new_dialog_is_empty(dialog, monkeypatch):
    client, url, _ = dialog
    seen = []
    def answer(result, question, backend, *, history, selection):
        seen.append(deepcopy(history))
        return {"text": "Расчётный ответ: " + question, "backend": "template",
                "forecast_fingerprint": result["fingerprint"], "warning": None}
    monkeypatch.setattr(api, "answer_question", answer)
    token = None
    for i in range(8):
        body = {"question": str(i)}
        if token:
            body["conversation_id"] = token
        response = client.post(url, json=body)
        assert response.status_code == 200
        token = response.json()["conversation_id"]
    assert seen[0] == []
    assert len(seen[-1]) == 10
    assert seen[-1][0] == {"role": "user", "content": "2"}
    assert seen[-1][-1] == {"role": "assistant", "content": "Расчётный ответ: 6"}
    fresh = client.post(url, json={"question": "Новый разговор"}).json()
    assert fresh["conversation_id"] != token and seen[-1] == []
    for field in ("history", "selection", "hours", "predictions"):
        bad = client.post(url, json={"question": "Ветер?", field: []})
        assert bad.status_code == 422


def test_table_references_are_retained_for_followup(dialog, monkeypatch):
    client, url, _ = dialog
    first = client.post(url, json={"question": "Найди лучшие четыре отдельных часа"}).json()
    token = first["conversation_id"]
    content = api._CONVERSATIONS[token].messages[-1]["content"]
    assert "ranked_hours" in content and "2026-02-01T05:00:00Z" in content
    assert len(content) <= 6000
    seen = []
    def answer(result, question, backend, *, history, selection):
        seen.extend(history)
        return {"text": "Уточнение", "backend": "template", "forecast_fingerprint": result["fingerprint"], "warning": None}
    monkeypatch.setattr(api, "answer_question", answer)
    followup = client.post(url, json={"question": "А для второго часа?", "conversation_id": token})
    assert followup.status_code == 200 and seen[-1]["content"] == content


def test_conversations_do_not_cross_forecasts_and_evict_explicitly(dialog, monkeypatch):
    client, url, _ = dialog
    monkeypatch.setattr(api, "_MAX_CONVERSATIONS", 1)
    first = client.post(url, json={"question": "Когда лучше?"}).json()
    token = first["conversation_id"]
    wrong = client.post(url.replace("a" * 64, "b" * 64), json={"question": "А там?", "conversation_id": token})
    assert wrong.status_code == 404 and wrong.json()["code"] == "CONVERSATION_NOT_FOUND"
    client.post(url, json={"question": "Когда лучше?"})
    assert len(api._CONVERSATIONS) == 1
    evicted = client.post(url, json={"question": "А там?", "conversation_id": token})
    assert evicted.status_code == 404 and evicted.json()["code"] == "CONVERSATION_NOT_FOUND"


def test_forecast_memory_eviction_restores_disk_result_and_keeps_dialog(dialog, monkeypatch):
    client, url, result = dialog
    forecast_store.save("a" * 64, result)
    first = client.post(url, json={"question": "Когда лучше?"}).json()
    token = first["conversation_id"]
    monkeypatch.setattr(api, "_MAX_FORECASTS", 1)
    replacement = {**result, "fingerprint": "sha256:" + "c" * 64}
    monkeypatch.setattr(api, "run_forecast", lambda request: replacement)
    created = client.post("/api/forecasts", json={"turbine_id": "T1", "horizon_hours": 24,
                                                "mode": "fixture", "origin": "2026-01-31T18:00:00Z"})
    assert created.status_code == 200
    assert "a" * 64 not in api._FORECASTS
    assert token in api._CONVERSATIONS
    restored = client.post(url, json={"question": "Найди лучшие четыре часа подряд", "conversation_id": token})
    assert restored.status_code == 200
    assert restored.json()["selection"]["start"] == "2026-02-01T04:00:00Z"
    assert len(api._CONVERSATIONS[token].messages) == 4
    # A process restart loses dialog state, but the forecast remains available.
    api._FORECASTS.clear()
    api._CONVERSATIONS.clear()
    expired = client.post(url, json={"question": "А там?", "conversation_id": token})
    assert expired.status_code == 404 and expired.json()["code"] == "CONVERSATION_NOT_FOUND"
    fresh = client.post(url, json={"question": "Найди лучшие четыре часа подряд"})
    assert fresh.status_code == 200 and fresh.json()["conversation_id"] != token


def test_missing_forecast_cannot_be_recovered_from_dialog_history(dialog):
    client, url, _ = dialog
    first = client.post(url, json={"question": "Когда лучше?"}).json()
    api._FORECASTS.clear()
    response = client.post(url, json={"question": "А там?", "conversation_id": first["conversation_id"]})
    assert response.status_code == 404 and response.json()["code"] == "NOT_FOUND"


def test_overlapping_questions_do_not_race_history(dialog, monkeypatch):
    client, url, _ = dialog
    token = client.post(url, json={"question": "Когда лучше?"}).json()["conversation_id"]
    started, release = Event(), Event()
    def slow_answer(result, question, backend, **kwargs):
        started.set()
        assert release.wait(timeout=5)
        return {"text": "Ответ", "backend": "template", "forecast_fingerprint": result["fingerprint"], "warning": None}
    monkeypatch.setattr(api, "answer_question", slow_answer)
    body = {"question": "А там?", "conversation_id": token}
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(client.post, url, json=body)
        try:
            assert started.wait(timeout=5)
            second = client.post(url, json=body)
            assert second.status_code == 409 and second.json()["code"] == "CONVERSATION_BUSY"
        finally:
            release.set()
        assert first.result().status_code == 200
    assert len(api._CONVERSATIONS[token].messages) == 4
