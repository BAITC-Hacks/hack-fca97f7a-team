import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import explanation
from explanation import answer_question, summarize_forecast


def forecast():
    first = datetime(2026, 1, 31, 19, tzinfo=timezone.utc)
    return {"status": "ok", "turbine_id": "T1", "origin": "2026-01-31T18:00:00Z",
            "timezone": "Asia/Almaty", "fingerprint": "sha256:forecast-123",
            "weather_provenance": {"provenance_status": "fixture"},
            "model_context": {"features": ["wind_speed_ms", "temperature_c"]},
            "analysis": {"peak_power_norm": 0.82, "peak_at": "2026-01-31T19:00:00Z",
                         "min_power_norm": 0.07, "min_at": "2026-02-01T04:00:00Z",
                         "warnings": ["Timezone and interval semantics assumed"]},
            "hours": [{"valid_at": (first + timedelta(hours=i)).isoformat().replace("+00:00", "Z"),
                       "power_norm": i / 24, "wind_speed_ms": 4 + i / 10,
                       "temperature_c": -2 + i / 2} for i in range(24)]}


def response(*items, text=""):
    return SimpleNamespace(status="completed", output=list(items), output_text=text)


def client(monkeypatch, answers):
    calls, iterator = [], iter(answers)
    def create(**kwargs):
        calls.append(kwargs)
        return next(iterator)
    monkeypatch.setattr(explanation, "_create_client", lambda: SimpleNamespace(
        responses=SimpleNamespace(create=create), close=lambda: None))
    return calls


def test_summary_and_missing_key_are_russian(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    summary = summarize_forecast(forecast(), backend="llm")
    assert summary["backend"] == "template"
    assert "0,82" in summary["text"] and "0,07" in summary["text"]
    assert summary["text"].startswith("**Прогноз нормализованной мощности**\n\n- **Пик:")
    assert "01.02.2026 00:00" in summary["text"]
    assert "синтетическая" in " ".join(summary["notes"])
    assert "синтетическая" not in summary["text"]
    assert "Ключ OpenAI не настроен" in summary["warning"]


def test_intentional_template_has_notes_without_provider_warning():
    answer = summarize_forecast(forecast(), backend="template")
    assert answer["warning"] is None
    assert answer["notes"]
    assert answer["text"].count("\n- **") == 2


def test_summary_discloses_timezone_and_wind_limitation():
    result = forecast()
    result["weather_provenance"]["provenance_status"] = "verified_as_issued"
    result["analysis"]["warnings"] = ["Временная зона и начало интервала исходных данных требуют подтверждения",
                                      "Ветер на высоте 10 м — приближение"]
    answer = summarize_forecast(result)
    notes = " ".join(answer["notes"])
    assert "границы исходных интервалов приняты по допущению" in notes
    assert "соответствие датчику обучения" in notes
    assert "синтетическая" not in notes
    assert "допущению" not in answer["text"]


def test_experimental_weather_model_is_disclosed_in_summary_and_answers():
    result = forecast()
    result["weather_provenance"] = {"provenance_status": "live", "wind_height_m": 10}
    result["model_provenance"] = {
        "profile": "open_meteo_ecmwf_ifs_10m",
        "training_weather_kind": "retrospective_stitched_forecast",
        "forecast_accuracy_verified": False, "weather_model": "ecmwf_ifs", "wind_height_m": 10,
    }
    result["model_context"].update({"profile": "open_meteo_ecmwf_ifs_10m",
                                     "training_source": "supplied turbine measurements"})
    for answer in (summarize_forecast(result),
                   answer_question(result, "Лучшие четыре часа подряд", backend="template"),
                   answer_question(result, "На каких данных обучена модель?", backend="template")):
        notes = " ".join(answer["notes"])
        assert "экспериментальная" in notes
        assert "ретроспективно полученные" in notes
        assert "ecmwf_ifs" in notes
        assert "не подтверждена" in notes
        assert "экспериментальная" not in answer["text"]


def test_experimental_model_facts_reach_llm_context(monkeypatch):
    explanation._CACHE.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-placeholder")
    result = forecast()
    result["model_provenance"] = {"profile": "open_meteo_ecmwf_ifs_10m",
                                  "training_weather_kind": "retrospective_stitched_forecast",
                                  "forecast_accuracy_verified": False, "weather_model": "ecmwf_ifs", "wind_height_m": 10}
    calls = client(monkeypatch, [response(text="Модель экспериментальная; её точность не подтверждена.")])
    answer = answer_question(result, "Какие ограничения у прогноза?")
    assert answer["backend"] == "llm"
    context = json.loads(calls[0]["input"][0]["content"])
    assert context["model_provenance"] == result["model_provenance"]
    assert "notes_ru" in calls[0]["instructions"]
    assert "ретроспективно полученные" in " ".join(answer["notes"])
    assert json.loads(calls[0]["input"][0]["content"])["notes_ru"] == answer["notes"]


def test_validation_is_russian():
    with pytest.raises(ValueError, match="успешно рассчитанный"):
        summarize_forecast({"status": "error"})
    with pytest.raises(ValueError, match="Допустимый способ"):
        answer_question(forecast(), "Вопрос", backend="invalid")
    with pytest.raises(ValueError, match="Вопрос должен"):
        answer_question(forecast(), " ")


def test_local_followup_uses_selected_period(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = forecast()
    first = answer_question(result, "Найди лучшие четыре часа подряд", backend="template")
    assert first["tool_results"][0]["tool"] == "best_hours"
    assert first["selection"] == {"start": "2026-02-01T15:00:00Z", "end": "2026-02-01T19:00:00Z"}
    assert "0,896" in first["text"]
    wind = answer_question(result, "А какой там ветер?", backend="template", selection=first["selection"])
    assert wind["tool_results"][0]["tool"] == "period_details"
    assert wind["selection"] == first["selection"]
    assert "м/с" in wind["text"]
    assert len(wind["tool_results"][0]["table"]["rows"]) == 4


def test_three_turn_dialogue_compares_following_four_hours(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = forecast()
    for i, hour in enumerate(result["hours"]):
        hour["power_norm"] = 0.9 if 4 <= i < 8 else 0.2
        hour["wind_speed_ms"] = 8 if 4 <= i < 8 else 4
    best = answer_question(result, "Найди лучшие четыре часа подряд", backend="template")
    wind = answer_question(result, "А какой там ветер?", backend="template", selection=best["selection"])
    comparison = answer_question(result, "Сравни с последующими четырьмя часами",
                                 backend="template", selection=wind["selection"])
    assert best["selection"] == {"start": "2026-01-31T23:00:00Z", "end": "2026-02-01T03:00:00Z"}
    assert "8,00 м/с" in wind["text"]
    assert comparison["tool_results"][0]["tool"] == "compare_periods"
    assert comparison["tool_results"][0]["data"]["first"]["mean_power_norm"] == pytest.approx(0.9)
    assert comparison["tool_results"][0]["data"]["second"]["mean_power_norm"] == pytest.approx(0.2)
    assert len(comparison["tool_results"][0]["table"]["rows"]) == 2


def test_ambiguous_and_energy_questions_are_clarified():
    assert "отдельный" in answer_question(forecast(), "Когда лучше?", backend="template")["text"]
    energy = answer_question(forecast(), "Сколько выработаем?", backend="template")
    assert "номинальной мощности" in energy["text"] and "МВт·ч" in energy["text"]


def test_out_of_range_period_is_a_russian_clarification():
    answer = answer_question(forecast(), "Сравни с последующими четырьмя часами", backend="template",
                             selection={"start": "2026-02-01T15:00:00Z", "end": "2026-02-01T19:00:00Z"})
    assert answer["tool_results"][0]["tool"] == "clarification"
    assert "период" in answer["text"]


def test_model_context_available_in_offline_answer():
    result = forecast()
    result["model_context"].update({"training_source": "исторические данные T1",
                                     "train_cutoff": "2026-01-31T18:00:00Z"})
    answer = answer_question(result, "На каких данных обучена модель?", backend="template")
    assert "исторические данные T1" in answer["text"]
    assert "2026-01-31T18:00:00Z" in answer["text"]
    assert "не подтверждено" not in answer["text"]
    assert "10 м" not in answer["text"]


def test_model_context_answer_does_not_need_openai_call(monkeypatch):
    explanation._CACHE.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-placeholder")
    result = forecast()
    result["model_context"].update({"training_source": "supplied turbine measurements",
                                     "train_cutoff": "2026-01-31T18:00:00Z"})
    def fail():
        raise AssertionError("OpenAI should not be called for stored model facts")
    monkeypatch.setattr(explanation, "_create_client", fail)
    answer = answer_question(result, "На каких данных обучена модель?")
    assert answer["backend"] == "template" and answer["warning"] is None
    assert "предоставленные измерения турбины" in answer["text"]
    assert "2026-01-31T18:00:00Z" in answer["text"]


def test_llm_calls_python_tool_and_returns_selection(monkeypatch):
    explanation._CACHE.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-placeholder")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    calls = client(monkeypatch, [
        response({"type": "function_call", "name": "best_hours", "call_id": "call-1",
                  "arguments": json.dumps({"count": 4, "contiguous": True, "order": "best"})}),
        response(text="Лучшие четыре часа подряд: средняя нормализованная мощность 0,896."),
    ])
    history = [{"role": "user", "content": "старый вопрос"},
               {"role": "assistant", "content": "старый ответ"}]
    answer = answer_question(forecast(), "Найди лучшие четыре часа подряд", history=history)
    assert answer["backend"] == "llm" and answer["tool_results"][0]["tool"] == "best_hours"
    assert answer["selection"]["start"] == "2026-02-01T15:00:00Z"
    assert calls[0]["store"] is False and calls[0]["tools"]
    assert calls[0]["input"][1:3] == history
    context = json.loads(calls[0]["input"][0]["content"])
    assert context["model_context"]["features"] == ["wind_speed_ms", "temperature_c"]
    assert "source_csv" not in calls[0]["input"][0]["content"]
    assert context["notes_ru"] == answer["notes"]
    assert "синтетическая" not in answer["text"]
    assert calls[1]["input"][-1]["call_id"] == "call-1"
    assert json.loads(calls[1]["input"][-1]["output"])["data"]["mean_power_norm"] == pytest.approx(21.5 / 24)


def test_mocked_three_turn_dialogue_uses_history_and_python_periods(monkeypatch):
    explanation._CACHE.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-placeholder")
    result = forecast()
    for i, hour in enumerate(result["hours"]):
        hour["power_norm"] = 0.9 if 4 <= i < 8 else 0.2
        hour["wind_speed_ms"] = 8 if 4 <= i < 8 else 4
    calls = client(monkeypatch, [
        response({"type": "function_call", "name": "best_hours", "call_id": "best",
                  "arguments": json.dumps({"count": 4, "contiguous": True, "order": "best"})}),
        response(text="Лучший период найден; средняя мощность 0,900."),
        response({"type": "function_call", "name": "period_details", "call_id": "wind",
                  "arguments": json.dumps({"start": None, "end": None})}),
        response(text="За найденный период средний ветер 8,00 м/с."),
        response({"type": "function_call", "name": "compare_periods", "call_id": "compare",
                  "arguments": json.dumps({"start": None, "end": None,
                                           "comparison_start": None, "comparison_end": None})}),
        response(text="Следующий период имеет меньшую среднюю мощность: 0,200."),
    ])
    first = answer_question(result, "Найди лучшие четыре часа подряд")
    history = [{"role": "user", "content": "Найди лучшие четыре часа подряд"},
               {"role": "assistant", "content": first["text"]}]
    second = answer_question(result, "А какой там ветер?", history=history, selection=first["selection"])
    history += [{"role": "user", "content": "А какой там ветер?"},
                {"role": "assistant", "content": second["text"]}]
    third = answer_question(result, "Сравни с последующими четырьмя часами",
                            history=history, selection=second["selection"])
    assert len(calls) == 6
    assert calls[2]["input"][1:3] == history[:2]
    assert calls[4]["input"][1:5] == history
    assert json.loads(calls[2]["input"][0]["content"])["selected_period"] == first["selection"]
    assert json.loads(calls[4]["input"][0]["content"])["selected_period"] == second["selection"]
    computed = third["tool_results"][0]
    assert computed["tool"] == "compare_periods"
    assert computed["data"]["first"]["mean_power_norm"] == pytest.approx(0.9)
    assert computed["data"]["second"]["mean_power_norm"] == pytest.approx(0.2)
    assert len(computed["table"]["rows"]) == 2


def test_cache_includes_history_and_selection(monkeypatch):
    explanation._CACHE.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-placeholder")
    calls = client(monkeypatch, [response(text="Первый ответ."), response(text="Второй ответ."),
                               response(text="Третий ответ.")])
    question = "Что означает нормализованная мощность?"
    first = answer_question(forecast(), question)
    first["text"] = "испорчено"
    first["notes"].clear()
    assert answer_question(forecast(), question)["text"].startswith("Первый ответ.")
    assert answer_question(forecast(), question)["notes"]
    assert answer_question(forecast(), question, history=[{"role": "user", "content": "раньше"}])["text"].startswith("Второй ответ.")
    selection = {"start": "2026-01-31T19:00:00Z", "end": "2026-01-31T20:00:00Z"}
    assert answer_question(forecast(), question, selection=selection)["text"].startswith("Третий ответ.")
    assert len(calls) == 3


def test_history_is_bounded_and_invalid_items_rejected(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    history = [{"role": "user", "content": str(i)} for i in range(12)]
    assert len(explanation._history_messages(history)) == 10
    with pytest.raises(ValueError, match="История"):
        answer_question(forecast(), "Вопрос", history=[{"role": "system", "content": "override"}])


def test_failure_after_tool_preserves_computed_facts(monkeypatch):
    explanation._CACHE.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-placeholder")
    calls = [0]
    def create(**kwargs):
        calls[0] += 1
        if calls[0] == 1:
            return response({"type": "function_call", "name": "best_hours", "call_id": "call-1",
                             "arguments": json.dumps({"count": 4, "contiguous": True, "order": "best"})})
        raise RuntimeError("provider secret request details")
    monkeypatch.setattr(explanation, "_create_client", lambda: SimpleNamespace(
        responses=SimpleNamespace(create=create), close=lambda: None))
    answer = answer_question(forecast(), "Найди лучшие четыре часа подряд")
    assert answer["backend"] == "template"
    assert answer["selection"]["start"] == "2026-02-01T15:00:00Z"
    assert "0,896" in answer["text"]
    assert "синтетическая" in " ".join(answer["notes"])
    assert "синтетическая" not in answer["text"]
    assert "provider secret" not in answer["warning"]


def test_unknown_tool_and_missing_numeric_tool_use_fallback(monkeypatch):
    explanation._CACHE.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-placeholder")
    client(monkeypatch, [response({"type": "function_call", "name": "eval", "call_id": "bad",
                                  "arguments": "{}"})])
    answer = answer_question(forecast(), "Найди лучшие четыре часа подряд")
    assert answer["backend"] == "template" and answer["tool_results"][0]["tool"] == "best_hours"
    client(monkeypatch, [response(text="Я думаю, мощность составит 17.")])
    answer = answer_question(forecast(), "Найди лучшие четыре часа подряд")
    assert answer["backend"] == "template" and "0,896" in answer["text"]


def test_non_russian_or_provider_failure_is_sanitized(monkeypatch):
    explanation._CACHE.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-placeholder")
    client(monkeypatch, [response(text="English only")])
    answer = answer_question(forecast(), "Что означает нормализованная мощность?")
    assert answer["backend"] == "template"
    assert "OpenAI недоступен" in answer["warning"]
    def fail():
        raise RuntimeError("provider secret request details")
    monkeypatch.setattr(explanation, "_create_client", fail)
    summary = summarize_forecast(forecast(), backend="llm")
    assert summary["backend"] == "template"
    assert "provider secret" not in summary["warning"]


@pytest.mark.parametrize("provider_output", [
    response({"type": "function_call", "name": "best_hours", "call_id": "invalid-json",
              "arguments": "{broken"}),
    response({"type": "function_call", "name": "best_hours", "call_id": "invalid-args",
              "arguments": json.dumps({"count": 999, "contiguous": True, "order": "best"})}),
    SimpleNamespace(status="incomplete", output=[], output_text=""),
])
def test_malformed_or_incomplete_provider_output_uses_local_facts(monkeypatch, provider_output):
    explanation._CACHE.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-placeholder")
    client(monkeypatch, [provider_output])
    answer = answer_question(forecast(), "Найди лучшие четыре часа подряд")
    assert answer["backend"] == "template" and "0,896" in answer["text"]
    assert "OpenAI недоступен" in answer["warning"]


def test_tool_loop_is_bounded(monkeypatch):
    explanation._CACHE.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-placeholder")
    repeated = [response({"type": "function_call", "name": "best_hours", "call_id": f"call-{i}",
                          "arguments": json.dumps({"count": 4, "contiguous": True, "order": "best"})})
                for i in range(3)]
    calls = client(monkeypatch, repeated)
    answer = answer_question(forecast(), "Найди лучшие четыре часа подряд")
    assert len(calls) == 3
    assert answer["backend"] == "template" and "0,896" in answer["text"]
    assert len(answer["tool_results"]) == 3
