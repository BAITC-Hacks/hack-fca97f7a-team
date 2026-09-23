"""February 2026 decision dates and the historical forecast request boundary."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from backend.adapters.replay_weather import fetch_replay_weather
from backend.core.contracts import ForecastError, SITE_TIMEZONE, iso
from backend.services.agent import run_forecast

FIRST_DATE = date(2026, 2, 1)
LAST_DATE = date(2026, 2, 28)
WEATHER_SOURCES = ("verified", "provider-documented")


def origin_for_date(value: str) -> str:
    """The issue on the preceding day predicts local 00:00 through 23:00."""
    try:
        forecast_date = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ForecastError("INVALID_INPUT", "Выберите дату февраля 2026 года.") from exc
    if forecast_date.isoformat() != value or not FIRST_DATE <= forecast_date <= LAST_DATE:
        raise ForecastError("INVALID_INPUT", "Выберите дату с 1 по 28 февраля 2026 года.")
    first_target = datetime.combine(forecast_date, datetime.min.time(), ZoneInfo(SITE_TIMEZONE))
    return iso(first_target.astimezone(timezone.utc) - timedelta(hours=1))


def run_february_forecast(turbine_id: str, forecast_date: str, horizon_hours: int,
                          weather_source: str) -> dict:
    origin = origin_for_date(forecast_date)
    if weather_source not in WEATHER_SOURCES:
        raise ForecastError("INVALID_INPUT", "Выберите источник архивной погоды.")
    request = {"turbine_id": turbine_id, "origin": origin,
               "horizon_hours": horizon_hours, "mode": "archive"}
    if weather_source == "verified":
        from backend.adapters.operational_weather import fetch_operational_weather
        result = run_forecast(request, weather_tool=fetch_operational_weather)
    else:
        result = run_forecast(request, weather_tool=fetch_replay_weather,
                              allow_documented_archive=True)
    if result.get("status") == "ok":
        return {**result, "forecast_date": forecast_date, "weather_source": weather_source}
    return result


def february_metadata() -> dict:
    dates = [(FIRST_DATE + timedelta(days=offset)).isoformat() for offset in range(28)]
    return {
        "status": "ok", "timezone": SITE_TIMEZONE,
        "first_date": dates[0], "last_date": dates[-1], "dates": dates,
        "origin_rule": "Предыдущий день, 23:00 по Asia/Almaty; первый прогнозный час — 00:00 выбранной даты.",
        "horizon_hours": [24, 48], "turbine_ids": ["T1", "T2"],
        "expected_runs": 56, "expected_forecast_rows_48h": 2688,
        "expected_daily_rows_24h": 1344,
        "actual_power_available": False,
        "weather_sources": {
            "verified": {
                "label": "Подтверждённый архивный выпуск",
                "availability_verified": True,
                "description": "Операционный ECMWF IFS: время Last-Modified всех использованных объектов публичного архива проверяется до момента расчёта.",
            },
            "provider-documented": {
                "label": "Архивный выпуск, время доступности оценено",
                "availability_verified": False,
                "description": "Open-Meteo Single Runs: выпуск предыдущего дня 00:00 UTC; принято ожидание 24 часа. Точное время публикации не подтверждено.",
            },
        },
    }
