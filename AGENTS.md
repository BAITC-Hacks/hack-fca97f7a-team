# Working agreement

## Current task and source of truth

The active application is **React + FastAPI**. The user explicitly authorized
this migration, real weather-to-CSV-to-model inference, and an OpenAI explanation
adapter. Earlier instructions deferring React/FastAPI/LLM implementation are
superseded. `app.py` is only the legacy Streamlit prototype.

Read [CONTRACTS.md](CONTRACTS.md) before changing a module boundary. README is the
launch/handoff guide; PLAN.md is the current scope. The latest user instruction
wins over these files. Do not add a database, queues or distributed orchestration.

The demo must be in Russian: all user-facing UI, explanations, fallback answers,
questions, errors and accessibility labels. Keep API identifiers and canonical CSV
headers unchanged. [tasks.md](tasks.md) tracks remaining implementation work for
the three developers, with ownership, priorities and acceptance criteria.

## Required flow and boundaries

1. React selects a registered turbine and submits an explicit forecast origin.
2. `api.py` validates HTTP bodies and calls `agent.run_forecast`.
3. `weather.py` normalizes provider output into hourly wind m/s and temperature °C.
4. `model_input.py` writes canonical CSV to `artifacts/model_inputs/<sha256>.csv`.
5. `model.predict_power_csv` reads and validates that exact file before inference.
6. The agent returns numeric predictions, statistics, provenance and actual trace.
7. React shows the result and requests an explanation by server-stored forecast ID.
8. `explanation.py` calls OpenAI with generated forecast facts, or returns an
   explicitly labeled computed fallback. Questions use the same stored result.

No UI/framework imports in core modules. No weather or inference logic in React.
Do not bypass the CSV boundary by exporting a file only after prediction. Never
let the LLM generate or overwrite numerical power predictions. Keys stay server-side.

## Data truth and chronology

- Preserve supplied files in `data/`. Distinct T1/T2 files contain 142,360/149,499
  rows and end January 31, 2026; no February truth is included despite filenames.
- Never relabel one turbine's history as another; reject identical source hashes.
- Source timestamps are assumed ten-minute interval starts in Asia/Almaty; drop
  and audit ambiguous/nonexistent local times, then convert to UTC.
- An hourly observation requires all six distinct samples; average the three
  measurements. Do not fill label gaps or remove zero-power observations.
- Freeze training at `2026-01-31T18:00:00Z`, using only completed hours. Never use
  February targets/actual weather to train, select or feed the forecasting model.
- Predict interval starts origin+1h through origin+24/48h. Origins are explicit,
  UTC-aware and hourly; never use today's date implicitly for historical replay.
- Weather initialization ≤ availability ≤ origin; verify every forecast hour,
  turbine identity and finite units before inference or cache reuse.
- Archive mode requires verified as-issued forecasts. Never replace them silently
  with fixtures, reanalysis, actual weather or retrospectively generated hindcasts.
- Power is normalized [0,1], not MW/MWh. No farm total without capacities and no
  accuracy claim without held-out truth. Report clipping and data exclusions.

Weather remains synthetic and must be labeled. Coordinates for T1/T2 were supplied
and mapped by the user through Google Maps; retain `coordinate_status=user_provided`
and the source links (see CONTRACTS.md). OpenAI is a real adapter; missing
keys/failure must be labeled fallback.
Do not claim full organizer compliance until archive weather and replay work.

## Ownership and how to make changes

For independent implementation tasks, the primary agent orchestrates: delegate
bounded coding work to faster subagents in parallel, then perform final integration
and verification itself. Prefer `gpt-6-sol` for coding and `gpt-6-luna` for bounded
checks when appropriate. This is a project work rule requested by the user; it
does not override module ownership, the current task scope, or the requirement to
coordinate shared contracts and preserve concurrent edits.

| Stream | Owns | Change here |
|---|---|---|
| A — integration/weather | api.py, agent.py, weather.py, contracts.py, fixture generator, config, dependency coordination | API routes, orchestration, real archive provider |
| B — data/model | data.py, model_input.py, model.py, scripts/train.py, corresponding tests | CSV feature schema, ingestion, predictor, replay |
| C — frontend/explanation | frontend/, explanation.py, summary tests | UI, central API client/types, grounded prose/questions |

Read CONTRACTS.md for signatures, DTOs, CSV version and change instructions.
Coordinate shared contract changes with affected owners; prefer additive fields.
Keep feature order/units/version aligned across the CSV writer, reader and model.
Train through CLI, not in requests. Load only locally generated model artifacts.

Keep HTTP errors structured. Never return provider exception details or keys.
Clear stale result/analysis/question state when input changes. Reject client-supplied
predictions in explanation requests; use server-stored forecast IDs. In-memory
stores are bounded; a restart/eviction returns 404 and the client regenerates.

## Development

Python 3.12+ (verified 3.14.4), Node 22+. From repo root:

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

FastAPI serves the built React app at http://localhost:8000 and docs at /docs.
For frontend hot reload run `npm --prefix frontend run dev` separately (5173
proxies /api to 8000). `.env` loads server-side with environment taking precedence.
Never put credentials in VITE_ variables or frontend files.

## Verification and commits

Run `python -m pytest -q` and `npm --prefix frontend run build` for interface changes.
Test CSV bytes/schema/hash, training cutoff, weather availability, cache invalidation,
API errors/downloads, stored-context explanation and stale UI handling. Tests clear
OPENAI_API_KEY and mock SDK responses; no paid calls in the automated suite.
TestClient requires localhost socket access in a restricted sandbox.

The user approved one live OpenAI smoke test, which passed. Do not treat that as
permission for unbounded repeated paid tests. Browser checks should use a backend
with an empty OPENAI_API_KEY unless further live tests are requested.

Commit working increments regularly as explicitly requested. Keep changes scoped;
never push unless asked. Preserve concurrent edits. Update README/CONTRACTS when
interfaces or launch commands change. Report real checks separately from mocked
ones and list remaining stubs accurately.
