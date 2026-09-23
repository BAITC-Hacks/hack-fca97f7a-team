"""User-supplied turbine locations and explicitly synthetic, dated weather runs."""
from __future__ import annotations

import json
from pathlib import Path

from contracts import ForecastError, fixture_dir

SITES = (
    {"turbine_id": "T1", "latitude": 43.645150, "longitude": 78.535604,
     "timezone": "Asia/Almaty", "coordinate_status": "user_provided",
     "coordinate_source": "https://maps.app.goo.gl/iN6svMt69D5qRpFU9"},
    {"turbine_id": "T2", "latitude": 43.643198, "longitude": 78.538828,
     "timezone": "Asia/Almaty", "coordinate_status": "user_provided",
     "coordinate_source": "https://maps.app.goo.gl/8UQMwsYavY6nLvFY8"},
)


def load_sites(mode: str = "fixture") -> list[dict]:
    if mode not in ("fixture", "archive"):
        raise ForecastError("INVALID_INPUT", "Mode must be fixture or archive.")
    return [dict(site) for site in SITES]


def fetch_weather(site: dict, origin: str, horizon_hours: int, mode: str) -> dict:
    if mode == "archive":
        raise ForecastError("WEATHER_UNAVAILABLE", "Verified as-issued archived weather is not configured.")
    if mode != "fixture":
        raise ForecastError("INVALID_INPUT", "Mode must be fixture or archive.")
    if not isinstance(site, dict) or site not in SITES:
        raise ForecastError("INVALID_INPUT", "Weather site must be a registered turbine.")
    if type(horizon_hours) is not int or horizon_hours not in (24, 48):
        raise ForecastError("INVALID_INPUT", "Horizon must be 24 or 48 hours.")
    from contracts import expected_hours, utc_time
    utc_time(origin)
    name = {"2026-01-31T18:00:00Z": "r1", "2026-02-01T18:00:00Z": "r2"}.get(origin)
    if name is None:
        raise ForecastError("WEATHER_UNAVAILABLE", "No synthetic weather run covers this demo origin.")
    path = fixture_dir() / f"{site['turbine_id']}-{name}.json"
    try:
        bundle = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ForecastError("WEATHER_UNAVAILABLE", "Generate synthetic weather with python -m scripts.make_fixtures.") from exc
    wanted = set(expected_hours(origin, horizon_hours))
    return {"manifest": bundle["manifest"],
            "rows": [row for row in bundle["rows"] if row.get("valid_at") in wanted]}
