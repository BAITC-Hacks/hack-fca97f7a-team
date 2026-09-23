# Wind power forecast — React + FastAPI

The active application is a React frontend with a FastAPI backend:

**Select turbine → weather tool → validated CSV → model reads CSV → predictions → OpenAI explanation.**

Both turbine models are trained from their separate real datasets. Weather and
map coordinates are still labeled fixtures. OpenAI explanation and forecast
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

1. Select T1/T2 on the map or selector. Keep January 31, 2026 and 48 hours.
2. Click **Predict generation**. Inspect the power chart and hourly table.
3. Click **Inspect model input CSV** to download the exact file the predictor read.
4. Read the explanation; its label distinguishes OpenAI from computed fallback.
5. Ask: **Which six-hour period has the highest average output?** The window is
   calculated locally and supplied to the explanation model.
6. Click **Advance one day & recalculate** to compare overlapping target hours.

Fixture weather exists only for January 31 and February 1 at 23:00 Asia/Almaty.
Other origins return an explicit error. Archive mode reports unavailable until
verified coordinates/weather are integrated. Input changes clear stale results.

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
Map coordinates `(0,0)` / `(0,0.03)` are intentionally fictional.

## Validation

```sh
python -m pytest -q
npm --prefix frontend run build
```

**41 Python tests pass** and the React TypeScript/Vite build passes. Tests cover
CSV consumption/integrity, chronology, source identities, input/output validation,
cache, HTTP/downloads, stored forecast context, summary fallback and legacy UI.
Tests clear OPENAI_API_KEY and mock SDK responses; they spend no API credits.
FastAPI TestClient needs local socket permissions in restricted environments.

One explicitly user-approved live test succeeded with `gpt-5.4-mini`: 24 generated
T2 weather rows → real CSV inference → LLM explanation, with no fallback. No raw
training CSV was sent. Subsequent browser tests use an empty key.

## Remaining work

- Resolve actual turbine coordinates and verify as-issued archived weather access.
- Implement February replay over all 28 daily origins and both turbines.
- Validate feature mismatch between measured training weather and forecast inputs.
- Confirm timezone/interval/normalization metadata; score only if truth is supplied.

The current app is a working demo with explicit weather/location stubs, not a
claim that the full organizer task is complete. See [AGENTS.md](AGENTS.md) for
working rules and [PLAN.md](PLAN.md) for current scope.
