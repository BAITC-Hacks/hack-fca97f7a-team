"""Immutable ECMWF operational GRIB receipts for February 2026 replay.

The Google public replica stores original IFS forecast runs, .index byte offsets,
and object Last-Modified times. Fetching is an explicit offline preparation step;
requests only read and verify the resulting local receipt.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

from backend.adapters.weather import SITES
from backend.core.contracts import FIRST_ORIGIN, ForecastError, artifact_dir, expected_hours, fingerprint, iso, utc_time

BASE = "https://storage.googleapis.com/ecmwf-open-data"
DOC = "https://confluence.ecmwf.int/display/UDOC/ECMWF+open+data%3A+real-time+forecasts+from+IFS+and+AIFS"
PARAMS = ("2t", "10u", "10v")
STEPS = tuple(range(18, 67, 3))
MAX_INDEX = 100_000
MAX_FIELD = 4_000_000
_DECODED_RECEIPTS: set[str] = set()


def cache_dir() -> Path:
    return Path(os.getenv("OPERATIONAL_WEATHER_DIR", str(artifact_dir() / "operational_weather")))


def _run(origin: str) -> tuple[datetime, datetime, str, Path]:
    when = utc_time(origin)
    first = utc_time(FIRST_ORIGIN)
    if iso(when) != origin or when.hour != 18 or when.minute or when.second or when.microsecond or not first <= when < first + timedelta(days=28):
        raise ForecastError("INVALID_INPUT", "Операционный архив принимает дневные запуски с 31 января по 27 февраля в 18:00 UTC.")
    init = when.replace(hour=0)
    stamp = init.strftime("%Y%m%d")
    prefix = f"{stamp}/00z/ifs/0p25/oper/{stamp}000000-"
    return when, init, prefix, Path(f"{stamp}-00z")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _last_modified(response: httpx.Response, origin: datetime) -> str:
    try:
        value = parsedate_to_datetime(response.headers["Last-Modified"]).astimezone(timezone.utc)
    except (KeyError, TypeError, ValueError) as exc:
        raise ForecastError("WEATHER_UNAVAILABLE", "У архивного объекта нет времени публикации.") from exc
    if value > origin or value < origin - timedelta(days=2):
        raise ForecastError("WEATHER_UNAVAILABLE", "Архивный погодный объект не подтверждён как доступный на момент прогноза.")
    return iso(value)


def _fetch(client: httpx.Client, url: str, origin: datetime, *, start: int | None = None,
           length: int | None = None) -> tuple[bytes, str]:
    headers = {"Range": f"bytes={start}-{start + length - 1}"} if start is not None and length is not None else {}
    for attempt in range(3):
        try:
            response = client.get(url, headers=headers, timeout=45, follow_redirects=False)
        except httpx.HTTPError as exc:
            if attempt == 2:
                raise ForecastError("WEATHER_UNAVAILABLE", "Не удалось скачать выпуск ECMWF; повторите загрузку.") from exc
        else:
            if response.status_code not in (429, 500, 502, 503, 504) or attempt == 2:
                break
        time.sleep(.5 * (attempt + 1))
    if response.status_code != (206 if headers else 200):
        raise ForecastError("WEATHER_UNAVAILABLE", f"Выпуск ECMWF недоступен: HTTP {response.status_code}.")
    if headers and response.headers.get("Content-Range", "").split("/")[0] != f"bytes {start}-{start + length - 1}":
        raise ForecastError("DATA_INVALID", "Погодный сервер вернул неверный диапазон байтов.")
    invalid_size = (len(response.content) != length if length is not None
                    else not 0 < len(response.content) <= MAX_INDEX)
    if invalid_size:
        raise ForecastError("DATA_INVALID", "Погодный сервер вернул неверный размер объекта.")
    return response.content, _last_modified(response, origin)


def _index_records(raw: bytes, step: int, init: datetime) -> dict[str, dict]:
    try:
        records = [json.loads(line) for line in raw.splitlines()]
        selected: dict[str, dict] = {}
        for row in records:
            if row.get("param") not in PARAMS or row.get("levtype") != "sfc" or str(row.get("step")) != str(step):
                continue
            if (row.get("type") != "fc" or row.get("stream") != "oper"
                    or row.get("time") != "0000" or row.get("date") != init.strftime("%Y%m%d")):
                raise ValueError("wrong forecast identity")
            param = row["param"]
            if param in selected or type(row.get("_offset")) is not int or type(row.get("_length")) is not int:
                raise ValueError("duplicate or invalid offset")
            if row["_offset"] < 0 or not 0 < row["_length"] <= MAX_FIELD:
                raise ValueError("invalid field length")
            selected[param] = row
        if set(selected) != set(PARAMS):
            raise ValueError("missing fields")
        return selected
    except (ValueError, TypeError, UnicodeError, KeyError, json.JSONDecodeError) as exc:
        raise ForecastError("DATA_INVALID", "Индекс ECMWF не содержит три точных погодных поля.") from exc


def _point(raw: bytes, param: str, step: int, site: dict, init: datetime) -> tuple[float, float, float]:
    try:
        import eccodes
        with tempfile.TemporaryFile() as stream:
            stream.write(raw)
            stream.seek(0)
            grib = eccodes.codes_grib_new_from_file(stream)
            if grib is None:
                raise ValueError("empty GRIB")
            try:
                if (eccodes.codes_get(grib, "shortName") != param
                        or int(eccodes.codes_get(grib, "step")) != step
                        or int(eccodes.codes_get(grib, "dataDate")) != int(init.strftime("%Y%m%d"))
                        or int(eccodes.codes_get(grib, "dataTime")) != 0
                        or eccodes.codes_get(grib, "centre") != "ecmf"
                        or eccodes.codes_get(grib, "dataType") != "fc"
                        or int(eccodes.codes_get(grib, "stepUnits")) != 1
                        or eccodes.codes_get(grib, "units") != ("K" if param == "2t" else "m s**-1")
                        or abs(float(eccodes.codes_get(grib, "iDirectionIncrementInDegrees")) - .25) > 1e-8
                        or abs(float(eccodes.codes_get(grib, "jDirectionIncrementInDegrees")) - .25) > 1e-8
                        or eccodes.codes_get(grib, "typeOfLevel") != "heightAboveGround"
                        or int(eccodes.codes_get(grib, "level")) != (2 if param == "2t" else 10)):
                    raise ValueError("GRIB identity mismatch")
                nearest = eccodes.codes_grib_find_nearest(grib, site["latitude"], site["longitude"], npoints=1)[0]
                lat, lon, value = float(nearest["lat"]), float(nearest["lon"]), float(nearest["value"])
            finally:
                eccodes.codes_release(grib)
        if not all(math.isfinite(v) for v in (lat, lon, value)):
            raise ValueError("non-finite GRIB value")
        if abs(lat - site["latitude"]) > .26 or min(abs(lon - site["longitude"]), abs(lon - site["longitude"] - 360)) > .26:
            raise ValueError("wrong nearest grid")
        if param == "2t" and not 150 < value < 350:
            raise ValueError("temperature units not Kelvin")
        return lat, lon, value
    except Exception as exc:
        raise ForecastError("DATA_INVALID", "GRIB ECMWF повреждён или не соответствует запрошенному выпуску.") from exc


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ForecastError("DATA_INVALID", "Кэш ECMWF содержит недопустимую ссылку.")
    if path.exists():
        if path.read_bytes() != data:
            raise ForecastError("DATA_INVALID", "Кэш ECMWF содержит конфликтующие данные.")
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".ecmwf-", delete=False) as stream:
        tmp = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _load_receipt(path: Path, origin: str, *, horizon_hours: int) -> dict:
    if path.is_symlink() or (path / "receipt.json").is_symlink():
        raise ForecastError("WEATHER_UNAVAILABLE", "Кэш ECMWF содержит недопустимую ссылку.")
    try:
        data = json.loads((path / "receipt.json").read_text(encoding="utf-8"))
        when, init, prefix, _ = _run(origin)
        if data.get("version") != 1 or data.get("origin") != origin or data.get("run_id") != iso(init):
            raise ValueError("wrong receipt identity")
        if set(data.get("nodes", {})) != {str(step) for step in STEPS}:
            raise ValueError("incomplete nodes")
        if "sites" in data and data["sites"] != [{key: site[key] for key in ("turbine_id", "latitude", "longitude")} for site in SITES]:
            raise ValueError("site coordinates changed")
        if set(data.get("objects", {})) != {f"{step}-{suffix}" for step in STEPS for suffix in ("index", *PARAMS)}:
            raise ValueError("incomplete objects")
        receipt_hash = data.get("receipt_sha256")
        decode_points = receipt_hash not in _DECODED_RECEIPTS
        for step in STEPS:
            stem = BASE + "/" + prefix + f"{step}h-oper-fc"
            index_meta = data["objects"][f"{step}-index"]
            index_path = path / f"{step}-index.bin"
            if index_path.is_symlink():
                raise ValueError("linked index")
            index_raw = index_path.read_bytes()
            if (index_meta["url"] != stem + ".index" or _sha(index_raw) != index_meta["sha256"]
                    or not init <= utc_time(index_meta["last_modified"]) <= when):
                raise ValueError("invalid index receipt")
            selected = _index_records(index_raw, step, init)
            for param in PARAMS:
                name = f"{step}-{param}"
                meta = data["objects"][name]
                file = path / f"{name}.bin"
                if file.is_symlink():
                    raise ValueError("linked raw field")
                raw = file.read_bytes()
                if (meta["url"] != stem + ".grib2" or _sha(raw) != meta["sha256"]
                        or len(raw) != selected[param]["_length"]
                        or meta["offset"] != selected[param]["_offset"]
                        or meta["length"] != selected[param]["_length"]
                        or not init <= utc_time(meta["last_modified"]) <= when):
                    raise ValueError("invalid field receipt")
                if decode_points:
                    for site in SITES:
                        lat, lon, value = _point(raw, param, step, site, init)
                        node = data["nodes"][str(step)][site["turbine_id"]]
                        if (node[param] != value or node["grid_latitude"] != lat or node["grid_longitude"] != lon):
                            raise ValueError("cached point differs from GRIB")
        if data.get("receipt_sha256") != fingerprint({k: v for k, v in data.items() if k != "receipt_sha256"})[7:]:
            raise ValueError("receipt checksum mismatch")
        for step in STEPS:
            node = data["nodes"][str(step)]
            for turbine_id in ("T1", "T2"):
                values = node[turbine_id]
                if not all(math.isfinite(values[key]) for key in ("2t", "10u", "10v", "grid_latitude", "grid_longitude")):
                    raise ValueError("invalid numeric node")
        _DECODED_RECEIPTS.add(receipt_hash)
        if len(_DECODED_RECEIPTS) > 64:
            _DECODED_RECEIPTS.pop()
        return data
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, ForecastError) as exc:
        raise ForecastError("WEATHER_UNAVAILABLE", "Проверенный погодный кэш ECMWF отсутствует или повреждён.") from exc


def fetch_operational_weather(site: dict, origin: str, horizon_hours: int, mode: str = "archive") -> dict:
    """Offline read of checked operational receipts; no network or fallback."""
    if mode != "archive" or site not in SITES or type(horizon_hours) is not int or horizon_hours not in (24, 48):
        raise ForecastError("INVALID_INPUT", "Неверный запрос к операционному архиву ECMWF.")
    when, init, prefix, name = _run(origin)
    receipt = _load_receipt(cache_dir() / name, origin, horizon_hours=horizon_hours)
    nodes = receipt["nodes"]
    rows = []
    for lead, stamp in enumerate(expected_hours(origin, horizon_hours), 1):
        step = 18 + lead
        lower = step // 3 * 3
        upper = lower if step % 3 == 0 else lower + 3
        a, b = nodes[str(lower)][site["turbine_id"]], nodes[str(upper)][site["turbine_id"]]
        weight = 0 if upper == lower else (step - lower) / 3
        t = a["2t"] * (1 - weight) + b["2t"] * weight - 273.15
        u = a["10u"] * (1 - weight) + b["10u"] * weight
        v = a["10v"] * (1 - weight) + b["10v"] * weight
        rows.append({"valid_at": stamp, "wind_speed_ms": math.hypot(u, v), "temperature_c": t})
    last = max(utc_time(meta["last_modified"]) for meta in receipt["objects"].values())
    grid = nodes["18"][site["turbine_id"]]
    manifest = {"turbine_id": site["turbine_id"], "run_id": iso(init),
                "provider": "ECMWF IFS operational / Google Cloud public replica",
                "source_url": BASE + "/" + prefix, "initialized_at": iso(init),
                "available_at": iso(last), "availability_basis": "operational_object_last_modified",
                "availability_verified": True, "provenance_status": "verified",
                "raw_sha256": receipt["receipt_sha256"], "receipt_sha256": receipt["receipt_sha256"],
                "interpolation": "linear_3h_to_hourly", "source_step_hours": 3,
                "grid_resolution_degrees": .25, "wind_height_m": 10, "temperature_height_m": 2,
                "weather_model": "ecmwf_ifs", "wind_height_status": "provider_feature_not_sensor_measurement",
                "grid_latitude": grid["grid_latitude"], "grid_longitude": grid["grid_longitude"],
                "provider_documentation": DOC, "object_count": len(receipt["objects"]),
                "source_object_count": len({meta["url"] for meta in receipt["objects"].values()}),
                "index_count": len(STEPS), "field_message_count": len(STEPS) * len(PARAMS),
                "source_kind": "operational_grib_archive",
                "evidence": {"receipt_path": f"operational_weather/{name}/receipt.json",
                             "receipt_sha256": receipt["receipt_sha256"],
                             "object_count": len(receipt["objects"]),
                             "source_object_count": len({meta["url"] for meta in receipt["objects"].values()}),
                             "first_object_last_modified": min(meta["last_modified"] for meta in receipt["objects"].values()),
                             "last_object_last_modified": iso(last)}}
    return {"manifest": manifest, "rows": rows}


def prepare_operational_weather(*, days: int = 28, start_day: int = 0, root: Path | None = None,
                                client: httpx.Client | None = None, cache_only: bool = False) -> dict:
    """Resumable acquisition of original index and selected GRIB messages."""
    if (type(days) is not int or type(start_day) is not int
            or not 1 <= days <= 28 or not 0 <= start_day < 28 or start_day + days > 28):
        raise ValueError("start_day and days must select 1..28 dates")
    root = Path(root) if root is not None else cache_dir()
    root.mkdir(parents=True, exist_ok=True)
    own_client = client is None
    if own_client:
        client = httpx.Client()
    assert client is not None
    completed, failures = [], []
    try:
        for day in range(start_day, start_day + days):
            origin = iso(utc_time(FIRST_ORIGIN) + timedelta(days=day))
            when, init, prefix, folder = _run(origin)
            path = root / folder
            if (path / "receipt.json").exists():
                try:
                    _load_receipt(path, origin, horizon_hours=48)
                    completed.append(origin)
                    continue
                except ForecastError:
                    raise ForecastError("DATA_INVALID", f"Повреждён готовый архивный выпуск {origin}; ручная проверка обязательна.")
            if cache_only:
                failures.append({"origin": origin, "message": "Погодный выпуск отсутствует в проверенном кэше ECMWF."})
                break
            path.mkdir(parents=True, exist_ok=True)
            objects, nodes = {}, {}
            try:
                for step in STEPS:
                    stem = BASE + "/" + prefix + f"{step}h-oper-fc"
                    index_path = path / f"{step}-index.bin"
                    if index_path.exists() and (path / f"{step}-index.last").exists():
                        index_raw = index_path.read_bytes()
                        index_last = (path / f"{step}-index.last").read_text().strip()
                    else:
                        index_raw, index_last = _fetch(client, stem + ".index", when)
                        _atomic_write(index_path, index_raw)
                        _atomic_write(path / f"{step}-index.last", (index_last + "\n").encode())
                    selected = _index_records(index_raw, step, init)
                    objects[f"{step}-index"] = {"url": stem + ".index", "sha256": _sha(index_raw), "last_modified": index_last}
                    values = {site["turbine_id"]: {} for site in SITES}
                    for param in PARAMS:
                        row = selected[param]
                        field_path = path / f"{step}-{param}.bin"
                        lm_path = path / f"{step}-{param}.last"
                        if field_path.exists() and lm_path.exists():
                            raw = field_path.read_bytes()
                            last = lm_path.read_text().strip()
                        else:
                            raw, last = _fetch(client, stem + ".grib2", when,
                                               start=row["_offset"], length=row["_length"])
                            _atomic_write(field_path, raw)
                            _atomic_write(lm_path, (last + "\n").encode())
                        if len(raw) != row["_length"]:
                            raise ForecastError("DATA_INVALID", "Размер сохранённого поля ECMWF не совпал с индексом.")
                        objects[f"{step}-{param}"] = {"url": stem + ".grib2", "sha256": _sha(raw),
                                                       "last_modified": last, "offset": row["_offset"], "length": row["_length"]}
                        for site in SITES:
                            lat, lon, val = _point(raw, param, step, site, init)
                            point = values[site["turbine_id"]]
                            if "grid_latitude" in point and (point["grid_latitude"], point["grid_longitude"]) != (lat, lon):
                                raise ForecastError("DATA_INVALID", "Поля ECMWF используют разные точки сетки.")
                            point.update({"grid_latitude": lat, "grid_longitude": lon, param: val})
                    nodes[str(step)] = values
                    print(f"{origin} step {step}/66", flush=True)
                receipt = {"version": 1, "origin": origin, "run_id": iso(init),
                           "sites": [{key: site[key] for key in ("turbine_id", "latitude", "longitude")} for site in SITES],
                           "objects": objects, "nodes": nodes}
                receipt["receipt_sha256"] = fingerprint(receipt)[7:]
                _atomic_write(path / "receipt.json", (json.dumps(receipt, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode())
                _load_receipt(path, origin, horizon_hours=48)
                completed.append(origin)
            except (ForecastError, OSError, ValueError) as exc:
                failures.append({"origin": origin, "message": str(exc)})
                print(f"{origin}: {exc}", flush=True)
                break
    finally:
        if own_client:
            client.close()
    return {"status": "ok" if not failures else "incomplete", "completed_days": len(completed),
            "expected_days": days, "completed_origins": completed, "failures": failures,
            "source": BASE, "availability_basis": "operational_object_last_modified"}
