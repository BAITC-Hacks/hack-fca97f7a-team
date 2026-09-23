"""Thin HTTP adapter around the UI-independent forecast core."""
from __future__ import annotations

import copy
import hashlib
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

from agent import run_forecast
from contracts import artifact_dir, forecast_csv
from explanation import answer_question, summarize_forecast
from weather import load_sites

ROOT = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass

app = FastAPI(title="Wind Power Demo API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"]
)

_FORECASTS: OrderedDict[str, dict] = OrderedDict()
_FORECASTS_LOCK = threading.RLock()
_MAX_FORECASTS = 64


class ForecastBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    turbine_id: StrictStr
    origin: StrictStr
    horizon_hours: Literal[24, 48]
    mode: Literal["fixture", "archive"]


class ExplanationBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    backend: Literal["template", "llm"] = "llm"


class QuestionBody(ExplanationBody):
    question: StrictStr = Field(min_length=1, max_length=2000)

    @field_validator("question")
    @classmethod
    def question_must_contain_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must contain non-whitespace text")
        return value


def _error(status: int, code: str, message: str, trace: list | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={
        "status": "error", "code": code, "message": message, "trace": trace or []
    })


def _status_for(code: str) -> int:
    if code == "INVALID_INPUT":
        return 400
    if code in ("DATA_INVALID", "MODEL_INVALID"):
        return 422
    if code in ("MODEL_UNAVAILABLE", "WEATHER_UNAVAILABLE"):
        return 503
    return 500


@app.exception_handler(RequestValidationError)
def _validation_error(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return _error(422, "INVALID_INPUT", "Request body or parameters are invalid.")


@app.get("/api/health")
def health() -> dict:
    configured = bool(os.getenv("OPENAI_API_KEY", "").strip())
    return {"status": "ok", "llm_configured": configured,
            "summary_backend": "llm" if configured else "template"}


@app.get("/api/sites")
def sites(mode: Literal["fixture", "archive"] = "fixture") -> dict:
    return {"sites": load_sites(mode)}


@app.post("/api/forecasts")
def create_forecast(body: ForecastBody):
    result = run_forecast(body.model_dump())
    if result.get("status") != "ok":
        code = str(result.get("code", "INTERNAL_ERROR"))
        status = _status_for(code)
        message = result.get("message")
        if status == 500 or (isinstance(message, str) and message.startswith("Forecast input or tool failed:")):
            code = "INTERNAL_ERROR"
            status = 500
            message = "Forecast processing failed."
        return _error(status, code, str(message or "Forecast could not be completed."), result.get("trace"))

    fingerprint = result.get("fingerprint", "")
    forecast_id = fingerprint.removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", forecast_id):
        return _error(500, "INTERNAL_ERROR", "Forecast returned an invalid identifier.", result.get("trace"))
    stored = copy.deepcopy(result)
    with _FORECASTS_LOCK:
        _FORECASTS[forecast_id] = stored
        _FORECASTS.move_to_end(forecast_id)
        while len(_FORECASTS) > _MAX_FORECASTS:
            _FORECASTS.popitem(last=False)
    return {**copy.deepcopy(result), "forecast_id": forecast_id}


def _get_forecast(forecast_id: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{64}", forecast_id):
        raise HTTPException(status_code=404, detail={
            "status": "error", "code": "NOT_FOUND", "message": "Forecast was not found.", "trace": []
        })
    with _FORECASTS_LOCK:
        result = _FORECASTS.get(forecast_id)
        if result is not None:
            _FORECASTS.move_to_end(forecast_id)
            return copy.deepcopy(result)
    raise HTTPException(status_code=404, detail={
        "status": "error", "code": "NOT_FOUND", "message": "Forecast was not found.", "trace": []
    })


@app.exception_handler(HTTPException)
def _http_error(_request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and exc.detail.get("status") == "error":
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return _error(exc.status_code, "HTTP_ERROR", str(exc.detail))


@app.get("/api/forecasts/{forecast_id}/download")
def download_forecast(
    forecast_id: str,
    kind: Literal["forecast", "model-input"] = Query(default="forecast"),
) -> Response:
    result = _get_forecast(forecast_id)
    if kind == "forecast":
        content = forecast_csv(result)
        return Response(content, media_type="text/csv", headers={
            "Content-Disposition": f'attachment; filename="forecast-{forecast_id}.csv"'
        })

    metadata = result.get("model_input")
    if not isinstance(metadata, dict):
        return _error(404, "NOT_FOUND", "Model input CSV is unavailable for this forecast.")
    filename = metadata.get("filename")
    if (metadata.get("schema_version") != "weather-features-v1"
            or metadata.get("row_count") not in (24, 48)
            or metadata.get("columns") != ["turbine_id", "valid_at", "wind_speed_ms", "temperature_c"]
            or not isinstance(filename, str)
            or not re.fullmatch(r"[0-9a-f]{64}\.csv", filename)):
        return _error(404, "NOT_FOUND", "Model input CSV is unavailable for this forecast.")
    base = (artifact_dir() / "model_inputs").resolve()
    path = (base / filename).resolve()
    if path.parent != base or not path.is_file():
        return _error(404, "NOT_FOUND", "Model input CSV is unavailable for this forecast.")
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return _error(404, "NOT_FOUND", "Model input CSV is unavailable for this forecast.")
    if digest != metadata.get("sha256") or digest != filename[:-4]:
        return _error(422, "DATA_INVALID", "Saved model input failed its integrity check.")
    return FileResponse(path, media_type="text/csv", filename=filename)


@app.post("/api/forecasts/{forecast_id}/explanation")
def explain_forecast(forecast_id: str, body: ExplanationBody):
    result = _get_forecast(forecast_id)
    try:
        return summarize_forecast(result, backend=body.backend)
    except Exception:
        return _error(500, "EXPLANATION_FAILED", "Forecast summary could not be generated.")


@app.post("/api/forecasts/{forecast_id}/questions")
def ask_forecast(forecast_id: str, body: QuestionBody):
    result = _get_forecast(forecast_id)
    try:
        return answer_question(result, body.question, backend=body.backend)
    except Exception:
        return _error(500, "EXPLANATION_FAILED", "Forecast question could not be answered.")


@app.api_route("/api/{api_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def unknown_api_route(api_path: str) -> JSONResponse:
    return _error(404, "NOT_FOUND", "API endpoint was not found.")


_frontend_dist = ROOT / "frontend" / "dist"
if _frontend_dist.is_dir():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")
