"""Thin HTTP adapter around the UI-independent forecast core."""
from __future__ import annotations

import copy
import hashlib
import json
import secrets
import os
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

from backend.services.agent import run_forecast
from backend.services.february import february_metadata, run_february_forecast
from backend.core.contracts import ROOT, ForecastError, artifact_dir, forecast_csv
from backend.adapters.explanation import answer_question, summarize_forecast
from backend.adapters.forecast_store import load as load_forecast, save as save_forecast
from backend.adapters.weather import clear_live_weather_cache, load_sites

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
_MAX_CONVERSATIONS = 128
_MAX_HISTORY_MESSAGES = 10


@dataclass
class Conversation:
    forecast_id: str
    messages: list[dict] = field(default_factory=list)
    selection: dict | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


# Dialogs stay in RAM; forecasts can be restored from the bounded disk store.
_CONVERSATIONS: OrderedDict[str, Conversation] = OrderedDict()



class ForecastBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    turbine_id: StrictStr
    origin: StrictStr
    horizon_hours: Literal[24, 48]
    mode: Literal["fixture", "archive", "live"]


class FebruaryForecastBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    turbine_id: Literal["T1", "T2"]
    forecast_date: StrictStr
    horizon_hours: Literal[24, 48]
    weather_source: Literal["verified", "provider-documented"] = "verified"


class ExplanationBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    backend: Literal["template", "llm"] = "llm"


class QuestionBody(ExplanationBody):
    question: StrictStr = Field(min_length=1, max_length=2000)
    conversation_id: StrictStr | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")

    @field_validator("question")
    @classmethod
    def question_must_contain_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must contain non-whitespace text")
        return value


class WeatherRefreshBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    turbine_id: Literal["T1", "T2"]


def _error(status: int, code: str, message: str, trace: list | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={
        "status": "error", "code": code, "message": message, "trace": trace or []
    })


def _status_for(code: str) -> int:
    if code == "INVALID_INPUT":
        return 400
    if code in ("DATA_INVALID", "MODEL_INVALID"):
        return 422
    if code in ("MODEL_UNAVAILABLE", "WEATHER_UNAVAILABLE", "ARCHIVE_UNAVAILABLE", "REPLAY_UNAVAILABLE"):
        return 503
    return 500


@app.exception_handler(RequestValidationError)
def _validation_error(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return _error(422, "INVALID_INPUT", "Проверьте параметры запроса: турбину, дату, горизонт и режим.")


@app.get("/api/health")
def health() -> dict:
    configured = bool(os.getenv("OPENAI_API_KEY", "").strip())
    return {"status": "ok", "llm_configured": configured,
            "summary_backend": "llm" if configured else "template"}


@app.get("/api/sites")
def sites(mode: Literal["fixture", "archive", "live"] = "fixture") -> dict:
    return {"sites": load_sites(mode)}


@app.post("/api/weather/refresh")
def refresh_weather(body: WeatherRefreshBody) -> dict:
    clear_live_weather_cache(body.turbine_id)
    return {"status": "ok"}


def _public_result(result: dict) -> dict:
    public = copy.deepcopy(result)

    def strip_baseline(value):
        if isinstance(value, dict):
            value.pop("baseline_norm", None)
            for child in value.values():
                strip_baseline(child)
        elif isinstance(value, list):
            for child in value:
                strip_baseline(child)

    strip_baseline(public)
    analysis = public.get("analysis")
    if isinstance(analysis, dict) and isinstance(analysis.get("warnings"), list):
        analysis["warnings"] = [warning for warning in analysis["warnings"]
                                if not (isinstance(warning, str) and
                                        ("baseline" in warning.lower() or "базов" in warning.lower()))]
    return public


@app.post("/api/forecasts")
def create_forecast(body: ForecastBody):
    return _store_forecast_result(run_forecast(body.model_dump()))


def _store_forecast_result(result: dict):
    if result.get("status") != "ok":
        code = str(result.get("code", "INTERNAL_ERROR"))
        status = _status_for(code)
        message = result.get("message")
        if status == 500 or (isinstance(message, str) and message.startswith("Forecast input or tool failed:")):
            code = "INTERNAL_ERROR"
            status = 500
            message = "Не удалось выполнить прогноз; проверьте данные и повторите попытку."
        return _error(status, code, str(message or "Не удалось выполнить прогноз; повторите попытку."), result.get("trace"))

    fingerprint = result.get("fingerprint", "")
    forecast_id = fingerprint.removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", forecast_id):
        return _error(500, "INTERNAL_ERROR", "Неверный идентификатор прогноза; создайте прогноз заново.", result.get("trace"))
    stored = _public_result(result)
    try:
        save_forecast(forecast_id, stored)
    except (OSError, ValueError, TypeError, OverflowError):
        return _error(500, "INTERNAL_ERROR", "Не удалось сохранить прогноз; повторите попытку.")
    with _FORECASTS_LOCK:
        _FORECASTS[forecast_id] = stored
        _FORECASTS.move_to_end(forecast_id)
        while len(_FORECASTS) > _MAX_FORECASTS:
            _FORECASTS.popitem(last=False)
    return {**copy.deepcopy(stored), "forecast_id": forecast_id}


@app.get("/api/replay/february")
def get_february_replay() -> dict:
    """Describe the daily decision points and both archive evidence levels."""
    return february_metadata()


@app.post("/api/replay/forecasts")
def create_february_forecast(body: FebruaryForecastBody):
    """Replay a selected February date, then reuse the normal forecast store/chat."""
    try:
        result = run_february_forecast(**body.model_dump())
    except ForecastError as exc:
        return _error(_status_for(exc.code), exc.code, str(exc))
    if result.get("status") != "ok" and result.get("code") == "WEATHER_UNAVAILABLE":
        result = {**result, "code": "ARCHIVE_UNAVAILABLE" if body.weather_source == "verified"
                  else "REPLAY_UNAVAILABLE"}
    return _store_forecast_result(result)


@app.get("/api/replay/february/download")
def download_february_replay(kind: Literal["forecast", "daily", "report"] = Query(default="daily")):
    """Serve fixed, reviewable February outputs; the URL never selects a path."""
    names = {"forecast": "forecast.csv",
             "daily": "daily_forecast.csv", "report": "report.json"}
    path = ROOT / "deliverables" / "february_2026_operational" / names[kind]
    if not path.is_file() or path.is_symlink():
        return _error(404, "NOT_FOUND", "Февральский отчёт недоступен в этой установке.")
    return FileResponse(path, media_type="application/json" if kind == "report" else "text/csv",
                        filename=f"february-2026-{names[kind]}")


def _get_forecast(forecast_id: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{64}", forecast_id):
        raise HTTPException(status_code=404, detail={
            "status": "error", "code": "NOT_FOUND", "message": "Прогноз не найден; создайте его заново.", "trace": []
        })
    with _FORECASTS_LOCK:
        result = _FORECASTS.get(forecast_id)
        if result is not None:
            _FORECASTS.move_to_end(forecast_id)
            return _public_result(result)
    result = load_forecast(forecast_id)
    if result is not None:
        result = _public_result(result)
        with _FORECASTS_LOCK:
            _FORECASTS[forecast_id] = result
            _FORECASTS.move_to_end(forecast_id)
            while len(_FORECASTS) > _MAX_FORECASTS:
                _FORECASTS.popitem(last=False)
        return copy.deepcopy(result)
    raise HTTPException(status_code=404, detail={
        "status": "error", "code": "NOT_FOUND", "message": "Прогноз не найден; создайте его заново.", "trace": []
    })


@app.exception_handler(HTTPException)
def _http_error(_request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and exc.detail.get("status") == "error":
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return _error(exc.status_code, "HTTP_ERROR", str(exc.detail))


@app.get("/api/forecasts/{forecast_id}")
def get_forecast(forecast_id: str) -> dict:
    """Reopen a checked, server-owned forecast without running weather or inference."""
    return {**_get_forecast(forecast_id), "forecast_id": forecast_id}


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
        return _error(404, "NOT_FOUND", "Входной CSV недоступен; создайте прогноз заново.")
    filename = metadata.get("filename")
    if (metadata.get("schema_version") != "weather-features-v1"
            or metadata.get("row_count") not in (24, 48)
            or metadata.get("columns") != ["turbine_id", "valid_at", "wind_speed_ms", "temperature_c"]
            or not isinstance(filename, str)
            or not re.fullmatch(r"[0-9a-f]{64}\.csv", filename)):
        return _error(404, "NOT_FOUND", "Входной CSV недоступен; создайте прогноз заново.")
    base = (artifact_dir() / "model_inputs").resolve()
    path = (base / filename).resolve()
    if path.parent != base or not path.is_file():
        return _error(404, "NOT_FOUND", "Входной CSV недоступен; создайте прогноз заново.")
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return _error(404, "NOT_FOUND", "Входной CSV недоступен; создайте прогноз заново.")
    if digest != metadata.get("sha256") or digest != filename[:-4]:
        return _error(422, "DATA_INVALID", "Входной CSV повреждён; создайте прогноз заново.")
    return FileResponse(path, media_type="text/csv", filename=filename)


@app.post("/api/forecasts/{forecast_id}/explanation")
def explain_forecast(forecast_id: str, body: ExplanationBody):
    result = _get_forecast(forecast_id)
    try:
        return summarize_forecast(result, backend=body.backend)
    except Exception:
        return _error(500, "EXPLANATION_FAILED", "Не удалось получить объяснение; повторите запрос.")


@app.post("/api/forecasts/{forecast_id}/questions")
def ask_forecast(forecast_id: str, body: QuestionBody):
    result = _get_forecast(forecast_id)
    with _FORECASTS_LOCK:
        token = body.conversation_id
        if token is None:
            token = secrets.token_hex(16)
            conversation = Conversation(forecast_id=forecast_id)
            _CONVERSATIONS[token] = conversation
            while len(_CONVERSATIONS) > _MAX_CONVERSATIONS:
                _CONVERSATIONS.popitem(last=False)
        else:
            conversation = _CONVERSATIONS.get(token)
            if conversation is None or conversation.forecast_id != forecast_id:
                return _error(404, "CONVERSATION_NOT_FOUND", "Диалог не найден для этого прогноза; начните новый разговор.")
            _CONVERSATIONS.move_to_end(token)
        if not conversation.lock.acquire(blocking=False):
            return _error(409, "CONVERSATION_BUSY", "Дождитесь ответа на предыдущий вопрос.")
    try:
        answer = answer_question(result, body.question, backend=body.backend,
                                 history=copy.deepcopy(conversation.messages),
                                 selection=copy.deepcopy(conversation.selection))
        with _FORECASTS_LOCK:
            if _CONVERSATIONS.get(token) is not conversation:
                return _error(404, "CONVERSATION_NOT_FOUND", "Диалог не найден для этого прогноза; начните новый разговор.")
            conversation.messages.extend([
                {"role": "user", "content": body.question},
                {"role": "assistant", "content": _answer_memory(answer)},
            ])
            conversation.messages = conversation.messages[-_MAX_HISTORY_MESSAGES:]
            if "selection" in answer:
                conversation.selection = copy.deepcopy(answer["selection"])
        return {**answer, "conversation_id": token}
    except Exception:
        return _error(500, "EXPLANATION_FAILED", "Не удалось ответить на вопрос; повторите запрос.")
    finally:
        conversation.lock.release()


def _answer_memory(answer: dict) -> str:
    """Keep the table's references even when LLM prose does not repeat its cells."""
    facts = []
    for tool in answer.get("tool_results", [])[-4:]:
        data = tool.get("data", {})
        compact = {key: value for key, value in data.items() if key not in ("hours", "changes")}
        if tool.get("tool") == "best_hours" and "hours" in data:
            compact["ranked_hours"] = [[hour["valid_at"], hour["power_norm"]] for hour in data["hours"]]
        if "changes" in data:
            compact["changes"] = [[change["from"], change["to"], change["delta_power_norm"]]
                                  for change in data["changes"]]
        facts.append({"tool": tool["tool"], "data": compact})
    if not facts:
        return answer["text"][:6000]
    # The final tool contains the active comparison/selection. Retain complete
    # JSON rather than cutting a timestamp or number at the message limit.
    encoded = json.dumps(facts, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(encoded) > 4500:
        encoded = json.dumps(facts[-1:], ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    suffix = "\nРассчитанные Python факты: " + encoded
    return answer["text"][:max(0, 6000 - len(suffix))] + suffix


@app.api_route("/api/{api_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def unknown_api_route(api_path: str) -> JSONResponse:
    return _error(404, "NOT_FOUND", "Адрес API не найден; проверьте ссылку.")


_frontend_dist = ROOT / "frontend" / "dist"
if _frontend_dist.is_dir():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")
