# Wind power forecast — React + FastAPI

Implementation backlog for three developers: [tasks.md](tasks.md). The demo must
be fully in Russian; localization is tracked there as required remaining work.

The active application is a React frontend with a FastAPI backend:

**Select turbine → weather tool → validated CSV → model reads CSV → predictions → OpenAI explanation.**

Both turbine models are trained from their separate real datasets. Fixture-mode
weather and map coordinates are synthetic; live mode fetches current Open-Meteo
weather at organizer-supplied coordinates; archive-mode coordinates are sourced
from the organizer but historical weather eligibility remains unverified. OpenAI explanation and forecast
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

## Demo

1. Для воспроизводимого показа выберите «Демонстрационная погода (заглушка)»,
   турбину T1 или T2, 31 января 2026 года и горизонт 48 часов.
2. Нажмите **«Сформировать прогноз»**. Посмотрите график и почасовую таблицу.
3. Нажмите **«Скачать входной CSV модели»**: это точный файл, прочитанный моделью.
4. Прочитайте объяснение: подпись различает ответ OpenAI и расчётный вариант.
5. Спросите: «В какие шесть часов средняя мощность максимальна?» Окно
   вычисляется локально перед формированием ответа.
6. Нажмите **«Перейти на день вперёд и пересчитать»**, чтобы сравнить общие часы.
7. Для текущей погоды переключите «Источник погоды» на **«Реальный прогноз
   Open-Meteo (сейчас)»**, выберите T1/T2 и 24 или 48 часов, затем нажмите
   **«Сформировать прогноз»**. Дата здесь не выбирается: сервер задаёт ближайший
   будущий целый час UTC. Этот шаг требует доступности погодного API.

In **live** mode select the turbine and 24/48 hours; do not enter a date. The
server selects the next UTC hour after receipt and returns it as `origin`. A live
request needs network access and never falls back silently to fixtures. Open-Meteo
Forecast API (best match, 10 m wind) is **current** weather, not proof of any
historical as-issued run. Weather data: © Open-Meteo, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/);
the free API is for noncommercial use under Open-Meteo's terms. Attribution must
remain visible in the UI. Wind height differs from the unverified training sensor
height and power is normalized, not a capacity forecast.

Fixture weather exists only for January 31 and February 1 at 23:00 Asia/Almaty.
Other origins return an explicit error. Archive mode lists organizer-supplied
coordinates but remains unavailable until independently reviewed, as-issued
per-run weather evidence is configured. Input changes clear stale results.

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

| Turbine | Complete hourly observations | Frozen training hours |
|---|---:|---:|
| T1 | 23,666 | 23,665 |
| T2 | 24,784 | 24,783 |

Training uses only completed hours at or before `2026-01-31T18:00:00Z`; its last
interval starts at 17:00 UTC. Predictions start at origin+1 hour. Models stay frozen
for the next origin; February labels/observed weather cannot enter the predictor.

Power is normalized [0,1], displayed as percentages in React—not MW/MWh. Capacity,
normalization denominator and source timestamp convention still need confirmation.
No farm total, calibrated uncertainty or accuracy claim without held-out truth.
Fixture map coordinates `(0,0)` / `(0,0.03)` are intentionally fictional.
Archive coordinates T1 (43.645150, 78.535604), T2 (43.643198, 78.538828)
come from organizer links, not independent engineering identification. The
[Open-Meteo verification note](docs/open-meteo-verification.md) records actual
public endpoint probes, but those retrospective queries **do not prove**
as-issued availability at the historical origin. `OPEN_METEO_ARCHIVE_MANIFEST`
(optional, unset by default) must point to an operator-reviewed external capture
evidence manifest; see [CONTRACTS.md](CONTRACTS.md#weather-seam--a-owns-weatherpy)
for exact schema and fail-closed rules. No key is required by
the public endpoint. Responses must match the trusted capture's versioned canonical *full-forecast*
SHA-256 (not volatile raw JSON bytes). Exact retrieved bytes retain a separate
`raw_sha256` artifact checksum. Wind at 10 m from `ecmwf_ifs` is an explicit proxy; its mismatch against the
unknown height of training sensors requires B's review. Archive has no silent
fallback to demo fixtures. Without genuine historical evidence, retain fixture
mode for the demo and do not claim archive readiness.

## Validation

```sh
python -m pytest -q
npm --prefix frontend run build
```

Python tests and the React TypeScript/Vite build cover
CSV consumption/integrity, chronology, source identities, input/output validation,
cache, HTTP/downloads, stored forecast context, summary fallback and legacy UI.
Tests clear OPENAI_API_KEY and mock SDK responses; they spend no API credits.
FastAPI TestClient needs local socket permissions in restricted environments.

One explicitly user-approved live test succeeded with `gpt-5.4-mini`: 24 generated
T2 weather rows → real CSV inference → LLM explanation, with no fallback. No raw
training CSV was sent. The React browser smoke test used an empty key and passed forecast rendering,
48-row model-input CSV download, a six-hour-window question, next-day comparison,
and the JavaScript error check (none).

## Remaining work

- Obtain independently reviewable as-issued capture and availability evidence for historical runs; coordinates alone are insufficient.
- Implement February replay over all 28 daily origins and both turbines.
- Validate feature mismatch between measured training weather and forecast inputs.
- Confirm timezone/interval/normalization metadata; score only if truth is supplied.

The fixture scenario uses explicit synthetic weather and locations; live mode
uses current Open-Meteo weather and organizer-supplied coordinates. The strict
historical archive remains unavailable without independent as-issued evidence.
This working demo is not a claim that the full organizer task is complete. See [AGENTS.md](AGENTS.md) for
working rules and [PLAN.md](PLAN.md) for current scope.
