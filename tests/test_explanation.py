import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import explanation
from explanation import answer_question, summarize_forecast


def success_result():
    return {
        "status": "ok", "turbine_id": "T1", "origin": "2026-01-31T18:00:00Z",
        "timezone": "Asia/Almaty", "fingerprint": "sha256:forecast-123",
        "weather_provenance": {"provenance_status": "fixture"},
        "analysis": {
            "peak_power_norm": 0.82, "peak_at": "2026-01-31T19:00:00Z",
            "min_power_norm": 0.07, "min_at": "2026-02-01T04:00:00Z",
            "warnings": ["Timezone and interval semantics assumed"],
        },
    }


def hourly_result():
    result = success_result()
    first = datetime(2026, 1, 31, 19, tzinfo=timezone.utc)
    result["hours"] = [{"valid_at": (first + timedelta(hours=i)).isoformat().replace("+00:00", "Z"),
                        "power_norm": i / 24} for i in range(24)]
    return result


def test_template_summary_uses_analysis_and_local_timezone():
    summary = summarize_forecast(success_result())
    assert summary["backend"] == "template"
    assert summary["forecast_fingerprint"] == "sha256:forecast-123"
    assert summary["warning"] is None
    assert "0,82" in summary["text"] and "0,07" in summary["text"]
    assert "01.02.2026 00:00 UTC+05:00 (Asia/Almaty)" in summary["text"]
    assert "01.02.2026 09:00 UTC+05:00 (Asia/Almaty)" in summary["text"]
    assert "нормализованная" in summary["text"] and "МВт·ч" in summary["text"]
    assert "синтетические" in summary["text"] and "допущению" in summary["text"]


def test_russian_source_timezone_warning_is_disclosed():
    result = success_result()
    result["analysis"]["warnings"] = ["Временная зона и начало интервала исходных данных требуют подтверждения"]
    assert "границы интервалов приняты по допущению" in summarize_forecast(result)["text"]


def test_archive_wind_height_limitation_is_from_provided_warning_only():
    result = success_result()
    result["weather_provenance"]["provenance_status"] = "verified_as_issued"
    result["analysis"]["warnings"] = ["Ветер на высоте 10 м — приближение, не подтверждённое для датчика обучения и высоты ступицы"]
    assert "соответствие датчику обучения" in summarize_forecast(result)["text"]
    result["analysis"]["warnings"] = []
    assert "высоте 10 м" not in summarize_forecast(result)["text"]


def test_missing_key_is_labeled_russian_fallback(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    summary = summarize_forecast(success_result(), backend="llm")
    assert summary["backend"] == "template"
    assert summary["forecast_fingerprint"] == "sha256:forecast-123"
    assert "Ключ OpenAI не настроен" in summary["warning"]
    assert "0,82" in summary["text"]


def test_validation_errors_are_russian():
    with pytest.raises(ValueError, match="успешно рассчитанный"):
        summarize_forecast({"status": "error"})
    with pytest.raises(ValueError, match="Допустимый способ"):
        summarize_forecast(success_result(), backend="anything")
    with pytest.raises(ValueError, match="Вопрос должен"):
        answer_question(success_result(), " ")


@pytest.mark.parametrize("question,minimum", [
    ("В какие шесть часов средняя мощность максимальна?", False),
    ("В какие 6 часов средняя мощность максимальна?", False),
    ("Когда максимален шестичасовой средний прогноз?", False),
    ("Which six-hour period has the highest average output?", False),
    ("Which 6 hours have the highest average output?", False),
    ("В какие шесть часов средняя мощность минимальна?", True),
    ("Найди минимум за 6-часовой период", True),
])
def test_six_hour_windows_calculated_locally(question, minimum):
    result = hourly_result()
    response = answer_question(result, question, backend="template")
    expected = sum(range(6) if minimum else range(18, 24)) / 24 / 6
    assert f"{expected:.3f}".replace(".", ",") in response["text"]
    assert ("01.02.2026 00:00" if minimum else "01.02.2026 18:00") in response["text"]
    assert "синтетическая" in response["text"]
    assert response["forecast_fingerprint"] == result["fingerprint"]


@pytest.mark.parametrize("question", [
    "Каков максимум прогноза на 2026 год?",
    "Когда максимум в 16 часов?",
])
def test_unrelated_digits_do_not_trigger_six_hour_window(question):
    answer = answer_question(hourly_result(), question, backend="template")
    assert "0,82" in answer["text"]
    assert "за шесть" not in answer["text"]


def test_weather_and_unsupported_questions_are_russian(monkeypatch):
    result = hourly_result()
    assert "м/с" in answer_question(result, "Что с ветром и температурой?", backend="template")["text"]
    assert "синтетические" in answer_question(result, "What about weather?", backend="template")["text"]
    unsupported = answer_question(result, "Дай ответ про футбол", backend="template")
    assert unsupported["backend"] == "template"
    assert "В какие шесть часов" in unsupported["text"]
    assert "м/с" not in unsupported["text"]


def test_peak_and_minimum_in_one_question_return_computed_summary():
    answer = answer_question(hourly_result(), "Когда максимум и минимум мощности?", backend="template")
    assert "0,82" in answer["text"] and "0,07" in answer["text"]
    assert "В какие шесть часов" not in answer["text"]


def test_nonconsecutive_hours_are_not_silently_grouped():
    result = hourly_result()
    result["hours"] = result["hours"][:3] + result["hours"][18:21]
    answer = answer_question(result, "Шесть часов с максимальной средней мощностью", backend="template")
    assert "нет шести последовательных часов" in answer["text"]


def test_llm_uses_russian_computed_facts_and_versioned_cache(monkeypatch):
    explanation._CACHE.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-placeholder")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="completed", output_text="Расчётный прогноз для турбины.")
    monkeypatch.setattr(explanation, "_create_client", lambda: SimpleNamespace(
        responses=SimpleNamespace(create=create), close=lambda: None))
    result = hourly_result()
    one = answer_question(result, "В какие шесть часов средняя мощность максимальна?", backend="llm")
    one["text"] = "изменённая копия"
    two = answer_question(result, "В какие шесть часов средняя мощность максимальна?", backend="llm")
    assert two["text"] == "Расчётный прогноз для турбины."
    assert two["backend"] == "llm" and two["forecast_fingerprint"] == result["fingerprint"]
    assert len(calls) == 1
    assert calls[0]["store"] is False
    assert "по-русски" in calls[0]["instructions"] and "не придумывай" in calls[0]["instructions"]
    context = json.loads(calls[0]["input"])
    assert context["calculated_question_facts"]["six_hour_window"]["mean_power_norm"] == pytest.approx(20.5 / 24)
    assert "0,854" in context["calculated_local_answer_ru"]
    assert "unit-test-placeholder" not in calls[0]["input"]
    assert "source_csv" not in calls[0]["input"]
    result["fingerprint"] = "sha256:other"
    answer_question(result, "В какие шесть часов средняя мощность максимальна?", backend="llm")
    monkeypatch.setenv("OPENAI_MODEL", "other-model")
    answer_question(result, "В какие шесть часов средняя мощность максимальна?", backend="llm")
    answer_question(result, "Когда средняя мощность минимальна за шесть часов?", backend="llm")
    assert len(calls) == 4
    assert "forecast-explanation-ru-v2" == explanation._PROMPT_VERSION


def test_llm_can_answer_other_forecast_questions_from_stored_hours(monkeypatch):
    explanation._CACHE.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-placeholder")
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="completed", output_text="Прогноз на этот час указан в таблице.")
    monkeypatch.setattr(explanation, "_create_client", lambda: SimpleNamespace(
        responses=SimpleNamespace(create=create), close=lambda: None))
    answer = answer_question(hourly_result(), "Какая мощность в первый час прогноза?", backend="llm")
    assert answer["backend"] == "llm" and len(calls) == 1
    assert json.loads(calls[0]["input"])["hours"][0]["power_norm"] == 0


def test_llm_failure_preserves_computed_facts_without_exception_details(monkeypatch):
    explanation._CACHE.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-placeholder")
    def fail():
        raise RuntimeError("provider secret request details")
    monkeypatch.setattr(explanation, "_create_client", fail)
    result = summarize_forecast(success_result(), backend="llm")
    assert result["backend"] == "template" and "0,82" in result["text"]
    assert result["forecast_fingerprint"] == "sha256:forecast-123"
    assert "недоступен" in result["warning"]
    assert "RuntimeError" not in result["warning"] and "secret request" not in result["warning"]
