from datetime import datetime, timedelta, timezone

import pytest

from backend.services.forecast_tools import TOOL_SCHEMAS, execute_tool, local_question


def result(powers=(0.1, 0.2, 0.9, 0.8, 0.3, 0.4, 0.1, 0.2, 0.1, 0.2)):
    first = datetime(2026, 2, 1, 0, tzinfo=timezone.utc)
    return {"status": "ok", "timezone": "Asia/Almaty", "hours": [
        {"valid_at": (first + i * timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
         "power_norm": value, "wind_speed_ms": 2.0 + i,
         "temperature_c": -4.0 + i} for i, value in enumerate(powers)]}


def test_schema_names_and_strict_parameters():
    assert {item["name"] for item in TOOL_SCHEMAS} == {
        "best_hours", "period_details", "average_power", "compare_periods", "power_changes"}
    assert all(item["strict"] and item["parameters"]["additionalProperties"] is False and
               set(item["parameters"]["required"]) == set(item["parameters"]["properties"])
               for item in TOOL_SCHEMAS)


def test_best_contiguous_and_followups_use_exact_selected_period():
    forecast = result()
    first = local_question(forecast, "Найди лучшие четыре часа подряд")
    assert first["tool"] == "best_hours"
    assert first["selection"] == {"start": "2026-02-01T02:00:00Z", "end": "2026-02-01T06:00:00Z"}
    assert first["data"]["mean_power_norm"] == pytest.approx(0.6)
    assert "[0,1].\n\nПериод:" in first["text"]
    wind = local_question(forecast, "А какой там ветер?", first["selection"])
    assert wind["tool"] == "period_details"
    assert wind["data"]["mean_wind_speed_ms"] == pytest.approx(5.5)
    assert len(wind["table"]["rows"]) == 4
    assert wind["table"]["rows"][0][0] == "01.02.2026 07:00 · UTC+05:00"
    assert "м/с.\n\nПериод" in wind["text"]
    comparison = local_question(forecast, "Сравни с последующими четырьмя часами", first["selection"])
    assert comparison["tool"] == "compare_periods"
    assert comparison["data"]["second"]["start"] == first["selection"]["end"]
    assert comparison["data"]["second"]["mean_power_norm"] == pytest.approx(0.15)
    assert comparison["data"]["delta_mean_power_norm"] == pytest.approx(-0.45)
    assert len(comparison["table"]["rows"]) == 2


def test_scattered_hours_do_not_claim_contiguous_selection():
    answer = execute_tool(result(), "best_hours", {"count": 3, "contiguous": False, "order": "best"})
    assert answer["selection"] is None
    assert [hour["power_norm"] for hour in answer["data"]["hours"]] == [0.9, 0.8, 0.4]
    assert "отдельных" in answer["text"]


def test_local_explicit_scattered_hours_between_count_and_noun():
    answer = local_question(result(), "Найди лучшие четыре отдельных часа")
    assert answer["tool"] == "best_hours"
    assert answer["data"]["count"] == 4
    assert answer["data"]["contiguous"] is False
    assert answer["selection"] is None


def test_ties_choose_earliest_window_and_minimum():
    forecast = result((0.5, 0.5, 0.1, 0.1))
    best = execute_tool(forecast, "best_hours", {"count": 2, "contiguous": True, "order": "best"})
    assert best["selection"]["start"] == "2026-02-01T00:00:00Z"
    worst = execute_tool(forecast, "best_hours", {"count": 2, "contiguous": True, "order": "worst"})
    assert worst["selection"]["start"] == "2026-02-01T02:00:00Z"


def test_period_average_and_explicit_comparison():
    forecast = result()
    avg = execute_tool(forecast, "average_power", {"start": "2026-02-01T00:00:00Z", "end": "2026-02-01T02:00:00Z"})
    assert avg["data"]["mean_power_norm"] == pytest.approx(0.15)
    comparison = execute_tool(forecast, "compare_periods", {
        "start": "2026-02-01T00:00:00Z", "end": "2026-02-01T02:00:00Z",
        "comparison_start": "2026-02-01T02:00:00Z", "comparison_end": "2026-02-01T04:00:00Z"})
    assert comparison["data"]["second"]["mean_power_norm"] == pytest.approx(0.85)
    assert "| ---" not in comparison["text"]
    assert "Во втором периоде" in comparison["text"] and "Первый:" in comparison["text"]
    assert ".\n\nПервый:" in comparison["text"] and ".\n\nВторой:" in comparison["text"]


def test_compact_local_period_does_not_repeat_date_or_timezone():
    answer = execute_tool(result(), "average_power", {
        "start": "2026-02-01T00:00:00Z", "end": "2026-02-01T02:00:00Z"})
    assert "01.02.2026, 05:00–07:00 · UTC+05:00 (Asia/Almaty)" in answer["text"]
    assert "[0,1].\n\nПериод" in answer["text"]
    assert answer["text"].count("01.02.2026") == 1
    assert answer["selection"] == {"start": "2026-02-01T00:00:00Z", "end": "2026-02-01T02:00:00Z"}
    assert answer["data"]["mean_power_norm"] == pytest.approx(0.15)


def test_cross_midnight_period_shows_both_dates_once():
    forecast = result((0.2, 0.4))
    start = datetime(2026, 2, 1, 18, tzinfo=timezone.utc)
    for index, hour in enumerate(forecast["hours"]):
        hour["valid_at"] = (start + timedelta(hours=index)).isoformat().replace("+00:00", "Z")
    answer = execute_tool(forecast, "average_power", {
        "start": "2026-02-01T18:00:00Z", "end": "2026-02-01T20:00:00Z"})
    assert "01.02.2026 23:00 – 02.02.2026 01:00 · UTC+05:00 (Asia/Almaty)" in answer["text"]


def test_daylight_saving_change_shows_both_offsets():
    forecast = result((0.2, 0.4))
    forecast["timezone"] = "Europe/Berlin"
    start = datetime(2026, 10, 25, 0, tzinfo=timezone.utc)
    for index, hour in enumerate(forecast["hours"]):
        hour["valid_at"] = (start + timedelta(hours=index)).isoformat().replace("+00:00", "Z")
    answer = execute_tool(forecast, "average_power", {
        "start": "2026-10-25T00:00:00Z", "end": "2026-10-25T02:00:00Z"})
    assert "UTC+02:00 → UTC+01:00 (Europe/Berlin)" in answer["text"]


def test_power_changes_are_only_between_adjacent_hours():
    forecast = result((0.1, 0.4, 0.1, 0.2))
    rises = execute_tool(forecast, "power_changes", {"threshold": 0.25, "direction": "up"})
    assert len(rises["data"]["changes"]) == 1
    assert rises["data"]["changes"][0]["delta_power_norm"] == pytest.approx(0.3)
    both = execute_tool(forecast, "power_changes", {"threshold": 0.25, "direction": "both"})
    assert len(both["data"]["changes"]) == 2
    assert both["data"]["changes"][0]["power_before_norm"] == pytest.approx(0.1)
    assert both["data"]["changes"][0]["power_after_norm"] == pytest.approx(0.4)
    assert "Мощность [0,1]" in both["table"]["columns"]
    forecast["hours"][1]["valid_at"] = "2026-02-01T09:00:00Z"
    assert not execute_tool(forecast, "power_changes", {"threshold": 0.25, "direction": "both"})["data"]["changes"]


@pytest.mark.parametrize("field,value", [("power_norm", float("nan")), ("wind_speed_ms", -1),
                                          ("temperature_c", float("inf")), ("power_norm", True),
                                          ("power_norm", 1.2)])
def test_bad_hour_is_rejected(field, value):
    forecast = result()
    forecast["hours"][0][field] = value
    with pytest.raises(ValueError):
        execute_tool(forecast, "best_hours", {"count": 1, "contiguous": True, "order": "best"})


def test_missing_hour_rejects_period_and_skips_discontinuous_window():
    forecast = result((0.1, 0.2, 0.9, 0.8))
    forecast["hours"][1]["valid_at"] = "2026-02-01T09:00:00Z"
    with pytest.raises(ValueError, match="полного набора"):
        execute_tool(forecast, "period_details", {"start": "2026-02-01T00:00:00Z", "end": "2026-02-01T03:00:00Z"})
    best = execute_tool(forecast, "best_hours", {"count": 2, "contiguous": True, "order": "best"})
    assert best["selection"]["start"] == "2026-02-01T02:00:00Z"


def test_ambiguous_question_and_energy_limit():
    forecast = result()
    assert "отдельный" in local_question(forecast, "Когда лучше ? ")["text"]
    assert "МВт·ч" in local_question(forecast, "сколько выработаем?")["text"]
    assert "Уточните период" in local_question(forecast, "А какой там ветер?")["text"]
    assert local_question(forecast, "Кто победил в футболе?") is None


def test_zero_threshold_omits_unchanged_hours_and_single_peak_is_supported():
    forecast = result((0.1, 0.1, 0.9, 0.9))
    changes = execute_tool(forecast, "power_changes", {"threshold": 0, "direction": "both"})
    assert len(changes["data"]["changes"]) == 1
    peak = local_question(forecast, "Назови лучший час прогноза")
    assert peak["data"]["hours"][0]["valid_at"] == "2026-02-01T02:00:00Z"
    assert peak["selection"] == {"start": "2026-02-01T02:00:00Z", "end": "2026-02-01T03:00:00Z"}
    wind = local_question(forecast, "А какой там ветер?", peak["selection"])
    assert wind["data"]["mean_wind_speed_ms"] == pytest.approx(4)
    with pytest.raises(ValueError):
        local_question(forecast, "Найди лучшие 0 часов")


def test_explicit_utc_period_in_local_question():
    forecast = result()
    answer = local_question(forecast, "Какая средняя мощность с 2026-02-01T00:00:00Z по 2026-02-01T02:00:00Z?")
    assert answer["tool"] == "average_power"
    assert answer["data"]["mean_power_norm"] == pytest.approx(0.15)


def test_why_power_dropped_uses_computed_before_after_without_causality_claim():
    forecast = result((0.5, 0.5, 0.3, 0.4, 0.1))
    answer = local_question(forecast, "А почему мощность упала?")
    assert answer["tool"] == "power_changes"
    assert answer["data"]["threshold"] == 0
    assert answer["data"]["direction"] == "down"
    assert len(answer["data"]["changes"]) == 2
    assert "0,400 → 0,100" in answer["text"]
    assert "не доказывают" in answer["text"]
    assert "По всему прогнозу" in answer["text"]
    assert "3,00 → 4,00" in answer["table"]["rows"][0][4]


def test_explicit_power_change_threshold_is_respected():
    forecast = result((0.1, 0.2, 0.4))
    answer = local_question(forecast, "Найди изменения мощности на 0,15")
    assert answer["data"]["threshold"] == pytest.approx(0.15)
    assert len(answer["data"]["changes"]) == 1
    with pytest.raises(ValueError, match="порог"):
        local_question(forecast, "Найди изменения мощности на 2")
    with pytest.raises(ValueError, match="порог"):
        local_question(forecast, "Найди изменения мощности на -0,2")


def test_invalid_args_and_boundaries_are_safe():
    forecast = result()
    with pytest.raises(ValueError):
        execute_tool(forecast, "best_hours", {"count": True, "contiguous": True, "order": "best"})
    with pytest.raises(ValueError):
        execute_tool(forecast, "average_power", {"start": "2026-02-01T01:30:00Z", "end": "2026-02-01T02:00:00Z"})
    with pytest.raises(ValueError):
        execute_tool(forecast, "compare_periods", {"start": "2026-02-01T08:00:00Z", "end": "2026-02-01T10:00:00Z", "comparison_start": None, "comparison_end": None})
    with pytest.raises(ValueError):
        execute_tool(forecast, "power_changes", {"threshold": float("nan"), "direction": "both"})
