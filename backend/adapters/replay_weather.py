"""Offline cache of dated ECMWF runs for a conditional February replay.

Open-Meteo documents the Single Runs archive, but does not publish an observed
availability timestamp for each historical run. Cache provenance states that
limit explicitly; no record here is a verified historical receipt log.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from backend.adapters.weather import ARCHIVE_URL, MODEL, SITES, _forecast_digest, _parse_forecast
from backend.core.contracts import FIRST_ORIGIN, ForecastError, artifact_dir, fingerprint, iso, utc_time

DOC_URL = "https://open-meteo.com/en/docs/single-runs-api"
RUN_POLICY = "previous_day_00z_for_18z_origin"
AVAILABILITY_BASIS = "provider_documented_conservative_24h"
MAX_RAW_BYTES = 2_000_000


def cache_dir() -> Path:
    return Path(os.getenv("REPLAY_WEATHER_DIR", str(artifact_dir() / "replay_weather")))


def _request(site: dict, origin: str, horizon_hours: int, mode: str) -> tuple[dict, dict, Path]:
    if mode not in ("archive", "provider_documented"):
        raise ForecastError("INVALID_INPUT", "Неверный режим февральского прогона.")
    if site not in SITES or type(horizon_hours) is not int or horizon_hours not in (24, 48):
        raise ForecastError("INVALID_INPUT", "Неверная турбина или горизонт февральского прогона.")
    when = utc_time(origin)
    first = utc_time(FIRST_ORIGIN)
    if iso(when) != origin or when != when.replace(hour=18, minute=0, second=0, microsecond=0) or not first <= when < first + timedelta(days=28):
        raise ForecastError("INVALID_INPUT", "Февральский прогон принимает только ежедневные точки запуска в 18:00 UTC.")
    run = (when - timedelta(days=1)).replace(hour=0)
    assumed_by = run + timedelta(hours=24)
    if assumed_by > when or when - run < timedelta(hours=24):
        raise ForecastError("INVALID_INPUT", "Недостаточный запас времени после выпуска погодной модели.")
    params = {"latitude": site["latitude"], "longitude": site["longitude"],
              "models": MODEL, "run": run.strftime("%Y-%m-%dT%H:00"),
              "hourly": "temperature_2m,wind_speed_10m", "wind_speed_unit": "ms",
              "temperature_unit": "celsius", "timezone": "UTC"}
    identity = {"version": 1, "turbine_id": site["turbine_id"], "origin": origin,
                "latitude": site["latitude"], "longitude": site["longitude"],
                "source_url": ARCHIVE_URL, "params": params}
    name = f"{site['turbine_id']}-{when:%Y%m%dT%H}-{fingerprint(identity)[7:23]}"
    return identity, {"run": run, "assumed_by": assumed_by}, Path(name)


def _validate(raw: bytes, meta: dict, identity: dict, timing: dict, horizon_hours: int) -> dict:
    if not isinstance(meta, dict) or type(meta.get("version")) is not int or meta["version"] != 1 or meta.get("request") != identity:
        raise ForecastError("WEATHER_UNAVAILABLE", "Кэш погодного выпуска повреждён: неверная идентичность запроса.")
    if not raw or len(raw) > MAX_RAW_BYTES:
        raise ForecastError("WEATHER_UNAVAILABLE", "Кэш погодного выпуска повреждён: неверный размер ответа.")
    raw_sha = hashlib.sha256(raw).hexdigest()
    if meta.get("raw_sha256") != raw_sha:
        raise ForecastError("WEATHER_UNAVAILABLE", "Кэш погодного выпуска повреждён: контрольная сумма не совпала.")
    try:
        data = json.loads(raw)
        rows, grid_lat, grid_lon, by_hour = _parse_forecast(data, identity["origin"], horizon_hours)
        stamps = sorted(by_hour)
        if (not stamps or utc_time(stamps[0]) != timing["run"]
                or any(utc_time(b) - utc_time(a) != timedelta(hours=1) for a, b in zip(stamps, stamps[1:]))):
            raise ValueError("non-contiguous full run")
        canonical = _forecast_digest({"turbine_id": identity["turbine_id"],
                                      "latitude": identity["latitude"], "longitude": identity["longitude"]},
                                     {"model": MODEL, "run": identity["params"]["run"]},
                                     grid_lat, grid_lon, by_hour)
        if meta.get("forecast_sha256") != canonical:
            raise ValueError("full forecast digest mismatch")
        if utc_time(meta["retrieved_at"]) > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("retrieval timestamp in future")
        if (meta.get("initialized_at") != iso(timing["run"])
                or meta.get("assumed_available_by") != iso(timing["assumed_by"])
                or meta.get("available_at") is not None
                or meta.get("availability_verified") is not False
                or meta.get("availability_basis") != AVAILABILITY_BASIS
                or meta.get("run_policy") != RUN_POLICY
                or meta.get("provider_documentation") != DOC_URL):
            raise ValueError("provenance mismatch")
    except (UnicodeError, ValueError, TypeError, KeyError, ForecastError) as exc:
        raise ForecastError("WEATHER_UNAVAILABLE", "Кэш погодного выпуска повреждён или неполон.") from exc
    manifest = {"turbine_id": identity["turbine_id"], "run_id": identity["params"]["run"],
                "provider": "Open-Meteo Single Runs / ecmwf_ifs", "source_url": ARCHIVE_URL,
                "initialized_at": iso(timing["run"]), "available_at": None,
                "assumed_available_by": iso(timing["assumed_by"]),
                "availability_basis": AVAILABILITY_BASIS, "availability_verified": False,
                "provenance_status": "provider_documented", "provider_documentation": DOC_URL,
                "run_policy": RUN_POLICY, "retrieved_at": meta["retrieved_at"],
                "raw_sha256": raw_sha, "forecast_sha256": canonical,
                "interpolation": "none", "wind_height_m": 10, "temperature_height_m": 2,
                "weather_model": MODEL, "wind_height_status": "provider_feature_not_sensor_measurement",
                "grid_latitude": grid_lat, "grid_longitude": grid_lon}
    return {"manifest": manifest, "rows": rows}


def _read_entry(path: Path, identity: dict, timing: dict, horizon_hours: int) -> dict:
    if path.is_symlink() or not path.is_dir():
        raise ForecastError("WEATHER_UNAVAILABLE", "Кэш погодного выпуска повреждён или неполон.")
    raw_path, meta_path = path / "raw.json", path / "manifest.json"
    if raw_path.is_symlink() or meta_path.is_symlink():
        raise ForecastError("WEATHER_UNAVAILABLE", "Кэш погодного выпуска повреждён или неполон.")
    try:
        if raw_path.stat().st_size > MAX_RAW_BYTES:
            raise ForecastError("WEATHER_UNAVAILABLE", "Кэш погодного выпуска слишком велик.")
        raw = raw_path.read_bytes()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ForecastError("WEATHER_UNAVAILABLE", "Кэш погодного выпуска повреждён или неполон.") from exc
    return _validate(raw, meta, identity, timing, horizon_hours)


def fetch_replay_weather(site: dict, origin: str, horizon_hours: int, mode: str = "archive") -> dict:
    """Load only a previously downloaded Single Runs response; never call the network."""
    identity, timing, name = _request(site, origin, horizon_hours, mode)
    path = cache_dir() / name
    if not path.exists() and not path.is_symlink():
        raise ForecastError("WEATHER_UNAVAILABLE", "Нет сохранённого погодного выпуска; запустите scripts.fetch_replay_weather.")
    return _read_entry(path, identity, timing, horizon_hours)


def _atomic_entry(path: Path, raw: bytes, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise ForecastError("WEATHER_UNAVAILABLE", "Погодный выпуск уже существует; проверьте кэш перед повтором.")
    temporary = Path(tempfile.mkdtemp(prefix=".replay-weather-", dir=path.parent))
    try:
        for name, content in (("raw.json", raw),
                              ("manifest.json", (json.dumps(meta, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode())):
            with (temporary / name).open("wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        os.rename(temporary, path)
    finally:
        if temporary.exists():
            for child in temporary.iterdir():
                child.unlink()
            temporary.rmdir()


def _download(client: httpx.Client, identity: dict) -> bytes:
    for attempt in range(3):
        try:
            response = client.get(ARCHIVE_URL, params=identity["params"], timeout=30.0, follow_redirects=False)
        except httpx.HTTPError as exc:
            if attempt == 2:
                raise ForecastError("WEATHER_UNAVAILABLE", "Не удалось получить погодный выпуск; повторите позже.") from exc
        else:
            if response.status_code == 200:
                if not response.content or len(response.content) > MAX_RAW_BYTES:
                    raise ForecastError("DATA_INVALID", "Погодный ответ имеет неверный размер.")
                return response.content
            if response.status_code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise ForecastError("WEATHER_UNAVAILABLE", f"Погодный выпуск не получен (HTTP {response.status_code}).")
        time.sleep(0.5 * (attempt + 1))
    raise AssertionError("retry loop did not terminate")


def prepare_replay_weather(output_dir: Path, *, days: int = 28, client: httpx.Client | None = None,
                           cache_only: bool = False) -> dict:
    """Download 2×days entries, resuming valid cache entries without rewriting them."""
    if type(days) is not int or not 1 <= days <= 28:
        raise ValueError("days must be 1..28")
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    own_client = client is None
    if own_client:
        client = httpx.Client()
    assert client is not None
    successes, failures = [], []
    try:
        for day in range(days):
            origin = iso(utc_time(FIRST_ORIGIN) + timedelta(days=day))
            for site in SITES:
                identity, timing, name = _request(site, origin, 48, "archive")
                path = root / name
                try:
                    if path.exists() or path.is_symlink():
                        bundle = _read_entry(path, identity, timing, 48)
                        source = "cache"
                    elif cache_only:
                        raise ForecastError("WEATHER_UNAVAILABLE", "Погодный выпуск отсутствует в кэше.")
                    else:
                        raw = _download(client, identity)
                        retrieved = iso(datetime.now(timezone.utc))
                        data = json.loads(raw)
                        rows, grid_lat, grid_lon, by_hour = _parse_forecast(data, origin, 48)
                        stamps = sorted(by_hour)
                        if (not stamps or utc_time(stamps[0]) != timing["run"]
                                or any(utc_time(b) - utc_time(a) != timedelta(hours=1) for a, b in zip(stamps, stamps[1:]))):
                            raise ForecastError("DATA_INVALID", "Погодный выпуск содержит пропуск во временном ряду.")
                        canonical = _forecast_digest(site, {"model": MODEL, "run": identity["params"]["run"]},
                                                     grid_lat, grid_lon, by_hour)
                        meta = {"version": 1, "request": identity, "initialized_at": iso(timing["run"]),
                                "available_at": None, "assumed_available_by": iso(timing["assumed_by"]),
                                "availability_basis": AVAILABILITY_BASIS, "availability_verified": False,
                                "run_policy": RUN_POLICY, "provider_documentation": DOC_URL,
                                "retrieved_at": retrieved, "raw_sha256": hashlib.sha256(raw).hexdigest(),
                                "forecast_sha256": canonical}
                        _validate(raw, meta, identity, timing, 48)
                        _atomic_entry(path, raw, meta)
                        bundle = {"manifest": {"forecast_sha256": canonical}, "rows": rows}
                        source = "download"
                    successes.append({"turbine_id": site["turbine_id"], "origin": origin,
                                      "run": identity["params"]["run"], "source": source,
                                      "forecast_sha256": bundle["manifest"]["forecast_sha256"]})
                except (ForecastError, OSError, ValueError, UnicodeError) as exc:
                    failures.append({"turbine_id": site["turbine_id"], "origin": origin,
                                     "code": exc.code if isinstance(exc, ForecastError) else "DATA_INVALID",
                                     "message": str(exc) if isinstance(exc, ForecastError) else "Ошибка погодного ответа или записи кэша."})
    finally:
        if own_client:
            client.close()
    report = {"status": "ok" if not failures else "incomplete", "provenance_status": "provider_documented",
              "availability_verified": False, "expected_runs": days * len(SITES),
              "cached_runs": len(successes), "downloads": sum(s["source"] == "download" for s in successes),
              "runs": successes, "failures": failures,
              "limitation": "Точное время доступности каждого исторического выпуска не подтверждено; выбран консервативный выпуск предыдущего дня."}
    report_path = root / "fetch_report.json"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=root, prefix=".fetch-report-", delete=False) as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        temporary = Path(stream.name)
    try:
        os.replace(temporary, report_path)
    finally:
        temporary.unlink(missing_ok=True)
    return report
