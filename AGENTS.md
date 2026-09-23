# Working agreement

## Objective and current scope

Build a reliable wind-power demo: select a registered turbine on a map → obtain
weather through a tool → validate/convert features → predict normalized hourly
power → display chart/table/analysis → advance origin and recalculate.

The user has authorized implementation. Earlier planning-only instructions in
PLAN.md are superseded by that request. Read PLAN.md for domain context, but use
the actual files and public contracts as the implementation source of truth.

The first slice uses real supplied turbine measurements and fitted regressors,
synthetic weather, clearly fictional map coordinates, and computed summaries.
Do not describe stubbed weather or template prose as a live API/LLM result.
Do not build React/FastAPI, full February replay, live APIs, or paid inference
until requested for the next workstream. Preserve the working local demo.

## Data truth and chronology

- The current input files are distinct `turbine 1.csv` and `turbine 2.csv` under
  `data/`, with 142,360 and 149,499 records respectively. Both end January 31,
  2026. There is no February truth, despite the filenames. Do not concatenate
  duplicate downloads or relabel one turbine's records as another turbine.
- Never modify supplied CSVs or the organizer brief. Generated canonical data,
  models and outputs live in ignored directories, with source hashes/audits.
- Assume source timestamps are ten-minute interval starts in Asia/Almaty until
  confirmed. Drop/report ambiguous/nonexistent local times; convert to UTC.
- An hourly observation requires all six distinct ten-minute intervals. Mean
  wind, temperature and power over complete hours; report dropped hours. Keep
  zero-power observations. Do not interpolate labels across outages.
- Fit only hours whose end is at or before the frozen first origin
  `2026-01-31T18:00:00Z`. Never train on February targets/observed weather.
- Predict hours starting origin+1h through origin+horizon. Origins are explicit,
  UTC-aware, hourly; horizon is 24 or 48. No dependency on today's date.
- Weather initialization is not historical availability. Reject future-available
  weather, incomplete coverage and nonfinite features. Archive mode must never
  silently use fixtures, reanalysis or realized weather.
- Output is normalized power in [0,1], not MW/MWh. No physical farm total without
  turbine capacities and normalization metadata. No accuracy claim without truth.

## Architecture and contracts

- One Python process; Streamlit is a replaceable presentation layer.
- `contracts.py`: request/result/tool types, timestamps, errors, CSV serialization.
- `data.py`: source ingestion and audits. `model.py`: fit/load/predict only.
- `weather.py`: site registry and weather adapter. `agent.py`: orchestration,
  validation, result fingerprints/cache and executed-step trace.
- `explanation.py`: computed summary now; bounded OpenAI integration later.
- `app.py`: controls/map/rendering/session state; no training/weather logic.
- No core module may import Streamlit or depend on browser/session state.
  A later FastAPI layer wraps these functions; React consumes their JSON results.
- Keep public functions and JSON fields in `contracts.py`/PLAN.md stable. Prefer
  additive changes; coordinate breaking changes with all affected owners.
- A marker resolves to a configured turbine ID. Background clicks cannot invent
  sites. Coordinates must never be accepted as an unvalidated model identity.
- Train via CLI, not on UI reruns. Cache identity includes model, request, site,
  normalized weather and meaningful provenance; excludes retrieval wall time.
- Reject invalid weather before using cached predictions. Return structured
  errors and never render an old result as a new successful forecast.
- Explanations consume existing computed facts. They do not generate power
  predictions. LLM failure must retain a labeled template summary.
- Keep the first slice small: no queues, database, service hierarchy, or general
  plugin framework. Simple test injection is enough.

## Ownership for parallel work after this slice

| Stream | Owns | Next task |
|---|---|---|
| A: integration/weather | agent.py, weather.py, contracts.py, fixture generator, site config, README, dependencies | Verify as-issued archive and coordinates; add thin FastAPI endpoints if frontend work starts |
| B: data/model | data.py, model.py, scripts/train.py, data/model tests, future replay.py | Validate timezone/metadata, chronological baseline evaluation, full February replay |
| C: frontend/explanation | app.py, explanation.py, UI/summary tests, future frontend/ | React UI against frozen contracts; bounded OpenAI summary and scoped questions |

Shared dependency and contract edits go through A. Avoid editing another
stream's files without coordination. Do not overwrite concurrent user changes.
These ownership labels organize future human work, not permission to start
extra agents or expand the current task.

## Development and verification

Use Python 3.11+ in `.venv`; current workspace has Python 3.14. Run from repo root:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m scripts.make_fixtures
python -m scripts.train --mode fixture
python -m pytest -q
python -m streamlit run app.py
```

Test relevant boundaries: source mapping/deduplication, complete-hour aggregation,
timezone and leakage guards, weather coverage/availability, prediction bounds,
cache invalidation, summaries, and UI stale-result behavior. Exercise both demo
origins, both horizons, and both turbines. Do not assert exact learned predictions.
Distinguish real browser checks from Streamlit AppTest simulation.

No API credentials are needed for the slice. Future OpenAI keys belong only in
server environment variables; never commit or expose them to React. NVIDIA
credit is reserved; do not introduce a second provider without a concrete task.

Before handoff, document actual launch/test commands, evidence, stub boundaries,
unresolved provenance/timezone issues and the next task for each stream. Do not
claim the full organizer task is complete while archived weather/replay is absent.
