"""Synthetic run identity and explicit archive boundary."""
import pytest

from backend.core.contracts import ForecastError
from backend.adapters.weather import fetch_weather, load_sites

ORIGINS = ("2026-01-31T18:00:00Z", "2026-02-01T18:00:00Z")


def test_registered_fixture_sites_and_runs():
    sites = load_sites()
    assert [site["turbine_id"] for site in sites] == ["T1", "T2"]
    assert all(site["coordinate_status"] == "user_provided" for site in sites)
    assert [(site["latitude"], site["longitude"]) for site in sites] == [(43.645150, 78.535604), (43.643198, 78.538828)]
    assert sites[0]["coordinate_source"] == "https://maps.app.goo.gl/iN6svMt69D5qRpFU9"
    assert sites[1]["coordinate_source"] == "https://maps.app.goo.gl/8UQMwsYavY6nLvFY8"
    for site in sites:
        first = fetch_weather(site, ORIGINS[0], 48, "fixture")
        second = fetch_weather(site, ORIGINS[1], 48, "fixture")
        assert len(first["rows"]) == len(second["rows"]) == 48
        assert first["manifest"]["run_id"] != second["manifest"]["run_id"]
        overlap = {row["valid_at"]: row for row in first["rows"]}
        assert any(row["valid_at"] in overlap and row["wind_speed_ms"] != overlap[row["valid_at"]]["wind_speed_ms"]
                   for row in second["rows"])
        assert fetch_weather(site, ORIGINS[0], 24, "fixture")["rows"] == first["rows"][:24]


def test_archive_never_uses_fixtures():
    assert load_sites("archive") == load_sites("fixture")
    with pytest.raises(ForecastError, match="Архив недоступен") as error:
        fetch_weather(load_sites()[0], ORIGINS[0], 24, "archive")
    assert error.value.code == "WEATHER_UNAVAILABLE"
    with pytest.raises(ForecastError) as error:
        fetch_weather({"turbine_id": "T1", "latitude": 9}, ORIGINS[0], 24, "fixture")
    assert error.value.code == "INVALID_INPUT"
