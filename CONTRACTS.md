# Module contracts and replacement guide

This file defines the boundaries for parallel work. Change an adapter behind its
interface rather than making every module understand a new provider/model.

```text
React (frontend/src/App.tsx)
  → frontend/src/api.ts → FastAPI (backend/api.py)
    → agent.run_forecast(request)
      → weather.fetch_weather(site, origin, horizon, mode)
      → validate historical availability + coverage
      → model_input.write_model_input(...) → artifacts/model_inputs/<sha256>.csv
      → model.predict_power_csv(model, csv_path, ...)
      → numeric result + analysis + trace
    → explanation.summarize_forecast(stored_result, backend)
      → OpenAI Responses API / explicit template fallback
  ← table + chart + model input download + explanation
```

## HTTP boundary — A owns backend, C owns frontend

Backend: `backend/api.py`; frontend transport: `frontend/src/api.ts`; TypeScript DTOs:
`frontend/src/types.ts`. OpenAPI is served at `/docs` and `/openapi.json`.

| Endpoint | Request | Response |
|---|---|---|
| `GET /api/health` | none | `status`, `llm_configured`, `summary_backend`; never credentials |
| `GET /api/sites?mode=live` | mode: live (UI); fixture/archive (internal) | `{sites:[{turbine_id,latitude,longitude,timezone,coordinate_status,coordinate_source}]}` |
| `POST /api/forecasts` | request below | forecast result plus `forecast_id` and `model_input` |
| `GET /api/forecasts/{id}` | stored forecast ID | checked stored result; no weather/model/LLM calls |
| `GET /api/forecasts/{id}/download?kind=forecast` | stored forecast ID | output CSV attachment |
| `GET /api/forecasts/{id}/download?kind=model-input` | stored forecast ID | exact CSV consumed by the model, hash verified |
| `POST /api/forecasts/{id}/explanation` | `{"backend":"llm"}` (or template) | explanation below |
| `POST /api/forecasts/{id}/questions` | `{"question":"When is output lowest?","backend":"llm"}` | answer using this stored forecast |

Forecast request is unchanged across UIs:

```json
{"turbine_id":"T2","origin":"2026-01-31T18:00:00Z","horizon_hours":48,"mode":"fixture"}
```

Success includes `status=ok`, those request fields, `timezone`, `run_id`,
`model_id`, `fingerprint`, `cache_hit`, `train_last_interval_start`,
`weather_provenance`, `hours`, `analysis`, `trace`, and:

```json
{
  "forecast_id": "64-character hex fingerprint",
  "model_input": {
    "schema_version": "weather-features-v1",
    "filename": "64-character-sha256.csv",
    "sha256": "64-character hex checksum",
    "row_count": 48,
    "columns": ["turbine_id", "valid_at", "wind_speed_ms", "temperature_c"]
  }
}
```

Each hour is `{valid_at,lead_hour,wind_speed_ms,temperature_c,power_norm}`.
Analysis contains `peak_power_norm`, `peak_at`, `min_power_norm`, `min_at`,
`clipped_count`, and `warnings`. Output is normalized power, not MW/MWh.

Explanation/answer: `{text,backend,forecast_fingerprint,warning,model?}`.
`backend=llm` means an actual OpenAI response; fallback is always `template`
with a reason. React renders numeric output before requesting the explanation.
It must check the explanation fingerprint and ignore responses from stale inputs.

Errors use HTTP 400/422/503/404/500 as appropriate and
`{status:"error",code,message,trace:[]}`. Unexpected tool/program failures
return `INTERNAL_ERROR` (HTTP 500) with a generic Russian message; malformed
weather/CSV data remains `DATA_INVALID` (HTTP 422). Forecasts are held in a bounded in-memory
store (64 results) backed by atomic, checksummed JSON in artifacts/forecasts.
Restart/eviction restores a validated record. Disk retention: newest 256 files,
maximum seven days. Missing/expired/corrupt records return 404; regenerate. This is intentionally a single-worker local demo, not distributed storage.

## Weather seam — A owns `backend/adapters/weather.py`

```python
load_sites(mode: str = "fixture") -> list[dict]
fetch_weather(site: dict, origin: str, horizon_hours: int, mode: str) -> dict
# {"manifest": {...}, "rows": [{"valid_at": "...Z", "wind_speed_ms": 6.2,
#                              "temperature_c": -4.0}, ...]}
```

Provider-specific JSON, unit conversion, grid selection and interpolation belong
in this adapter. Return **m/s**, **°C**, UTC hourly starts, and exactly the requested
hours in order. The agent validates these before writing CSV. Do not put weather
provider field names in React or the estimator.

Manifest requires turbine ID, run ID, provider, source URL, initialization and
availability timestamps, availability basis, provenance status, raw checksum and
interpolation policy. `initialized_at <= available_at <= origin` is mandatory.
Archive mode requires verified provenance. Fixture mode retains two synthetic
runs per turbine. Both modes use the same user-provided coordinates and source links.
Coordinates establish neither engineering identity nor weather eligibility.
See [Open-Meteo verification](docs/open-meteo-verification.md).

Site coordinates were supplied and mapped by the user: T1 is
`43.645150, 78.535604` ([source](https://maps.app.goo.gl/iN6svMt69D5qRpFU9));
T2 is `43.643198, 78.538828` ([source](https://maps.app.goo.gl/8UQMwsYavY6nLvFY8)).
`coordinate_status=user_provided` describes this source; `coordinate_source` is
the original Maps URL. Sites are available in both modes, while archive weather
requires verified run evidence. The fixture weather is still synthetic. Coordinates are
included in the existing forecast cache identity through the site metadata.

The archive adapter requests `single-runs-api.open-meteo.com/v1/forecast`,
`models=ecmwf_ifs`, one immutable UTC `run`, hourly `temperature_2m` and
`wind_speed_10m`, m/s, °C, UTC timezone (API reports GMT or UTC with zero
UTC offset). 10 m wind is a provider feature; sensor/hub height remains unknown.
The provider model is trained on this weather source rather than assuming parity
with SCADA wind. Grid latitude/longitude can differ from
requested turbine coordinates and are recorded in `weather_provenance`.
`interpolation=none` means the adapter does not interpolate; it does **not**
claim native provider hourly or vertical resolution. All target hours
origin+1 through origin+24/48 must be unique, ordered and finite. There is no fixture fallback.

Archive remains unavailable by default. Configure server-side
`OPEN_METEO_ARCHIVE_MANIFEST` to point at an operator-reviewed JSON file, e.g.:

```json
{"version":1,"runs":[{"turbine_id":"T1","origin":"2026-01-31T18:00:00Z","latitude":43.64515,"longitude":78.535604,"model":"ecmwf_ifs","run":"2026-01-31T12:00","initialized_at":"2026-01-31T12:00:00Z","available_at":"2026-01-31T17:00:00Z","attestation":"reviewed_as_issued","availability_basis":"external_capture_log","evidence_ref":"operator/capture-001","forecast_sha256":"<64 lowercase hex chars of canonical full forecast v1>"}]}
```

This example is a **schema illustration, not a verified historical run**;
never deploy it as evidence. A record is bound to exactly one turbine, its
registered coordinates, origin, run/model and the versioned canonical full
forecast digest. It requires independent external as-issued capture/log evidence for availability (not merely the run
initialization, API access time, current latest metadata or a retrospective
hindcast). The operator reviews that evidence before placing the manifest on
the server. No record, malformed/ambiguous record, or available_at > origin
blocks retrieval **before HTTP**; a canonical forecast mismatch also blocks
inference. `forecast_sha256` is SHA-256 of UTF-8 JSON with sorted keys,
compact separators and no NaN (`contracts.fingerprint` without `sha256:`),
over this version-1 object: `version=1`, `turbine_id`, float requested
`latitude`/`longitude`, `model`, `run`, float `grid_latitude`/`grid_longitude`,
`wind_height_m=10`, `temperature_height_m=2`, `wind_unit="m/s"`,
`temperature_unit="°C"`, `timezone="UTC"`, and `rows` sorted by valid_at
containing **every** hour in the returned full run as `{valid_at: ISO UTC Z,
wind_speed_ms: float, temperature_c: float}`. Provider UTC/GMT aliases,
key order and generationtime_ms do not change this digest; any extra/missing
forecast hour, weather value, grid coordinate or bound identity does. Evidence
must originate from independently verified historical captures, **not** a
retrospective query recalculated just to satisfy the hash. The adapter never
fabricates attestation from an HTTP success. `raw_sha256` in the returned
manifest always hashes exact bytes received for that retrieval; raw responses
are atomically retained at `artifacts/weather_raw/<raw_sha256>.json`. A corrupt
existing artifact blocks inference instead of being overwritten. Model features
still pass only through the canonical CSV writer and reader.
`availability_basis` in responses includes the evidence reference; neither
source URL nor errors contain credentials. The public endpoint uses no API key.
This file is trusted configuration, **not independently self-proving**: do not
manufacture checksums/evidence from today's historical query and call it
as-issued. Test malformed values, missing hours, wrong turbine and future
publication times. Historical weather/reanalysis/stitched runs are not substitutes.

## CSV seam — B owns `backend/ml/model_input.py`

```python
write_model_input(rows, turbine_id, origin, horizon_hours) -> dict
read_model_input(path, *, turbine_id, origin, horizon_hours, expected_sha256) -> list[dict]
```

Exact UTF-8 header, order and units (`weather-features-v1`):

```csv
turbine_id,valid_at,wind_speed_ms,temperature_c
T2,2026-01-31T19:00:00Z,6.2,-4.0
```

There are exactly 24 or 48 rows; timestamps equal origin+1h through origin+horizon.
One turbine only; finite numeric features; no duplicate/missing hours; nonnegative
wind. No target power or truth column is allowed in prediction inputs. Filenames
are content-addressed SHA-256. The file is atomically written under ignored
`artifacts/model_inputs/`; portable metadata is returned, never an absolute path.

The model reads this file and verifies its checksum, schema, site and window.
This is the actual inference input, not a decorative export made afterward.

If adding model features, increment schema version and update the writer, reader,
model training feature list, weather normalization, DTO metadata and relevant
contract tests together. Do not silently rename columns or change units.

## Model seam — B owns `backend/ml/model.py` and `backend/ml/data.py`

```python
train_model(history, origin, turbine_id) -> PowerModel
load_model(turbine_id, *, profile="measured") -> PowerModel
predict_power_csv(model, csv_path, *, turbine_id, origin,
                  horizon_hours, expected_sha256) -> list[float]
```

`PowerModel.metadata` retains turbine ID, model ID, feature list, training origin,
last completed training interval and frozen persistence baseline. The agent
requires matching turbine and a training cutoff no later than the first origin.
Locally generated versioned model artifacts also record the source and canonical
data hashes, feature order and units, fit parameters and environment versions.
`load_model(turbine_id)` remains the measured-profile loader and checks the selected turbine;
regenerate artifacts through `python -m scripts.train --mode fixture` after
changing ingestion or features. See [DATA_MODEL_HANDOFF.md](DATA_MODEL_HANDOFF.md)
for measured-source audits and unconfirmed weather feature provenance.
CSV inference returns one finite value per row in the same order. The agent clamps
to [0,1] and reports how many values needed clamping.

To replace the regressor, change fit/load/predict inside this module and retrain
via `python -m scripts.train --mode fixture`. Preserve output alignment and metadata.
`predict_power(model, rows)` is the lower-level helper; orchestration must call the
CSV interface. Models are fitted once from separately identified turbine datasets,
not during HTTP requests or React renders.

## Orchestration seam — A owns `backend/services/agent.py`

`run_forecast(request, *, weather_tool=..., model_loader=...) -> dict` stays free
of FastAPI, Streamlit and React. It validates requests, calls tools, writes CSV,
loads/predicts, computes analysis, and records actual execution steps.

Cache identity includes request, site, model identity, weather content/provenance,
and CSV schema/checksum. Weather is revalidated and the CSV is ensured present
before cached predictions are returned. Retrieval wall time is not content identity.

Keep error mapping and transport in `backend/api.py`. Keep numeric analysis in the core;
LLM prose must not overwrite predictions, uncertainty, or provenance.

## Explanation seam — C owns `backend/adapters/explanation.py`

```python
summarize_forecast(result, backend="template") -> dict
answer_question(result, question, backend="llm") -> dict
```

FastAPI supplies a server-stored successful result, never client-authored power
values. The adapter sends only generated forecast context and computed facts to
OpenAI. Source training CSVs and API keys are not included in prompts. Six-hour
windows are calculated locally before prose generation. Unsupported local questions
return a limitation rather than fabricated answers.

OpenAI uses `OPENAI_API_KEY`, `OPENAI_MODEL` and the Responses API, bounded by an
8-second timeout and no automatic retries. Missing keys/provider failures return
computed prose with an explicit warning. Successful prose is cached by forecast
fingerprint, model, prompt version and question. The UI labels the actual backend.

To change provider: modify the adapter/client factory here, preserving return fields
and failure behavior. Do not put provider calls or credentials in frontend code.

## Checks after changing a seam

```sh
python -m pytest -q
npm --prefix frontend run build
```

Tests never use paid APIs: the suite clears the key and mocks SDK responses.
`tests/test_model_input.py` verifies real CSV roundtrips/integrity;
`tests/test_api.py` verifies transport/download/stored-result boundaries;
`tests/test_explanation.py` verifies grounded payloads, cache and failures.
Commit compatible increments and coordinate shared schema changes across A/B/C.

## Versioned model artifacts

`load_model(turbine_id, *, profile="measured")` is the loading boundary. Default training writes
`artifacts/models/<turbine>/<model-hash>/model.pkl` and `metadata.json`, then
updates `latest.json`. Loading verifies estimator identity, checksum, feature
units/order and Python/scikit-learn compatibility. Trusted legacy per-turbine
pickle files remain readable only when no new registry exists; retraining migrates.
Metadata retains `train_origin` and `features` alongside `train_cutoff` and
`feature_names`. `predict_power_csv` returns raw finite predictions so the agent
retains ownership of clipping/counts. The independent diagnostic helper may clip.

## Current live weather

`mode=live` is supported by HTTP, core and React, and is the UI default.
The server replaces request origin with its current UTC hour; output remains
origin+1h through origin+24/48h. Historical dates are not used in this mode.
`backend/adapters/weather.py` fetches https://api.open-meteo.com/v1/forecast for the registered
coordinates, fixed `models=ecmwf_ifs`, wind_speed_10m and temperature_2m, m/s, °C, UTC,
three forecast days. Exact hourly coverage/units/finite values are validated
using the same parser as archive. Raw bytes and SHA-256 are saved before CSV inference.
There is no synthetic fallback on provider failure.

Live provenance is `live`, `availability_basis=live_http_retrieval`, and
`retrieved_at=available_at` records actual retrieval. `initialized_at=null`: the
provider run initialization is unknown, not fabricated. Live retrieval must be no more than five minutes old and not in the future;
cache reuse across an hour boundary still requires full target coverage; archive retains its stricter as-issued chronology.
Weather wind height is 10 m. It is used as a provider feature, not interpreted as
the unknown turbine sensor/hub height. Model training remains frozen. Baseline values are only for internal model
evaluation and are absent from user-facing hours, CSV and explanation inputs.

## Provider-compatible power model

`fixture` selects `profile=measured`; `live` and verified `archive` select
`profile=open_meteo_ecmwf_ifs_10m`. There is no fallback between model profiles.
Provider artifacts live under `artifacts/models/open_meteo_ecmwf_ifs_10m/` with
their own `latest.json`. The profile, fixed recipe and weather context (provider,
model, feature heights, historical source kind and verified CSV digest) are part
of the model identity. The agent checks profile/model/heights before inference.
The canonical input CSV remains `weather-features-v1`: raw m/s and °C features,
same two columns and order, no numerical height correction in the adapter.

`python -m scripts.fetch_training_weather --start-date 2024-01-01 --end-date 2026-01-31`
creates a checked raw cache and `training_weather.csv`/`manifest.json` under
`artifacts/training_weather/`. This is Historical Forecast API with fixed ECMWF
IFS, a retrospective stitched series whose origin availability is **UNVERIFIED**.
It is training/diagnostic data, never valid runtime archive evidence.
`load_training_weather` rechecks source/request/site/grid/unit/coverage identities
and raw/CSV hashes. `python -m scripts.train_forecast --activate` joins weather to
power by turbine and UTC hour, selects a recipe on September–October 2025, checks
November–January, and refits through the frozen cutoff only if gates pass.
Missing complete-hour labels are counted and excluded, never filled.

Successful real-weather results add `model_provenance` with `profile`,
`training_weather_kind=retrospective_stitched_forecast`,
`forecast_accuracy_verified=false`, `weather_model=ecmwf_ifs`, `wind_height_m=10`.
Weather provenance adds `weather_model` and `temperature_height_m=2`;
`wind_height_status=provider_feature_not_sensor_measurement`. Model metadata
contains training feature ranges; out-of-range inference hours generate a warning.
UI and explanations retain the explicit experimental-model limitation.
This improves source compatibility, not proof of 24/48-hour forecast skill.
The verified Single Runs manifest/digest/availability gate remains mandatory.

## Weather cache and persistent forecasts

Live HTTP responses use a bounded eight-entry cache with a 300-second TTL, keyed
by turbine, coordinates, URL and provider parameters. Coverage and raw artifact
integrity are rechecked on reuse. `weather_cache_hit` is a boolean in provenance;
`retrieved_at` retains actual original retrieval time. Volatile live retrieval
fields are excluded from numeric forecast identity; archive provenance is retained.
A UTC-hour boundary before/during/after retrieval triggers one refreshed-origin
retry. A second crossing returns structured WEATHER_UNAVAILABLE.

`POST /api/weather/refresh` accepts `{"turbine_id":"T1"}` (or T2), clears that
turbine's cache, and returns `{"status":"ok"}`. React then regenerates the
forecast using the normal request/epoch flow.

Completed API results are saved as version-1 JSON envelopes with a SHA-256 content
digest. Downloads/explanations restore after memory eviction or restart, subject
to disk retention. Inputs remain server-owned; corrupt JSON, wrong identity,
invalid coverage or checksum mismatches are rejected. Legacy baseline fields
are stripped before response/explanation. No database or distributed workers.

## Conditional February replay (internal CLI only)

`backend/adapters/replay_weather.py` stores individual dated ECMWF IFS responses.
The CLI explicitly opts in using `--weather-source provider-documented`; HTTP
archive and default replay retain the strict verified gate. This path returns
`provenance_status=provider_documented`, `available_at=null`,
`availability_verified=false`, `assumed_available_by=run+24h` (an assumption).
The selected run is previous-day 00 UTC for origin 18 UTC, age42h. Agent accepts
this only with `allow_documented_archive=True`, preserving the caveat in output.
No publication time or external attestation is manufactured. See docs/february-replay.md.

React retains only the last live forecast ID in localStorage. On reload it uses
GET to reopen checked server data and labels it saved, with original retrieval time.
It does not auto-call explanation on restore. Missing/expired IDs return404 and
are cleared; explicit refresh regenerates real weather and prediction.

Model registries now write paths relative to latest.json (T1/hash). The loader retains legacy absolute/repository-relative compatibility and requires the resolved turbine directory. scripts/package_replay.py verifies and exports a portable February bundle without secrets or training CSVs.
