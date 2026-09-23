# Hackathon Plan

## 1. Problem

Build a reproducible agentic workflow that predicts hourly wind-turbine output 24–48 hours ahead using historical turbine measurements and **weather forecasts actually available at the forecast origin**. Optimize for one reliable local demo and a complete February replay.

**REQUIRED by organizer:** learn from supplied March 2023–January 31, 2026 history; obtain weather forecasts by the two turbine coordinates; produce hourly 24–48-hour predictions; replay successive forecast origins across February 1–28, 2026; autonomously fetch, prepare, predict, analyze, and recalculate when inputs update. README/reproducibility is worth 25/100 points, equal to functionality and technical implementation.

**TEAM DEMO DECISION:** map selection → weather retrieval → hourly power forecast → short explanation → recalculation. Organizer does not require an LLM; the team wants a model-generated explanation after the first slice. Use a computed text summary initially, add an LLM after the forecasting path works, and leave conversational follow-up optional. Agent framework, cloud deployment, database, and uncertainty intervals are unnecessary.

**CONFIRMED:** the organizer brief is `data/HackAlem AI_ Agentic AI для прогнозирования выработки ВЭС.md`; it matches the previously supplied requirements. Distinct turbine 1 and turbine 2 CSVs are now present (142,360 and 149,499 rows). Both end January 31, 2026; February truth is absent. Root AGENTS.md defines implementation rules and parallel ownership.

**UNKNOWN:** numeric coordinates, measurement timezone/interval semantics, normalization denominator, capacity, submission format, and historical weather access. Treat filenames as provisional turbine identity, not evidence of a second turbine. The user has now authorized implementation of the first vertical slice; full archive integration and frontend migration remain later workstreams.

## 2. Assumptions

- Two independent turbine forecasts; no claimed physical farm total without capacity weights. Output is normalized hourly mean power, not MW or MWh. Observed targets are in [0,1]; preserve this supplied scale without rescaling or clipping training labels. The normalization denominator remains undocumented.
- Raw timestamps have no timezone and occur every ten minutes. Provisionally treat them as ten-minute interval starts in `Asia/Almaty`. Convert with that IANA timezone, including historical offset changes; internal timestamps are UTC. A source hour becomes usable after its end. Use this explicit assumption to unblock the slice; confirm it before claiming verified time alignment. Drop and report ambiguous/nonexistent local timestamps rather than guessing across clock changes.
- Daily origin is 23:00 local. First origin: `2026-01-31T18:00:00Z`; first target: `2026-01-31T19:00:00Z` (February 1 midnight local). Predict the next 48 hourly starts. Offer 24 hours as a subset.
- February replay uses 28 daily origins, January 31–February 27 local. Keep all 48-hour outputs; February 28-origin forecasts concern March and are outside scored coverage. Score only February targets, separately for leads 1–24 and 25–48; never average overlapping forecasts before scoring.
- Freeze the fitted model before the first origin, using only completed source intervals then available and never February labels. Using a subset of January 31 history avoids intraday leakage. No daily retraining in the MVP.
- Resolve the two map links in the brief into `sites.csv` before the real demo. Automated map access failed during planning; do not invent real coordinates. Fixture coordinates are explicitly fictional.
- Map selection means selecting a registered turbine marker, T1 and T2 with separate fitted models. Arbitrary locations do not have a fitted turbine model; background clicks must not start a forecast. Both fixture markers are visibly fictional until real coordinates are resolved.
- First slice uses supplied **T1/T2 measurements plus synthetic weather**. `mode=fixture` identifies weather provenance; label the UI “Real turbine training data; synthetic weather.” It **does not satisfy** the archival requirement. Train each turbine from its own source; reject identical files across turbine identities.

## 3. Primary Demo

**DEMO INPUT:** turbine `T2`, origin January 31, 2026 at 23:00 Asia/Almaty, horizon 48 hours; organizer-trained model and verified archived weather cached locally.

**60–90 second script:**

1. Open the map and click T2's marker. The side panel shows turbine, coordinates, forecast origin, and a 24/48-hour selector; default to the input above.
2. Click **Predict generation**. Agent selects an eligible historical weather run, loads/fetches it, validates coverage, prepares features, predicts, and checks results. Display these steps without requesting further user decisions.
3. Show the hourly normalized-power chart, weather chart/table, persistence baseline, CSV download, and expandable provenance/trace. Display “Historical replay” prominently; do not present January/February forecasts as live.
4. Show a short explanation of the computed peak, low-output hours, and limitations. First slice uses a deterministic template; the final demo adds an LLM paraphrase. Never let the LLM generate power values or claim unmeasured accuracy.
5. Click **Advance one day**. Select the newly eligible weather run, recalculate, and highlight changed predictions on overlapping timestamps. The explanation updates with the result. Unchanged inputs reuse their result.
6. Show February replay coverage, showing coverage for both turbines and explicitly marking missing truth. If time remains, ask “When is output lowest?” using only the displayed forecast context; conversational follow-up is outside the core script.

**DEMO OUTPUT:** clickable turbine map → power/weather plots → grounded explanation → changed forecast; CSV, provenance, trace, and replay coverage remain inspectable. The value is a usable, auditable forecasting cycle rather than an isolated model prediction.

## 4. Demo Success Criteria

- Selecting a supported map marker and clicking Predict generation completes the workflow; no notebook execution or manual model selection during presentation. A background click cannot forecast an untrained location.
- Exactly 48 contiguous finite hourly predictions in [0,1] per selected turbine; units and timezone visible.
- Weather source, run, availability basis, train cutoff, and real/fixture mode are visible.
- Advancing origin changes the input fingerprint and triggers computation; unchanged inputs do not.
- Cached forecast and computed summary finish within 5 seconds. Display them before an optional LLM call; bound that call to 8 seconds and keep the template on failure. Invalid/missing weather yields a clear failure, not fabricated output.
- T2 February export and documented launch/replay commands work; both turbines use their own real training data. Full two-turbine compliance remains a separate completion gate.

## 5. Scope

### Must Have

- Deterministic ingestion into canonical CSV, per-turbine regression, persistence baseline.
- As-issued archive weather adapter with cache and availability guard; full-period replay.
- Bounded agent: select → fetch → validate → prepare → predict → analyze → export; change detection and trace.
- Streamlit map with supported turbine selection, forecast dashboard, computed explanation and CSV download; source provenance; README; focused leakage/contract checks.
- Post-slice: add model-generated explanation using the fixed summary interface; template remains the explicit fallback.

### Mock Initially

- Two deterministic synthetic weather runs, flagged `fixture` throughout; fictional fixture coordinates until map links are resolved.
- Use actual T1/T2 training history from the supplied CSVs. Small synthetic measurement samples are for automated tests only.
- Canned weather retrieval uses the real tool interface. Never hardcode prediction arrays, agent traces, a second turbine dataset, or February truth.

### Later If Time

- Train on matched archived forecast features to reduce weather-to-measurement domain shift; calibrated intervals; capacity-weighted farm output if capacities arrive.
- After the slice, a separate frontend can proceed in parallel: A wraps the frozen functions with FastAPI; C builds React against the same request/result contracts. Preserve the runnable Streamlit demo until replacement passes the same checks.
- One-turn follow-up questions about the displayed result, only after map/forecast/explanation/replay work. A live-weather mode is also optional and cannot replace the required historical replay.

### Explicitly Cut

- Open-ended chat, arbitrary-location forecasting, authentication, database, queues, containers/cloud deployment, multi-agent hierarchy, hyperparameter search, deep learning, automated retraining, alert delivery, custom map design.
- Reanalysis, realized February weather, retrospective hindcasts, and future labels as substitutes for as-issued input forecasts.

## 6. First Vertical Slice

**INPUT:** `T2`, `2026-01-31T18:00:00Z`, 48 hours, fixture mode.

**END-TO-END FLOW:** click registered T2 map marker → Streamlit request → `run_forecast` → fixture weather tool → eligibility/coverage checks → two-feature preparation → fitted regressor → computed analysis/trace → chart/table/CSV → `summarize_forecast` template. Advance one day and repeat with the second fixture run.

**OUTPUT:** the frozen result contract in §9 and its visible rendering.

**REAL COMPONENTS:** UI, orchestration, supplied T1/T2 CSV parsing and hourly aggregation, fitting/inference, timestamp validation, cache fingerprinting, analysis, CSV serialization, error handling.

**MOCKED COMPONENTS:** weather forecasts/transport, unresolved site coordinates, and LLM prose (computed template). Measurements, model fitting, inference, and summary statistics are real. Do not score synthetic-weather predictions as forecast accuracy.

**DEFINITION OF DONE:** runs from a clean environment without weather/LLM credentials or network calls; map tiles/assets may require internet, with a synchronized site-selector fallback if unavailable. Passes §13 tests; fixture banner persists on screen and in exports. Target: implementation minutes 25–75 of the hackathon, then hand off parallel work.

## 7. Architecture

Choose one Python process with Streamlit and local files for the first slice. Prepare for the user's later React frontend + thin FastAPI backend: no core module imports Streamlit, and UI session state stays separate from forecasting state. A later HTTP layer wraps the frozen JSON-compatible functions; it does not rewrite forecasting.

```text
Map + Streamlit controls / replay CLI
            |
      forecasting agent ----> weather adapter ----> archive / local cache
            |                       |
      validate + features <---------+
            |
      fitted regression <---- canonical turbine history
            |
      analysis + trace ----> chart / CSV / replay summary
            |
      explanation adapter -> template first / LLM later
```

| Component | Responsibility; input → output | Demo-critical |
|---|---|---|
| UI | marker selection + controls + result → map, chart, table, download | Yes |
| Explanation | validated forecast facts → short summary; no prediction authority | Template in slice; LLM later |
| Agent | request + model + weather tool → validated result/trace | Yes |
| Weather | site + origin + horizon → eligible hourly weather bundle | Yes |
| Data/model | canonical history → fitted per-turbine model; weather → predictions | Yes |
| Replay | 28 origins × available sites → long CSV + explicit missing-site coverage | Final demo |

Model: `HistGradientBoostingRegressor(max_iter=100, max_leaf_nodes=15, random_state=42)` per turbine, features `[wind_speed_ms, temperature_c]`; clamp predictions to [0,1] and report count clamped. Train on measured wind/temperature and normalized power. Explicit limitation: weather-model inputs differ from local measured training features. Baseline repeats last eligible measured power; February origins still use the frozen latest pre-test observation, clearly labeled “frozen persistence.” January chronological validation uses only its prior training data and eligible observations.

Weather decision: use **NOAA NCEI GFS 0.5° operational forecast archive**, nearest grid point, 10 m wind and 2 m temperature. Select the newest eligible run that spans the full target window. Interpolate same-run 3-hour forecast values to hourly; no extrapolation or cross-run stitching. Compute wind from U/V components before interpolation. Request a point subset through NCEI THREDDS NetCDF Subset Service (NCSS); parse NetCDF with xarray/scipy. If NCSS cannot serve this dataset, use the provenance-checked canonical archive cache supplied/exported separately; do not spend the remaining hackathon writing a GRIB download system.

**Archive gate, owner A, first 30 minutes after handoff:** verify one January 31 operational run for the real coordinates, units, forecast horizon, publication schedule, and retrieval endpoint; then prefetch all required runs. Initialization time is not publication time. Provisionally require `initialized_at + 8h <= origin`; record this as an assumed conservative lag until supported by publication evidence. Unverified availability stays `unverified`, never silently becomes compliant.

Planning evidence: [NCEI GFS documentation](https://www.ncei.noaa.gov/products/weather-climate-models/global-forecast) describes 0.5° forecasts at 3-hour intervals and approximately two years online. The specific February catalog could not be retrieved during planning, so accessibility remains unvalidated. [Open-Meteo Single Runs documentation](https://open-meteo.com/en/docs/single-runs-api) describes older ECMWF coverage as hindcasts and distinguishes initialization from availability; do not treat that coverage as proof of an operational as-issued archive.

**Presentation adapter:** `explanation.py` consumes a successful forecast result and returns text; it neither fetches weather nor retrains the model. Template mode is real computed prose. Post-slice, C adds one bounded OpenAI Responses API call through the OpenAI Python SDK, with a template fallback. Send only forecast rows, computed analysis, timezone/units, and provenance, never the raw training dataset. Cache explanation by forecast fingerprint + backend + model ID + prompt version; preserve explicit `template|llm` labeling.

## 8. Technology Stack

| CHOICE | WHY |
|---|---|
| Python 3.12+, venv, pip (verified on 3.14) | One runtime for model, orchestration, UI; straightforward local setup. |
| Streamlit + folium + streamlit-folium | Clickable map, form/chart/table/download without a separate frontend build. Use st_folium marker events; keep selection in session state. |
| OpenAI Python SDK, post-slice only | One text-summary call; first slice uses a deterministic template with the same interface. No agent framework. |
| pandas, numpy, scikit-learn | CSV/time handling and a small CPU model; no GPU or paid inference. |
| requests; xarray + scipy | Bounded HTTP retrieval and point NetCDF decoding; weather adapter only. |
| Local CSV/JSON + pickle model artifacts | Inspectable reproducible outputs, no database. Load only locally produced model artifacts. |
| pytest | Small meaningful contract, chronology, and invalidation checks. |

Freeze exact installed versions in `requirements.txt` after the first successful local run. First slice has no LLM dependency or credentials. Map reference: [streamlit-folium](https://github.com/randyzwitch/streamlit-folium) documents bidirectional map interaction. Post-slice summary uses `gpt-5.4-mini`, documented in the [official OpenAI model page](https://developers.openai.com/api/docs/models/gpt-5.4-mini), through the [Responses API](https://developers.openai.com/api/docs/guides/text). User reports $50 OpenAI API credit and $50 NVIDIA API credit. Choose OpenAI for explanation and optional follow-up; reserve NVIDIA credit rather than adding a second provider integration now. Account model access and latency need one smoke test after the slice; failure retains the template. Local regression remains responsible for numeric power forecasts.

## 9. Shared Contracts

Frozen for first implementation. A coordinates any blocking amendment before other owners change consumers. No public HTTP API.

**Configuration:** `DATA_MODE=fixture|archive` (default `fixture`, controls weather), `DATA_DIR=./data`. Both modes train on supplied T1/T2 history; fixture measurements exist only for tests. Origin/horizon/site are explicit inputs, never inferred from today's date. No silent archive→fixture fallback. `SUMMARY_BACKEND=template|llm` defaults to `template`; post-slice LLM uses `OPENAI_API_KEY` and `OPENAI_MODEL=gpt-5.4-mini`. Never require a key for template mode.

**Supplied data / ingestion contract:**

- Read the exact `data/Dataset HackAlemAI для участников 11.03.2023-28.02.2026 - turbine 1.csv` and `... - turbine 2.csv` as T1/T2. T1 has 142,360 rows, SHA-256 `c4c341582fb2dd348b7187f0128cff265fe055f469413871ebb5db50eef58b5b`; T2 has 149,499 rows, SHA-256 `820578cd18bb557cd30c2e102f3ae5a386dfc6c489a5a15743339c2b017305e5`. Preserve originals. Ignore suffixed duplicate downloads; reject identical source hashes across turbine identities.
- Comma-separated UTF-8, decimal points. Drop `ID` (row counter). Map `Статистическое время` → timestamp, `Средняя скорость ветра(m/s)` → wind_speed_ms, `Нормализованная активная мощность` → power_norm, `Средняя температура окружающей среды(°C)` → temperature_c. Parse timestamps with `%Y-%m-%d %H:%M:%S` (single-digit hours occur).
- T2 inspection: 149,499 sorted unique timestamps, 2023-03-11 00:00 through 2026-01-31 23:50; no missing/nonfinite numeric values. Wind 0.11–21.43 m/s; power 0–1; temperature −19.08–43.97 °C. There are 2,853 missing ten-minute slots on the naive source clock.
- For T2 before timezone conversion there are 24,785 complete six-sample hours and 219 partially populated hours. These are input audit counts, not promised post-timezone/training counts. Convert using §2; require all six distinct ten-minute starts for each UTC hour, then arithmetic-mean all three measurements. Drop/report incomplete hours; do not fill outages or remove zero-power observations. Apply the completed-hour cutoff before fitting.
- Write generated `data/canonical/history.csv`; reserve `data/canonical/truth.csv` for separately supplied February targets. No February weather observations or labels feed model training, model selection, or inference. Supplied filenames overstate their actual date coverage.
- T1 is now available as a distinct file. Run the same audited ingestion pipeline separately for both turbines; no farm-total aggregation without capacity metadata.

**Canonical files (UTF-8 CSV, decimal points, explicit UTC ISO timestamps):**

```text
sites.csv: turbine_id,latitude,longitude,timezone
T2,0.0,0.0,Asia/Almaty                 # example only; fictional fixture site
history.csv: turbine_id,timestamp,wind_speed_ms,temperature_c,power_norm
T2,2026-01-31T16:00:00Z,6.2,-4.0,0.31
weather.csv: turbine_id,run_id,initialized_at,available_at,valid_at,wind_speed_ms,temperature_c
T2,fixture-r1,2026-01-31T06:00:00Z,2026-01-31T14:00:00Z,2026-01-31T19:00:00Z,7.2,-5.0
```

Comments above are explanatory, not literal CSV contents. Sites unique by turbine; history unique by `(turbine_id,timestamp)`; weather unique by `(turbine_id,run_id,valid_at)`. `timestamp`/`valid_at` mean hourly interval start. Missing required values reject a forecast; invalid training rows are excluded and counted. Use the six-sample hourly aggregation policy above. Mixed/unknown units stop real ingestion.

Each weather run has a manifest object (bundled with rows in `fixtures/T1-r1.json` etc. in the slice): `run_id`, `provider`, `source_url`, `retrieved_at`, `initialized_at`, `available_at`, `availability_basis`, `provenance_status` (`verified|unverified|fixture`), `raw_sha256`, `interpolation` (`none|linear_3h_to_1h`). Preserve raw response and source metadata. Retrieval time is not historical availability. Cache key includes coordinates, source run, variables, and interpolation policy.

**Public Python interfaces, defined in `contracts.py`:**

```python
fetch_weather(site: dict, origin: str, horizon_hours: int, mode: str) -> dict
# {"manifest": {...}, "rows": [{"valid_at": ..., "wind_speed_ms": ..., "temperature_c": ...}]}
train_model(history: pandas.DataFrame, origin: str, turbine_id: str) -> object
predict_power(model: object, weather_rows: list[dict]) -> list[float]
summarize_forecast(result: dict, backend: str = "template") -> dict
run_forecast(request: dict) -> dict
replay_month(mode: str, output_path: str) -> dict
```

**Map boundary:** UI resolves marker identity to `turbine_id` from `weather.load_sites()`; the slice uses an explicit fixture registry, while verified archive sites will come from `config/sites.csv`; requests never accept arbitrary client-supplied coordinates. Background clicks do nothing; unsupported sites disable Predict generation; a missing artifact returns MODEL_UNAVAILABLE with the training command. The fixture T2 coordinate is a labeled placeholder, not a claim about the real site. Use `st_folium`'s marker event (`last_object_clicked`) matched to a configured marker, not general `last_clicked`; keep a synchronized selectbox as the asset/network fallback. Map pan/zoom must not invoke forecast or reset the selected date. Resolve authoritative coordinates once in config, not through a geocoder per click.

**Explanation boundary:** `summarize_forecast` returns `{"text":"...","backend":"template","forecast_fingerprint":"sha256:...","warning":null}`. On missing credentials/timeout/provider error in LLM mode, return template text with an explanatory `warning`; leave the forecast successful. Template is 2–3 sentences derived from peak/minimum/times/warnings in `analysis`; format times in site timezone and explicitly name normalized units and synthetic weather where applicable. For ties choose earliest hour. LLM mode may paraphrase those facts in ≤100 words, without new numbers, causal claims, or confidence estimates. One Responses API call with `max_output_tokens=300`, `reasoning={"effort":"none"}`, timeout=8 seconds, retries disabled; use `response.output_text`, falling back on empty/incomplete output. Keep the key server-side; future React code never receives it. Optional chat later receives only the current result and question; out-of-context questions get a clear limitation. Changing forecast invalidates prior explanation/chat context.

Internally pass the weather tool as a dependency for testing; UI calls `run_forecast` and then `summarize_forecast`, with no model or weather imports. Model identity hashes training rows, feature order, parameters, and cutoff. Result fingerprint hashes request, model identity, and normalized weather/manifest content. Same fingerprint reuses result; changed eligible weather recomputes. Each call still checks eligible weather metadata. Force refresh bypasses transport cache, never eligibility rules.

**Request:**

```json
{"turbine_id":"T2","origin":"2026-01-31T18:00:00Z","horizon_hours":48,"mode":"fixture"}
```

**Success result shape** (one illustrative row shown; actual `hours` length equals horizon):

```json
{
  "status":"ok","mode":"fixture","turbine_id":"T2",
  "origin":"2026-01-31T18:00:00Z","horizon_hours":48,"timezone":"Asia/Almaty",
  "run_id":"fixture-r1","model_id":"sha256:...","fingerprint":"sha256:...",
  "cache_hit":false,"train_last_interval_start":"2026-01-31T16:00:00Z",
  "weather_provenance":{"initialized_at":"2026-01-31T06:00:00Z","available_at":"2026-01-31T14:00:00Z","source_url":"fixture://r1","availability_basis":"synthetic","provenance_status":"fixture"},
  "hours":[{"valid_at":"2026-01-31T19:00:00Z","lead_hour":1,"power_norm":0.42,"baseline_norm":0.31,"wind_speed_ms":7.2,"temperature_c":-5.0}],
  "analysis":{"peak_power_norm":0.42,"peak_at":"2026-01-31T19:00:00Z","min_power_norm":0.12,"min_at":"2026-02-01T02:00:00Z","clipped_count":0,"warnings":["Real turbine training data; synthetic weather", "Timezone and interval semantics assumed"]},
  "trace":[{"step":"fetch_weather","status":"ok","detail":"fixture-r1 selected"}]
}
```

Analysis values above are illustrative; calculate them over the full response. Include `timezone` in the success result, resolved from the site; explanation/display use it rather than guessing from UTC. Trace includes every executed step and reasons for selection/retry/cache reuse. Error shape: `{"status":"error","code":"WEATHER_UNAVAILABLE","message":"...","trace":[]}`; codes also `INVALID_INPUT`, `DATA_INVALID`, `MODEL_UNAVAILABLE`. Fetch timeout 10 seconds, one retry; then eligible verified cache or explicit error. Reject future availability, duplicate/missing hours, nonfinite features, unknown sites, horizons other than 24/48. Do not invent weather on failure.

**Forecast CSV:** `turbine_id,origin,valid_at,lead_hour,power_norm,baseline_norm,run_id,model_id,mode,provenance_status`. All normalized values remain fractions. Replay returns `expected_rows,actual_rows,missing_origins,provenance_status,mae_1_24,mae_25_48`; MAEs are null without truth, alongside scored row counts. Requested two-site replay: 28 × 2 × 48 = 2,688 rows including March spillover; February-only lead-1–24 coverage is 1,344 rows. Per turbine, the full replay yields 1,344 rows and 672 February lead-1–24 rows. The first slice covers only two fixture origins, not the full replay. Include `missing_sites` in the replay summary and keep `expected_rows=2688` for the requested scope. Report metrics per turbine; truth joins by turbine/time after forecasting, in replay only.

## 10. Repository Structure

```text
PLAN.md                     # frozen planning artifact
README.md                   # A: setup, provenance, replay, limitations
requirements.txt            # A: shared dependency changes
.gitignore                  # A: environments/raw data/artifacts
contracts.py                # A: frozen boundary types/validation
app.py                      # C: Streamlit map and UI
explanation.py              # C: template now, bounded LLM later
agent.py                    # A: orchestration/cache/errors
weather.py                  # A: real and fixture weather adapters
model.py                    # B: training/features/prediction
data.py                     # B: canonical ingestion
replay.py                   # B: batch replay/metrics CLI
scripts/make_fixtures.py     # A: synthetic weather and small test inputs
scripts/train.py            # B: training CLI
scripts/prefetch.py          # A: archived weather retrieval CLI
config/sites.csv            # A: confirmed site metadata
fixtures/                   # A: tiny distributable synthetic inputs
data/                       # supplied originals/brief; generated canonical/weather files ignored
artifacts/                  # local models/results; ignored
tests/                      # agent A; data/model B; UI/explanation C
```

Keep modules flat. Preserve supplied files in place; do not blanket-ignore or remove the organizer brief. Share redistribution-safe caches only; if raw data cannot be committed, README documents placement and hashes.

## 11. Team Ownership

| Person | OWNS / SAFE TO MODIFY | SHOULD AVOID MODIFYING | FIRST TASK AFTER SLICE | DEPENDS ON |
|---|---|---|---|---|
| A: integration/weather | agent.py, weather.py, contracts.py, config, scripts/prefetch.py, README, dependencies | B/C modules except agreed integration fixes | Verify archive gate and coordinates; prefetch verified runs | Organizer coordinates; accessible operational archive |
| B: data/model/replay | data.py, model.py, replay.py, scripts/train.py, test_model.py | UI, agent, weather schemas | Review both-turbine aggregation/time assumptions; improve model; January holdout vs persistence; both-turbine replay | Raw measurements; frozen weather contract; A's caches |
| C: UI/explanation/demo | app.py, explanation.py, test_ui.py, test_explanation.py, presentation notes | Model, weather, agent, shared contracts/dependencies | Polish marker selection; add bounded LLM explanation/fallback; render provenance and replay coverage | Slice contracts; summary API key for LLM only |

Each human may use their coding agent within their files. UltraCode first creates the shared slice; then hands it off. A alone integrates shared changes. Preserve UI→agent and UI→explanation boundaries so A replaces weather/adds a thin API, B improves ingestion/model/replay, and C builds the frontend/explanation concurrently. No shared-file redesign after the handoff without coordination.

**Clock from hackathon start:** 0:00–0:25 architecture; 0:25–1:15 slice (humans validate data/archive in parallel); 1:15–3:15 streams above; 3:15–4:00 integrate real inputs and complete replay; 4:00–4:30 clean-launch checks and README; 4:30–5:00 freeze and rehearse. If archive retrieval fails, state the unmet requirement early and prioritize organizer-provided as-issued files over new features.

## 12. Critical Risks and Fallbacks

| RISK / WHY IT MATTERS | FASTEST VALIDATION (first hour) | FALLBACK |
|---|---|---|
| As-issued archive inaccessible or unverifiable; core compliance fails | Retrieve one operational run and prove run/availability/coverage; test NCSS and units | Organizer-provided verified as-issued cache via same schema; fixture demo remains explicitly incomplete if unavailable |
| Turbine identity and unknown timezone; fake two-site coverage or time misalignment | Verify file hashes; confirm distinct data and timestamp convention; resolve map links | Use separate real datasets with explicit time assumptions; never duplicate a turbine to claim coverage |
| Measured-to-forecast feature mismatch; weak accuracy | January time-split holdout, then small archived-weather overlap if available | Binned measured wind-to-power curve with training median temperature fallback only during training; keep same prediction interface and label model change; no accuracy claim without evidence |
| Weather/map/LLM network failure or latency; demo stalls | Time one point fetch; test marker click; try summary key once after slice | Verified weather cache; synchronized site selector if map assets fail; template if LLM fails; each fallback labeled |
| Integration/reproducibility drift; judging loses 25 points | Fresh venv + fixture smoke test before stream split | Local single-process demo and frozen dependencies; stop optional features |

Fallback model is attempted only if the selected regressor fails validation or cannot fit; missing inference weather always fails. January measured-feature validation is a model diagnostic, not proof of February forecast accuracy.

## 13. First Vertical Slice — Implementation Brief

### Goal

UltraCode: build the first runnable slice of the agreed map → weather → power forecast → explanation demo. Use real T1/T2 history and a genuinely fitted model, with synthetic weather and a computed summary. Deliver working code and a clean handoff for three parallel streams. Execute this plan; do not redesign it or expand scope into the full hackathon submission.

### Build

1. Inspect the repo and any AGENTS.md before edits; preserve supplied originals and existing work. Use Python 3.12+, one Streamlit process, flat modules, local artifacts. Create the slice files listed below and freeze §9 contracts before writing consumers.
2. Parse both exact CSV filenames and headers from §9; ignore suffixed duplicates. Convert the explicitly assumed timezone, audit ambiguous timestamps, require six ten-minute samples per hour, and average the three measurements. Save canonical data and an ingestion audit with source hash, date range, dropped hours, and time assumptions. Never create a T1 model from T2 data.
3. Implement `train_model`/`predict_power` with the selected regressor and features. Fit only completed hours before the first origin, save an artifact/metadata, and load it for UI requests. Do not fit again on Streamlit reruns. Baseline uses the last eligible pre-test observation.
4. Generate two deterministic synthetic weather runs per turbine covering the two demo origins, with distinct values on overlapping timestamps and manifests. Keep seed fixed. Supply an explicitly fictional coordinate if real map coordinates remain unresolved; use separate fixture config. Synthetic weather must not derive from future measured weather. Weather adapter validates availability/coverage and returns the frozen bundle. Archive mode returns a useful WEATHER_UNAVAILABLE error until A implements it.
5. Implement `run_forecast`: request validation → eligible weather → feature validation → prediction → peak/minimum/bounds checks → result/trace. Build content fingerprints from normalized weather, request, and model identity. Use deterministic JSON serialization and exclude retrieval wall-clock time from content identity. Repeated identical inputs reuse computation; a new eligible weather input recomputes. Emit traces from actual execution, not canned success strings.
6. Implement `summarize_forecast` in template mode using computed peak/minimum/times and provenance. It must produce useful text from any valid result, not a hardcoded demo paragraph. Leave the LLM implementation behind this boundary for C; `backend=llm` in the slice falls back explicitly to template with a warning. No SDK/key needed yet.
7. Implement the Folium map in Streamlit with clickable T1/T2 markers, synchronized fallback site selector, origin and 24/48-hour controls. Start with no selected site; enable Predict generation after valid selection. Clicks on the background cannot change site identity. Show active site and coordinate provenance. Use session state/stable component key so map redraws preserve inputs and do not start work.
8. On Predict generation, display the chart/table, baseline, weather inputs, source/run times, trace, units, fixture label and CSV download, then call the summary adapter. On Advance one day, update origin and rerun; compare overlapping hours. Clear or visibly mark old output stale as soon as request controls change; never show old results as current success.
9. Add focused tests, run them, start the app, and exercise both demo runs. Document exact setup commands and any browser verification that could not be performed. Update README with limitations and A/B/C handoff. Stop after the slice; do not implement full archive retrieval, replay, or chat.

### Do Not Build

No separate API/backend service, React, live weather vendor integration, arbitrary-location forecasts, LLM call, chat, cloud deployment, database, agent hierarchy, actual-weather substitute for archived forecasts, February training, fake T1, fabricated accuracy, or hidden fallback. Do not add success-returning placeholders for replay/prefetch.

### Required Contracts

Implement §9 verbatim, including template summary response and site-identity mapping. Keep `app.py` free of weather/model logic; no core module imports Streamlit. A later React/FastAPI migration replaces the UI and wraps existing functions, without changing these contracts. Keep `explanation.py` free of prediction/retrieval logic. Pure helpers and dependency injection for tests are fine; avoid plugin systems and generic frameworks. Preserve file ownership in §11 for handoff.

### Required Files

`requirements.txt`, `.gitignore`, `contracts.py`, `app.py`, `agent.py`, `weather.py`, `model.py`, `data.py`, `explanation.py`, `scripts/make_fixtures.py`, `scripts/train.py`, focused tests, and updated `README.md`. Include `scripts/__init__.py` for CLI module invocation. Generate weather JSON bundles (manifest plus rows) and small test-only measurement data; fixture sites are defined in weather.py. Generate `data/canonical/history.csv`, ingestion audit, and model artifacts; ignore generated artifacts. Existing supplied files stay untouched. The later owners add `replay.py`, `scripts/prefetch.py`, and confirmed real-site config; do not require those for startup.

### Acceptance Tests

- From repository root: `python -m venv .venv` with Python 3.12+, activate it, then `python -m pip install -r requirements.txt`. The current slice is verified on Python 3.14.4; the pinned NumPy requires Python 3.12+.
- `python -m scripts.make_fixtures`; `python -m scripts.train --mode fixture`; `DATA_MODE=fixture SUMMARY_BACKEND=template python -m streamlit run app.py`. Open `http://localhost:8501`; no external weather/LLM credentials required.
- UI: initially no prediction; click T2 marker, choose `2026-01-31T18:00:00Z` (23:00 local), horizon 48, and Predict generation. Real weather-tool invocation is recorded; result has exactly 48 unique next-hour rows with finite values in [0,1]. Chart/table/CSV agree; explanation matches computed peak/minimum; provenance identifies real training and synthetic weather.
- Repeat unchanged input: same forecast fingerprint/numbers, cache hit. Advance one day: new run/fingerprint, changed overlap, new explanation fingerprint. Pan map: no forecast invocation. Background click: no invented site. Both T1/T2 requests succeed with distinct model identities; unknown-site requests fail.
- `python -m pytest -q`: real-file ingestion mapping and duplicate-copy exclusion; six-sample aggregation; completed-hour and February leakage guards; weather availability and missing-hour rejection; model output/24–48 shape; fingerprint invalidation; summary facts and fallback. Use tiny deterministic inputs for failure cases rather than brittle assertions about exact learned predictions.
- Inject weather failure: explicit error, no archive→fixture fallback and no stale successful result. Summary failure cannot discard a valid forecast. With map tiles unavailable, site selector still completes the flow and displays coordinates.
- Record actual test results and unresolved real-coordinate/timezone/archive items in README. Acceptance requires the two demo runs, not merely importable files.

### Handoff / Stop Condition

After tests and smoke run, summarize commands, working behavior, actual test evidence, and known stubs. Point A to weather/agent/contracts, B to data/model/replay, and C to app/explanation. List frozen request/result/tool contracts and shared dependency coordination. Do not start those later streams yourself unless the user asks.

## 14. Definition of Done

**Slice complete:** implemented with real separately trained T1/T2 models, four synthetic weather bundles, map/UI, computed analysis, and export. Verification and commands are recorded in README; later streams work against §9.

**Hackathon MVP complete (still requires verified archived weather and full replay):** actual two-site data loaded; verified operational forecasts acquired automatically by coordinates or replayed from their documented cache; completed-interval cutoff and availability checks enforced; both turbines replayed for all 28 origins; 2,688 forecast rows exported with provenance; February coverage checked; optional truth metrics honestly labeled; marker selection, explanation, and demo update work; LLM explanation demonstrated or template-only limitation explicitly recorded; fresh-start README includes data placement, normalization/timezone assumptions, source attribution, limitations, and commands below.

Final commands after their owners implement them: `python -m scripts.train --mode archive`; `python -m scripts.prefetch --month 2026-02`; `python -m replay --mode archive --month 2026-02 --output artifacts/february.csv`; `DATA_MODE=archive python -m streamlit run app.py`.

**Not complete:** fixture-only output, hindcasts/reanalysis presented as historical forecasts, assumed publication times presented as verified, missing origins hidden, or test-period labels entering training. If blocked, demonstrate the working slice and list the exact unmet requirement rather than claiming compliance.
