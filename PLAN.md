# Hackathon Plan

## 1. Problem

Predict hourly normalized turbine output 24–48 hours ahead from weather forecasts
available at each historical forecast origin. The final submission must replay
February 2026 using real turbine history and verified as-issued weather.

**Current user-authorized build:** React + FastAPI, explicit weather → CSV → model
inference, LLM explanation, basic questions, and documented replaceable modules.
This supersedes the earlier Streamlit-first implementation brief.

## 2. Assumptions

- Both distinct T1/T2 datasets are supplied; 142,360/149,499 ten-minute records.
  Both end January 31, 2026. February truth is absent.
- Source timestamps provisionally mean interval starts in Asia/Almaty. Audit
  ambiguous times and incomplete hours; confirm this convention with organizers.
- Output is normalized power [0,1]. Capacity/normalization denominator is unknown.
- Freeze models before January 31, 2026 18:00 UTC (23:00 local), using completed
  hours only. Forecast starts at origin+1h, February 1 midnight local.
- Real numeric coordinates and T1/T2 mapping were supplied by the user through
  Google Maps (see CONTRACTS.md). Live uses real Open-Meteo ECMWF IFS and a
  separately trained provider model. Fixtures remain synthetic; verified
  as-issued weather provenance is still unavailable.

## 3. Primary Demo

Select T1/T2 on the React map, choose January 31 and a 48-hour horizon, and click
«Сформировать прогноз». FastAPI orchestrates weather validation, CSV creation, actual
CSV-based power inference and numeric analysis. The user sees the table/chart,
can download the exact model input, and then sees an OpenAI explanation.
Ask which six-hour window has the highest output; the backend computes the window
and explains it. Advance one day and compare predictions for overlapping hours.

## 4. Demo Success Criteria

- React communicates with FastAPI; no Streamlit dependency in the active flow.
- Actual CSV is written and consumed by the model, with schema and SHA-256 checks.
- Exactly 24/48 valid hourly predictions; provenance/units visible.
- Numeric results appear before the bounded explanation request completes.
- LLM failure preserves forecast and clearly labels the computed fallback.
- Stale responses never appear under a new site/date/horizon.
- Forecast and model-input CSV downloads match the selected result.

## 5. Scope

### Must Have

React map/controls/table/chart, FastAPI transport, audited real-data training,
weather adapter, canonical CSV conversion, CSV model inference, OpenAI adapter,
scoped questions, visible stubs, tests and documented module boundaries.

### Mock Initially

Weather API. Computed prose only when OpenAI is absent
or fails; never call that fallback an LLM response. Real regressors use separate
real turbine histories.

### Later If Time

Verified archive retrieval, full February batch replay, held-out accuracy metrics,
improved forecast-feature training and calibrated uncertainty.

### Explicitly Cut

Arbitrary-location turbine modeling, auth/database/queues, distributed services,
autonomous agent hierarchies, cloud deployment and unbounded chat.

## 6. First Vertical Slice

Implemented flow: React → FastAPI → weather bundle → validated CSV file → model
reads CSV → numerical result → OpenAI explanation / explicit fallback. Fixture
runs cover January 31 and February 1 origins, each 24/48 hours and both turbines.
Other origins fail clearly rather than inventing weather. Streamlit remains only
as an optional legacy prototype.

## 7. Architecture

```text
frontend/src/api.ts → api.py → agent.py
                               ├─ weather.py: normalized hourly bundle
                               ├─ model_input.py: canonical CSV artifact
                               ├─ model.py: read CSV, infer real power model
                               └─ analysis/provenance/result
                  api.py → explanation.py → OpenAI / computed fallback
```

One local FastAPI process, bounded in-memory result store, local model/artifact
files. React can use Vite in development; FastAPI serves frontend/dist for a
single-port demo. No prediction logic or credentials in the frontend.

## 8. Technology Stack

Python 3.12+, pandas/numpy/scikit-learn for local regression, FastAPI/Pydantic for
HTTP validation, OpenAI SDK Responses API for prose. React/TypeScript/Vite and
Leaflet for the frontend. CPU-only; no GPU or NVIDIA integration needed yet.
Pinned dependencies and npm lockfile are committed. README has exact commands.

## 9. Shared Contracts

**Authoritative interface guide:** [CONTRACTS.md](CONTRACTS.md). Runtime boundaries
are `contracts.py`, `model_input.py`, HTTP schemas in `api.py`, and DTOs in
`frontend/src/types.ts`. Keep them compatible.

Request:

```json
{"turbine_id":"T2","origin":"2026-01-31T18:00:00Z","horizon_hours":48,"mode":"fixture"}
```

CSV schema `weather-features-v1`:

```csv
turbine_id,valid_at,wind_speed_ms,temperature_c
T2,2026-01-31T19:00:00Z,6.2,-4.0
```

Success includes hourly rows, computed analysis, trace, provenance, model identity,
forecast ID and model-input artifact metadata. Explanation requests reference the
stored forecast ID; they cannot supply replacement predictions. See CONTRACTS.md
for all routes, errors, signatures and replacement instructions.

## 10. Repository Structure

```text
AGENTS.md / PLAN.md / CONTRACTS.md / README.md
frontend/src/       React UI, api.ts transport, types.ts DTOs
api.py              FastAPI, validation, result store, downloads
agent.py            orchestration, chronology, cache, numeric analysis
weather.py          live ECMWF IFS, fixture and verified archive adapters
model_input.py      canonical CSV writer/reader and schema version
model.py / data.py  local fitting/inference and measurement ingestion
explanation.py      bounded OpenAI explanation and scoped questions
scripts/            reproducible fixture and training commands
fixtures/           small synthetic weather JSON bundles
 data/              supplied immutable data; generated canonical files ignored
artifacts/          ignored trained models and exact inference input CSVs
tests/              offline module and API contract tests
```

## 11. Team Ownership

A owns API/orchestration/weather/shared dependency coordination. B owns ingestion,
CSV/model/replay. C owns React and explanation/questions. AGENTS.md lists files;
CONTRACTS.md explains what to change and what to preserve at each seam. Commit
regularly and coordinate shared DTO/schema changes.

## 12. Critical Risks and Fallbacks

| Risk | Validation | Fallback |
|---|---|---|
| As-issued weather archive inaccessible | Retrieve a real eligible run with publication evidence | Verified organizer cache; otherwise explicitly incomplete fixture demo |
| Timezone/interval/capacity unknown | Confirm metadata; preserve ingestion audit | Explicit assumptions, normalized output only |
| Forecast-weather vs measured-feature mismatch | Chronological holdout and archive overlap | Simple trained regressor with honest limitations |
| OpenAI failure or latency | One user-approved live test passed; mock failures in tests | Bounded request and computed prose, labeled template |
| Integration drift | CSV and HTTP contract tests; React typecheck/build | Stable boundaries in CONTRACTS.md; no frontend/core coupling |

## 13. Implementation / Next Handoff

The requested React/FastAPI migration and CSV/LLM seams are implemented. Follow
README to install, train, build and launch. Before replacing a stub, read the
specific CONTRACTS.md section and run its tests. A replaces weather/site adapter,
B improves model/CSV schema and adds replay, C improves UI/prose. Preserve the
working demo while completing real archive requirements.

## 14. Definition of Done

**Model improvement, September 23:** provider-specific training and chronological
checks implemented; details and remaining errors in [FORECASTING_REPORT.md](FORECASTING_REPORT.md).
Retrospective stitched-weather diagnostics improve MAE by about 51%; this is not
verified 24/48-hour forecasting skill. The real live path was checked for both
turbines and horizons with input CSV checksum validation.

**Current slice:** both turbines predict from actual input CSVs, React/FastAPI
flow works, OpenAI adapter is wired, fallback is honest, errors/downloads tested,
module change instructions documented, code committed. Verification is in README.

**Full organizer submission remains:** verified as-issued weather for the supplied sites,
28 daily origins for both turbines (2,688 48-hour rows including March spillover),
February coverage checks, reproducible replay, and accuracy only if truth arrives.
