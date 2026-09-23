"""Registered demo sites and explicitly synthetic, dated weather runs."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path

import httpx

from contracts import ForecastError, artifact_dir, expected_hours, fingerprint, fixture_dir, iso, next_live_origin, utc_now, utc_time

SITES = (
    {"turbine_id": "T1", "latitude": 0.0, "longitude": 0.0,
     "timezone": "Asia/Almaty", "coordinate_status": "fixture"},
    {"turbine_id": "T2", "latitude": 0.0, "longitude": 0.03,
     "timezone": "Asia/Almaty", "coordinate_status": "fixture"},
)


ARCHIVE_SITES = (
    {"turbine_id": "T1", "latitude": 43.645150, "longitude": 78.535604,
     "timezone": "Asia/Almaty", "coordinate_status": "organizer-supplied"},
    {"turbine_id": "T2", "latitude": 43.643198, "longitude": 78.538828,
     "timezone": "Asia/Almaty", "coordinate_status": "organizer-supplied"},
)
ARCHIVE_URL = "https://single-runs-api.open-meteo.com/v1/forecast"
LIVE_URL = "https://api.open-meteo.com/v1/forecast"
MODEL = "ecmwf_ifs"
_HOUR = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:00(?::00)?(?:Z)?$")
_SHA = re.compile(r"^[a-f0-9]{64}$")
_REF = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,199}$")


def _unavailable(message: str) -> ForecastError:
    return ForecastError("WEATHER_UNAVAILABLE", message)


def _archive_record(site: dict, origin: str) -> dict:
    """Operator-reviewed external capture evidence; strings alone do not establish truth."""
    path = os.getenv("OPEN_METEO_ARCHIVE_MANIFEST", "").strip()
    if not path:
        raise _unavailable("Архив недоступен: настройте проверенный реестр выпусков прогноза.")
    try:
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
        if (not isinstance(manifest, dict) or type(manifest.get("version")) is not int
                or manifest["version"] != 1
                or not isinstance(manifest.get("runs"), list)):
            raise ValueError("invalid manifest")
        candidates = [r for r in manifest["runs"] if isinstance(r, dict)
                      and r.get("turbine_id") == site["turbine_id"] and r.get("origin") == origin]
        if len(candidates) != 1:
            raise ValueError("missing or ambiguous run")
        record = candidates[0]
        required = {"turbine_id", "origin", "latitude", "longitude", "model", "run",
                    "initialized_at", "available_at", "attestation", "availability_basis",
                    "evidence_ref", "forecast_sha256"}
        if set(record) != required or any(record[k] is None for k in required):
            raise ValueError("incomplete run")
        if (type(record["latitude"]) not in (int, float) or type(record["longitude"]) not in (int, float)
                or record["latitude"] != site["latitude"] or record["longitude"] != site["longitude"]
                or record["model"] != MODEL or record["attestation"] != "reviewed_as_issued"
                or record["availability_basis"] != "external_capture_log"
                or not isinstance(record["evidence_ref"], str) or not _REF.fullmatch(record["evidence_ref"])
                or not isinstance(record["forecast_sha256"], str) or not _SHA.fullmatch(record["forecast_sha256"])):
            raise ValueError("evidence mismatch")
        initialized = utc_time(record["initialized_at"])
        available = utc_time(record["available_at"])
        if (iso(initialized) != record["initialized_at"] or iso(available) != record["available_at"]
                or not isinstance(record["run"], str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:00", record["run"])
                or record["run"] != initialized.strftime("%Y-%m-%dT%H:00")
                or initialized.minute or initialized.second or initialized.microsecond
                or initialized > available or available > utc_time(origin)):
            raise ValueError("run unavailable at origin")
        return record
    except (OSError, ValueError, TypeError, KeyError, ForecastError) as exc:
        raise _unavailable("Архив недоступен: проверьте внешнее свидетельство выпуска и доступности для этой турбины и даты.") from exc


def _provider_hour(value: object) -> str:
    if not isinstance(value, str) or not _HOUR.fullmatch(value):
        raise ValueError("timestamp")
    # Open-Meteo timezone=UTC returns naive UTC strings; explicit UTC only.
    try:
        dt = utc_time(value if value.endswith("Z") else value + "Z")
    except ForecastError as exc:
        raise ValueError("invalid UTC hour") from exc
    if dt.minute or dt.second or dt.microsecond:
        raise ValueError("hour alignment")
    return iso(dt)


def _forecast_digest(site: dict, record: dict, grid_lat: float, grid_lon: float, by_hour: dict) -> str:
    """v1: all forecast hours, not HTTP serialization or volatile generation metadata."""
    content = {"version": 1, "turbine_id": site["turbine_id"],
               "latitude": float(site["latitude"]), "longitude": float(site["longitude"]),
               "model": record["model"], "run": record["run"],
               "grid_latitude": float(grid_lat), "grid_longitude": float(grid_lon),
               "wind_height_m": 10, "temperature_height_m": 2,
               "wind_unit": "m/s", "temperature_unit": "°C", "timezone": "UTC",
               "rows": [by_hour[hour] for hour in sorted(by_hour)]}
    return fingerprint(content).removeprefix("sha256:")


def _archive_weather(site: dict, origin: str, horizon_hours: int) -> dict:
    record = _archive_record(site, origin)  # no network before eligibility is proven
    params = {"latitude": site["latitude"], "longitude": site["longitude"],
              "models": MODEL, "run": record["run"],
              "hourly": "temperature_2m,wind_speed_10m", "wind_speed_unit": "ms",
              "temperature_unit": "celsius", "timezone": "UTC"}
    try:
        response = httpx.get(ARCHIVE_URL, params=params, timeout=8.0, follow_redirects=False)
        if response.status_code == 429:
            raise _unavailable("Лимит погодного API исчерпан; повторите запрос позже.")
        if response.status_code != 200:
            raise _unavailable("Погодный API недоступен; повторите запрос позже.")
        raw = response.content
        digest = hashlib.sha256(raw).hexdigest()
        data = json.loads(raw)
    except httpx.TimeoutException as exc:
        raise _unavailable("Погодный API не ответил вовремя; повторите запрос позже.") from exc
    except httpx.HTTPError as exc:
        raise _unavailable("Погодный API недоступен; повторите запрос позже.") from exc
    except (UnicodeError, ValueError) as exc:
        raise ForecastError("DATA_INVALID", "Ответ погодного API имеет неверный формат.") from exc
    try:
        units = data["hourly_units"]
        hours = data["hourly"]
        grid_lat, grid_lon = data["latitude"], data["longitude"]
        if (type(grid_lat) not in (int, float) or type(grid_lon) not in (int, float)
                or not math.isfinite(grid_lat) or not math.isfinite(grid_lon)
                or not -90 <= grid_lat <= 90 or not -180 <= grid_lon <= 180):
            raise ValueError("grid coordinates")
        if (type(data["utc_offset_seconds"]) is not int or data["utc_offset_seconds"] != 0
                or data["timezone"] not in ("GMT", "UTC")
                or units["time"] not in ("iso8601", "ISO8601")
                or units["wind_speed_10m"] != "m/s" or units["temperature_2m"] != "°C"):
            raise ValueError("units")
        stamps, winds, temps = (hours[k] for k in ("time", "wind_speed_10m", "temperature_2m"))
        if not all(isinstance(a, list) for a in (stamps, winds, temps)) or not len(stamps) == len(winds) == len(temps):
            raise ValueError("array lengths")
        by_hour = {}
        for stamp, wind, temp in zip(stamps, winds, temps):
            stamp = _provider_hour(stamp)
            if (stamp in by_hour or type(wind) not in (int, float) or type(temp) not in (int, float)
                    or not math.isfinite(wind) or not math.isfinite(temp) or wind < 0):
                raise ValueError("duplicate or invalid measurement")
            by_hour[stamp] = {"valid_at": stamp, "wind_speed_ms": float(wind), "temperature_c": float(temp)}
        rows = [by_hour[hour] for hour in expected_hours(origin, horizon_hours)]
        canonical_digest = _forecast_digest(site, record, grid_lat, grid_lon, by_hour)
    except (KeyError, TypeError, ValueError) as exc:
        raise ForecastError("DATA_INVALID", "Погодный ответ содержит пропуски, дубли, неверные единицы или значения.") from exc
    if canonical_digest != record["forecast_sha256"]:
        raise _unavailable("Погодный прогноз изменился по сравнению с проверенным выпуском; проверьте свидетельство.")
    target = artifact_dir() / "weather_raw" / f"{digest}.json"
    temporary = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != raw:
                raise OSError("existing raw response does not match checksum")
        else:
            with tempfile.NamedTemporaryFile(mode="wb", prefix=".weather-", suffix=".tmp",
                                             dir=target.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            # Concurrent writers may have completed while this response was saved.
            if target.exists():
                if target.read_bytes() != raw:
                    raise OSError("existing raw response does not match checksum")
            else:
                os.replace(temporary, target)
                temporary = None
    except OSError as exc:
        raise _unavailable("Не удалось сохранить исходный ответ погоды; проверьте каталог артефактов.") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"manifest": {"turbine_id": site["turbine_id"], "run_id": record["run"],
            "provider": "Open-Meteo Single Runs / ecmwf_ifs", "source_url": ARCHIVE_URL,
            "initialized_at": record["initialized_at"], "available_at": record["available_at"],
            "availability_basis": record["availability_basis"] + ":" + record["evidence_ref"],
            "provenance_status": "verified", "raw_sha256": digest,
            "forecast_sha256": canonical_digest, "interpolation": "none",
            "wind_height_m": 10, "wind_height_status": "proxy_not_hub_height",
            "grid_latitude": data.get("latitude"), "grid_longitude": data.get("longitude")}, "rows": rows}


def _live_weather(site: dict, origin: str, horizon_hours: int) -> dict:
    params = {"latitude": site["latitude"], "longitude": site["longitude"],
              "hourly": "wind_speed_10m,temperature_2m", "wind_speed_unit": "ms",
              "temperature_unit": "celsius", "timezone": "UTC", "forecast_hours": 72}
    try:
        response = httpx.get(LIVE_URL, params=params, timeout=8.0, follow_redirects=False)
        fetched_at = utc_now().isoformat(timespec="microseconds").replace("+00:00", "Z")  # completion, not model initialization
        if response.status_code == 429:
            raise _unavailable("Лимит погодного API исчерпан; повторите запрос позже.")
        if response.status_code != 200:
            raise _unavailable("Погодный API недоступен; повторите запрос позже.")
        raw = response.content
        digest = hashlib.sha256(raw).hexdigest()
        data = json.loads(raw)
    except httpx.TimeoutException as exc:
        raise _unavailable("Погодный API не ответил вовремя; повторите запрос позже.") from exc
    except httpx.HTTPError as exc:
        raise _unavailable("Погодный API недоступен; повторите запрос позже.") from exc
    except (UnicodeError, ValueError) as exc:
        raise ForecastError("DATA_INVALID", "Ответ погодного API имеет неверный формат.") from exc
    try:
        if not isinstance(data, dict) or data.get("error") is True:
            raise ValueError("provider error")
        units, hours = data["hourly_units"], data["hourly"]
        grid_lat, grid_lon = data["latitude"], data["longitude"]
        if (type(grid_lat) not in (int, float) or type(grid_lon) not in (int, float)
                or not math.isfinite(grid_lat) or not math.isfinite(grid_lon)
                or not -90 <= grid_lat <= 90 or not -180 <= grid_lon <= 180
                or type(data["utc_offset_seconds"]) is not int or data["utc_offset_seconds"] != 0
                or data["timezone"] not in ("UTC", "GMT")
                or units["time"] not in ("iso8601", "ISO8601")
                or units["wind_speed_10m"] != "m/s" or units["temperature_2m"] != "°C"):
            raise ValueError("units or grid")
        stamps, winds, temps = (hours[k] for k in ("time", "wind_speed_10m", "temperature_2m"))
        if not all(isinstance(a, list) for a in (stamps, winds, temps)) or not len(stamps) == len(winds) == len(temps):
            raise ValueError("array lengths")
        by_hour = {}
        for stamp, wind, temp in zip(stamps, winds, temps):
            stamp = _provider_hour(stamp)
            if (stamp in by_hour or type(wind) not in (int, float) or type(temp) not in (int, float)
                    or not math.isfinite(wind) or not math.isfinite(temp) or wind < 0):
                raise ValueError("duplicate or invalid measurement")
            by_hour[stamp] = {"valid_at": stamp, "wind_speed_ms": float(wind), "temperature_c": float(temp)}
        rows = [by_hour[hour] for hour in expected_hours(origin, horizon_hours)]
    except (KeyError, TypeError, ValueError, ForecastError) as exc:
        raise ForecastError("DATA_INVALID", "Погодный ответ содержит пропуски, дубли, неверные единицы или значения.") from exc
    _save_raw(raw, digest)
    return {"manifest": {"turbine_id": site["turbine_id"], "run_id": f"live-best-match/{digest}",
            "provider": "Open-Meteo Forecast / best match", "source_url": LIVE_URL,
            "initialized_at": None, "available_at": fetched_at, "fetched_at": fetched_at,
            "availability_basis": "response_received", "provenance_status": "live",
            "raw_sha256": digest, "interpolation": "none", "wind_height_m": 10,
            "wind_height_status": "proxy_not_hub_height", "grid_latitude": grid_lat,
            "grid_longitude": grid_lon}, "rows": rows}


def _save_raw(raw: bytes, digest: str) -> None:
    target = artifact_dir() / "weather_raw" / f"{digest}.json"
    temporary = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != raw:
                raise OSError("existing raw response does not match checksum")
        else:
            with tempfile.NamedTemporaryFile(mode="wb", prefix=".weather-", suffix=".tmp",
                                             dir=target.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            # Exclusive publication: never overwrite a concurrent writer's artifact.
            try:
                os.link(temporary, target)
            except FileExistsError:
                if target.read_bytes() != raw:
                    raise OSError("existing raw response does not match checksum")
    except OSError as exc:
        raise _unavailable("Не удалось сохранить исходный ответ погоды; проверьте каталог артефактов.") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_sites(mode: str = "fixture") -> list[dict]:
    if mode not in ("fixture", "archive", "live"):
        raise ForecastError("INVALID_INPUT", "Режим должен быть fixture, archive или live.")
    return [dict(site) for site in (ARCHIVE_SITES if mode in ("archive", "live") else SITES)]


def fetch_weather(site: dict, origin: str, horizon_hours: int, mode: str) -> dict:
    if mode not in ("fixture", "archive", "live"):
        raise ForecastError("INVALID_INPUT", "Режим должен быть fixture, archive или live.")
    if not isinstance(site, dict) or site not in (ARCHIVE_SITES if mode in ("archive", "live") else SITES):
        raise ForecastError("INVALID_INPUT", "Выберите зарегистрированную турбину для указанного режима.")
    if type(horizon_hours) is not int or horizon_hours not in (24, 48):
        raise ForecastError("INVALID_INPUT", "Горизонт должен составлять 24 или 48 часов.")
    parsed = utc_time(origin)
    if parsed.minute or parsed.second or parsed.microsecond or iso(parsed) != origin:
        raise ForecastError("INVALID_INPUT", "Укажите начало прогноза по целому часу UTC.")
    if mode == "archive":
        return _archive_weather(site, origin, horizon_hours)
    if mode == "live":
        if origin != next_live_origin():
            raise ForecastError("INVALID_INPUT", "Для текущей погоды допустим только ближайший будущий час UTC; создайте прогноз заново.")
        return _live_weather(site, origin, horizon_hours)
    name = {"2026-01-31T18:00:00Z": "r1", "2026-02-01T18:00:00Z": "r2"}.get(origin)
    if name is None:
        raise ForecastError("WEATHER_UNAVAILABLE", "Нет демонстрационного погодного выпуска для этой даты; выберите 31 января или 1 февраля.")
    path = fixture_dir() / f"{site['turbine_id']}-{name}.json"
    try:
        bundle = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ForecastError("WEATHER_UNAVAILABLE", "Демонстрационная погода отсутствует; выполните python -m scripts.make_fixtures.") from exc
    wanted = set(expected_hours(origin, horizon_hours))
    return {"manifest": bundle["manifest"],
            "rows": [row for row in bundle["rows"] if row.get("valid_at") in wanted]}
