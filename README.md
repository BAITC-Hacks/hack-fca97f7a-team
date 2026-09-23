# Wind power forecast — React + FastAPI

Implementation backlog for three developers: [tasks.md](tasks.md). The active
React demo has a Russian user interface and Russian explanation fallback.

The active application is a React frontend with a FastAPI backend:

**Select turbine → weather tool → validated CSV → model reads CSV → predictions → OpenAI explanation.**

Both turbine models are trained from their separate real datasets. Weather is
still a labeled fixture; map coordinates come from the user's Google Maps links.
OpenAI explanation and forecast
questions are real integrations, with an explicit computed fallback when the
key/provider is unavailable. Streamlit (`app.py`) is only the legacy prototype.

## Run the app

Requires Python **3.12+** (tested 3.14.4) and Node **22+**.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m scripts.make_fixtures
python -m scripts.train --mode fixture
npm --prefix frontend ci
npm --prefix frontend run build
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Open **http://localhost:8000**. FastAPI serves the built React app on the same
port; interactive API documentation is at **http://localhost:8000/docs**.

For frontend hot reload, keep FastAPI on port 8000 and run this in another terminal:

```sh
npm --prefix frontend run dev
```

Open http://localhost:5173; Vite proxies `/api` to FastAPI.

## OpenAI configuration

Copy `.env.example` to `.env` only if you do not already have a `.env`, then set:

```text
OPENAI_API_KEY=your-server-side-key
OPENAI_MODEL=gpt-5.4-mini
SUMMARY_BACKEND=llm
DATA_MODE=fixture
```

The current workspace already has the supplied key in ignored `.env` with
owner-only permissions. Environment variables take precedence over `.env`.
Never place keys in React, `VITE_` variables, Git or prompts. No NVIDIA adapter is
needed for this slice.

The backend uses the OpenAI Responses API with an 8-second timeout and no automatic
retries. Numeric forecasts appear first. Missing key, timeout or provider failure
returns a labeled local answer; it does not discard or change the forecast.

## Демонстрация за 2–3 минуты

Согласованный минималистичный дизайн описан в [frontend/DESIGN.md](frontend/DESIGN.md).

1. Откройте приложение. Слева — карта с координатами пользователя и параметры, справа — прогноз, под ним — анализ и чат. Выберите T1 на карте или в списке, дату 31.01.2026 и горизонт «48 часов». Время запуска — 23:00 Asia/Almaty. Погода остаётся демонстрационной.
2. Нажмите **«Сформировать прогноз»**. Покажите график нормализованной мощности и раздел «Почасовые данные». Числовой результат появляется до объяснения.
3. Нажмите **«Скачать прогноз CSV»** в панели результата. Под графиком доступны **PNG** (2200 × 840) и **SVG** с датой, турбиной, часовым поясом и легендой. В разделе **«Данные и метод расчёта»** нажмите **«Скачать входной CSV»** — это точный файл, прочитанный моделью.
4. Покажите пометку «Объяснение ИИ» или «Расчётное объяснение — ИИ недоступен». Спросите: **«В какие шесть часов средняя мощность максимальна?»**. Шестичасовое среднее вычисляет сервер.
5. Нажмите **«Следующий день и новый прогноз»**, затем покажите «Сравнение запусков» для совпадающих часов. Выберите T2 и повторите прогноз. При смене параметров предыдущий результат скрывается.
6. Для проверки ошибок выберите «Проверенный архив» и нажмите «Сформировать прогноз»: появится сообщение о недоступной погоде. Верните «Демонстрационная погода». При дате вне 31 января и 1 февраля приложение покажет понятную ошибку.

Сохранённая демонстрационная погода доступна только для 31 января и 1 февраля,
23:00 Asia/Almaty. Карта загружает тайлы из сети; турбину всегда можно выбрать
из списка. Режим архива заработает после подключения проверенной архивной
погоды. Повторный запуск сервера удаляет сохранённые ID прогнозов; сформируйте
прогноз заново.

## The module seams

**Read [CONTRACTS.md](CONTRACTS.md) for exact HTTP routes, JSON, CSV schema,
Python signatures and instructions for replacing each component.**

| Owner | Modules | Replace/improve here |
|---|---|---|
| A — integration/weather | `api.py`, `agent.py`, `weather.py`, `contracts.py` | transport, orchestration, verified weather/site adapter |
| B — data/model | `data.py`, `model_input.py`, `model.py`, `scripts/train.py` | source ingestion, canonical CSV schema, fitting/inference, replay |
| C — UI/explanation | `frontend/`, `explanation.py` | React views, central API client/types, OpenAI prose/questions |

The CSV seam is **real inference input**, not an export fabricated afterward:

```csv
turbine_id,valid_at,wind_speed_ms,temperature_c
T2,2026-01-31T19:00:00Z,6.2,-4.0
```

`model_input.write_model_input` validates and atomically writes it to
`artifacts/model_inputs/<sha256>.csv`. `model.predict_power_csv` reads those bytes,
checks checksum/header/turbine/hour coverage, and runs inference in row order.
Forecast responses include schema version, checksum, row count and filename.
The HTTP download rechecks integrity. A trace shows CSV creation and prediction.

Predictions are stored server-side under a forecast ID; summary/question endpoints
accept that ID rather than client-authored predictions. In-memory stores retain
64 forecasts, so a server restart/eviction requires generating the forecast again.
Use one worker for this local demo. No database, queues or distributed services.

## Data and assumptions

Source CSVs and brief in `data/` remain unchanged. T1 has 142,360 records and T2
149,499. Both end January 31, 2026; February truth is absent despite filenames.

Assume ten-minute interval starts in Asia/Almaty. Drop/report ambiguous local
times and incomplete hours. Each retained hour averages six complete samples.
Zero-power observations are retained. Generated data/audits are under ignored
`data/canonical/`; models and inference CSVs are under ignored `artifacts/`.
The source hashes, clock exclusions and feature assumptions are recorded in
[DATA_MODEL_HANDOFF.md](DATA_MODEL_HANDOFF.md).

| Turbine | Complete hourly observations | Frozen training hours |
|---|---:|---:|
| T1 | 23,666 | 23,665 |
| T2 | 24,784 | 24,783 |

Training uses only completed hours at or before `2026-01-31T18:00:00Z`; its last
interval starts at 17:00 UTC. Predictions start at origin+1 hour. Models stay frozen
for the next origin; February labels/observed weather cannot enter the predictor.

Power is normalized [0,1], displayed as percentages in React—not MW/MWh. Capacity,
normalization denominator and source timestamp convention still need confirmation.
No farm total or calibrated uncertainty is available. The measured-weather
holdout in [EVALUATION_REPORT.md](EVALUATION_REPORT.md) assesses the regressor;
it does not establish accuracy using weather available at a forecast origin.
Координаты и соответствие турбин подтверждены пользователем:

| Турбина | Широта | Долгота | Источник |
|---|---:|---:|---|
| T1 | 43.645150 | 78.535604 | [Google Maps](https://maps.app.goo.gl/iN6svMt69D5qRpFU9) |
| T2 | 43.643198 | 78.538828 | [Google Maps](https://maps.app.goo.gl/8UQMwsYavY6nLvFY8) |

API помечает их как `user_provided` и возвращает исходную ссылку в
`coordinate_source`. Это не меняет статус демонстрационных погодных данных.

## Validation

```sh
python -m pytest -q
npm --prefix frontend run build
python -m scripts.evaluate
```

The evaluation reports MAE/RMSE/R² for both turbines and 24/48-hour windows,
compared with origin-refreshed persistence. It uses future-hour *measured* wind
and temperature; see [EVALUATION_REPORT.md](EVALUATION_REPORT.md) before citing
the scores.

The Python suite and React TypeScript/Vite build cover
CSV consumption/integrity, chronology, source identities, input/output validation,
cache, HTTP/downloads, stored forecast context, summary fallback and legacy UI.
Tests clear OPENAI_API_KEY and mock SDK responses; they spend no API credits.
FastAPI TestClient needs local socket permissions in restricted environments.

One explicitly user-approved live test succeeded with `gpt-5.4-mini`: 24 generated
T2 weather rows → real CSV inference → LLM explanation, with no fallback. No raw
training CSV was sent. An earlier React browser smoke test used an empty key and
passed forecast rendering, 48-row model-input CSV download, a six-hour-window
question, next-day comparison, and the JavaScript error check (none).

The minimal Russian UI was also checked in Chromium with an empty OpenAI key:
T1/T2 × 24/48 hours, forecast/model-input CSV downloads, PNG (2200 × 840), SVG,
two-question chat history, real weather-unavailable errors and retry, input
invalidation, and a 390-pixel mobile viewport. Missing forecast IDs and delayed
explanations were simulated in the browser to check recovery and stale responses.
No JavaScript errors or paid OpenAI requests occurred.

## Remaining work

- Verify as-issued archived weather access for the user-supplied turbine coordinates.
- Implement February replay over all 28 daily origins and both turbines.
- Validate feature mismatch between measured training weather and forecast inputs.
- Confirm timezone/interval/normalization metadata; score only if truth is supplied.

The current app is a working demo with explicit synthetic weather and user-supplied coordinates, not a
claim that the full organizer task is complete. See [AGENTS.md](AGENTS.md) for
working rules and [PLAN.md](PLAN.md) for current scope.

## Интеграция MLmodel

Обучение `python -m scripts.train --mode fixture` теперь также создаёт январскую
диагностику отдельно для T1/T2: `artifacts/training/T1_metrics.json` и
`T2_metrics.json`, плюс CSV с фактом и прогнозом. `--skip-validation` пропускает
только диагностику. Она использует измеренную погоду и не оценивает качество
реального прогноза погоды на 24/48 часов; baseline заморожен на весь январь.

Модели сохраняются в `artifacts/models/<турбина>/<хэш>/`, активные версии — в
`latest.json`. Старые локальные `T1.pkl`/`T2.pkl` читаются при отсутствии реестра;
переобучение переводит проект на новый формат. Внешний контракт
`load_model("T1")` и обязательный CSV-вход сохранены. После обучения:

```sh
python -m scripts.smoke_model --models-dir artifacts/models
```

Команда проверяет восемь синтетических сценариев через реальное чтение CSV.

Проверка объединённой ветки: 58 тестов, сборка React и 8 CSV smoke-сценариев прошли.
Январский MAE: T1 — 0,02373; T2 — 0,02592 (нормализованные доли, измеренная погода).
