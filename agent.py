"""Forecast orchestration with weather eligibility and content-based result reuse."""
from __future__ import annotations

import copy
import math
from collections import OrderedDict
from threading import RLock

from contracts import (FEATURES, FIRST_ORIGIN, ForecastError, artifact_dir, expected_hours, fingerprint,
                       utc_time, validate_request)
from model import load_model, predict_power_csv
from model_input import write_model_input
from weather import fetch_weather, load_sites

_CACHE: OrderedDict[str, dict] = OrderedDict()
_MAX_CACHE = 64
_CACHE_LOCK = RLock()


def _validated_weather(bundle: dict, request: dict, site: dict) -> tuple[dict, list[dict]]:
    if not isinstance(bundle, dict) or not isinstance(bundle.get("manifest"), dict) or not isinstance(bundle.get("rows"), list):
        raise ForecastError("DATA_INVALID", "Weather tool returned an invalid bundle.")
    manifest, rows = bundle["manifest"], bundle["rows"]
    required = ("turbine_id", "run_id", "provider", "source_url", "initialized_at",
                "available_at", "availability_basis", "provenance_status", "raw_sha256", "interpolation")
    if any(not manifest.get(key) for key in required):
        raise ForecastError("DATA_INVALID", "Weather provenance is incomplete.")
    if manifest["turbine_id"] != site["turbine_id"]:
        raise ForecastError("DATA_INVALID", "Weather belongs to a different turbine.")
    if request["mode"] == "archive" and manifest["provenance_status"] != "verified":
        raise ForecastError("WEATHER_UNAVAILABLE", "Archive mode requires verified forecast provenance.")
    if request["mode"] == "fixture" and manifest["provenance_status"] != "fixture":
        raise ForecastError("DATA_INVALID", "Fixture mode requires labeled synthetic weather.")
    initialized = utc_time(manifest["initialized_at"])
    available = utc_time(manifest["available_at"])
    if initialized > available:
        raise ForecastError("DATA_INVALID", "Weather initialization follows its availability time.")
    if available > utc_time(request["origin"]):
        raise ForecastError("WEATHER_UNAVAILABLE", "Weather run was unavailable at the requested origin.")
    expected = expected_hours(request["origin"], request["horizon_hours"])
    if len(rows) != len(expected):
        raise ForecastError("DATA_INVALID", "Weather coverage is incomplete or has duplicate hours.")
    observed = []
    normalized = []
    for row in rows:
        if not isinstance(row, dict) or any(key not in row for key in ("valid_at", *FEATURES)):
            raise ForecastError("DATA_INVALID", "Weather row has missing features or timestamp.")
        stamp = row["valid_at"]
        utc_time(stamp)
        observed.append(stamp)
        clean = {"valid_at": stamp}
        for feature in FEATURES:
            value = row[feature]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ForecastError("DATA_INVALID", "Weather features must be finite numeric values.")
            clean[feature] = float(value)
        if clean["wind_speed_ms"] < 0:
            raise ForecastError("DATA_INVALID", "Wind speed cannot be negative.")
        normalized.append(clean)
    if observed != expected:
        raise ForecastError("DATA_INVALID", "Weather must cover each forecast hour once in order.")
    return manifest, normalized


def run_forecast(request: dict, *, weather_tool=fetch_weather, model_loader=load_model) -> dict:
    trace: list[dict] = []
    try:
        request = validate_request(request)
        trace.append({"step": "validate_request", "status": "ok", "detail": "registered request shape and UTC origin"})
        sites = {site["turbine_id"]: site for site in load_sites(request["mode"])}
        site = sites.get(request["turbine_id"])
        if site is None:
            if request["mode"] == "archive":
                raise ForecastError("WEATHER_UNAVAILABLE", "Verified site coordinates are unavailable for archive mode.")
            raise ForecastError("INVALID_INPUT", "Turbine is not registered for this mode.")
        trace.append({"step": "resolve_site", "status": "ok", "detail": site["coordinate_status"] + " coordinates"})
        for attempt in (1, 2):
            try:
                bundle = weather_tool(site, request["origin"], request["horizon_hours"], request["mode"])
                break
            except (OSError, TimeoutError, ConnectionError) as exc:
                trace.append({"step": "fetch_weather", "status": "retry" if attempt == 1 else "error",
                              "detail": f"transport attempt {attempt}: {type(exc).__name__}"})
                if attempt == 2:
                    raise ForecastError("WEATHER_UNAVAILABLE", "Weather transport failed after two attempts.") from exc
        trace.append({"step": "fetch_weather", "status": "ok", "detail": "weather received"})
        manifest, rows = _validated_weather(bundle, request, site)
        trace[-1]["detail"] = manifest["run_id"] + " selected"
        trace.append({"step": "validate_weather", "status": "ok", "detail": "availability, provenance and complete hourly coverage"})
        trace.append({"step": "prepare_features", "status": "ok", "detail": f"{len(rows)} finite wind and temperature pairs"})
        model_input = write_model_input(rows, request["turbine_id"], request["origin"], request["horizon_hours"])
        trace.append({"step": "write_model_input_csv", "status": "ok",
                      "detail": f"{model_input['row_count']} rows · {model_input['schema_version']} · {model_input['sha256']}"})
        fitted = model_loader(request["turbine_id"])
        metadata = fitted.metadata
        if metadata.get("turbine_id") != request["turbine_id"] or not metadata.get("model_id"):
            raise ForecastError("MODEL_UNAVAILABLE", "Model identity does not match the selected turbine.")
        if utc_time(metadata["train_origin"]) > min(utc_time(request["origin"]), utc_time(FIRST_ORIGIN)):
            raise ForecastError("MODEL_UNAVAILABLE", "Model was trained after the requested origin.")
        last_start = utc_time(metadata["train_last_interval_start"])
        from datetime import timedelta
        if last_start + timedelta(hours=1) > min(utc_time(request["origin"]), utc_time(FIRST_ORIGIN)):
            raise ForecastError("MODEL_UNAVAILABLE", "Training hour extends beyond the requested origin.")
        baseline = float(metadata["baseline_norm"])
        if not math.isfinite(baseline) or not 0 <= baseline <= 1:
            raise ForecastError("MODEL_UNAVAILABLE", "Model baseline is outside normalized bounds.")
        trace.append({"step": "load_model", "status": "ok", "detail": metadata["model_id"]})
        provenance = {key: manifest[key] for key in ("run_id", "provider", "source_url", "initialized_at",
                     "available_at", "availability_basis", "provenance_status", "raw_sha256", "interpolation")}
        identity = fingerprint({"request": request, "site": site, "model_id": metadata["model_id"],
                                "weather": {"manifest": provenance, "rows": rows}, "model_input": model_input})
        with _CACHE_LOCK:
            cached = _CACHE.get(identity)
            if cached is not None:
                _CACHE.move_to_end(identity)
                result = copy.deepcopy(cached)
        if cached is not None:
            result["cache_hit"] = True
            result["trace"] = trace + [{"step": "predict_power", "status": "cached", "detail": "same validated content"}]
            return result
        raw_predictions = predict_power_csv(
            fitted, artifact_dir() / "model_inputs" / model_input["filename"],
            turbine_id=request["turbine_id"], origin=request["origin"],
            horizon_hours=request["horizon_hours"], expected_sha256=model_input["sha256"],
        )
        if len(raw_predictions) != len(rows) or any(not math.isfinite(float(value)) for value in raw_predictions):
            raise ForecastError("DATA_INVALID", "Model returned invalid predictions.")
        clipped = [min(1.0, max(0.0, float(value))) for value in raw_predictions]
        clipped_count = sum(float(a) != b for a, b in zip(raw_predictions, clipped))
        hours = [{**row, "lead_hour": i, "power_norm": clipped[i-1], "baseline_norm": baseline}
                 for i, row in enumerate(rows, start=1)]
        peak = max(hours, key=lambda hour: hour["power_norm"])
        minimum = min(hours, key=lambda hour: hour["power_norm"])
        warnings = ["Real turbine training data; synthetic weather"] if request["mode"] == "fixture" else []
        warnings.append("Timezone and interval semantics assumed pending source confirmation")
        if clipped_count:
            warnings.append(f"{clipped_count} model predictions clipped to normalized bounds")
        analysis = {"peak_power_norm": peak["power_norm"], "peak_at": peak["valid_at"],
                    "min_power_norm": minimum["power_norm"], "min_at": minimum["valid_at"],
                    "clipped_count": clipped_count, "warnings": warnings}
        trace.append({"step": "predict_power", "status": "ok", "detail": f"{len(hours)} normalized hourly predictions"})
        trace.append({"step": "analyze_result", "status": "ok", "detail": "peak, minimum and clipping computed"})
        result = {"status": "ok", **request, "timezone": site["timezone"],
                  "run_id": manifest["run_id"], "model_id": metadata["model_id"],
                  "fingerprint": identity, "cache_hit": False,
                  "train_last_interval_start": metadata["train_last_interval_start"],
                  "model_input": model_input,
                  "weather_provenance": provenance, "hours": hours, "analysis": analysis,
                  "trace": trace}
        with _CACHE_LOCK:
            _CACHE[identity] = copy.deepcopy(result)
            if len(_CACHE) > _MAX_CACHE:
                _CACHE.popitem(last=False)
        return result
    except ForecastError as exc:
        trace.append({"step": "error", "status": "error", "detail": exc.code})
        return {"status": "error", "code": exc.code, "message": str(exc), "trace": trace}
    except Exception as exc:
        trace.append({"step": "error", "status": "error", "detail": type(exc).__name__})
        return {"status": "error", "code": "DATA_INVALID", "message": "Forecast input or tool failed: " + str(exc), "trace": trace}
