# Wind power forecast demo

A working first vertical slice: select **T1 or T2** on a map, generate 24/48 hourly
power predictions, inspect weather/output, read computed analysis, download CSV,
and advance the forecast origin to compare an updated run.

**Real:** supplied turbine measurements, audited hourly aggregation, two fitted
scikit-learn regressors, prediction, validation, cache, trace, analysis and exports.
**Stubbed:** weather forecasts, map coordinates and LLM prose. Weather and location
are visibly labeled fictional. The explanation is a deterministic summary of
computed facts. This is not yet the complete organizer submission.

## Run

Python **3.12+** (verified on 3.14.4). No weather or LLM API keys needed.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m scripts.make_fixtures
python -m scripts.train --mode fixture
python -m streamlit run app.py
```

Open http://localhost:8501. Select **T2**, leave **January 31, 2026 / 48 hours**, and
click **Predict generation**. Read the chart/table and analysis, download CSV,
then click **Advance one day**. The 24 overlapping forecast hours are compared.
T1 works through the same flow using its own measurements/model. The selector
also works if external map assets cannot load.

Only January 31 and February 1 at 23:00 local have synthetic runs in this slice.
Other dates return `WEATHER_UNAVAILABLE`; they do not invent weather. Changing
site/date/horizon hides the old result until the next successful calculation.

Training is a separate command, never repeated by a UI rerun. Generated files
live under `data/canonical/` and `artifacts/` and are ignored by Git. The small
synthetic weather bundles under `fixtures/` are committed and regenerable.

## Data and assumptions

The supplied CSVs and organizer brief are in `data/` and remain unchanged.
T1 has **142,360** records; T2 has **149,499**. They are distinct files. Both end
January 31, 2026; neither contains February truth despite their filenames.

Source times are assumed ten-minute interval starts in `Asia/Almaty`. Six complete
samples form each UTC hour; incomplete hours are excluded, not filled. Six
ambiguous local timestamps per turbine are excluded at the 2024 clock change.
The source timezone/interval convention still needs organizer confirmation.

| Turbine | Complete hourly observations | Training hours before frozen cutoff |
|---|---:|---:|
| T1 | 23,666 | 23,665 |
| T2 | 24,784 | 24,783 |

The first origin is `2026-01-31T18:00:00Z` (23:00 local). Training includes only
completed hours ending at or before it; the last training interval starts at
17:00 UTC. Targets begin at origin+1 hour, which is February 1 midnight local.
Models stay frozen for the second origin. February measurements never enter
fitting or inference. Audits include source hashes and exclusion counts in
`data/canonical/ingestion_audit.json`; model metadata is in `artifacts/models/`.

Output is **normalized power in [0,1]**, not MW/MWh. Capacity and normalization
denominator are unknown. No farm total, calibrated uncertainty, or accuracy
claim is made. The baseline repeats the last eligible pre-test observation.

## Boundaries for parallel work

```text
Streamlit map/controls
    → agent.run_forecast(request)
        → registered site → weather.fetch_weather(...)
        → chronology/coverage/features → model.predict_power(...)
        → analysis + trace + JSON result
    → explanation.summarize_forecast(result)
    → chart / table / CSV
```

No core module imports Streamlit. A later FastAPI adapter can wrap the same
functions; React can replace `app.py` without rewriting forecasting.

| Owner | Files | Next task |
|---|---|---|
| A — integration/weather | `agent.py`, `weather.py`, `contracts.py`, fixtures/config, dependencies | Verify real coordinates and as-issued weather archive; add thin HTTP endpoints for the new frontend |
| B — data/model | `data.py`, `model.py`, `scripts/train.py`, associated tests | Confirm source semantics; chronological validation; full February replay |
| C — frontend/explanation | `app.py`, `explanation.py`, UI/summary tests | React presentation and bounded OpenAI explanation; scoped follow-up questions later |

Coordinate shared contract/dependency changes through A. See [AGENTS.md](AGENTS.md)
for the working agreement and [PLAN.md](PLAN.md) for frozen schemas and scope.

## Configuration and stubs

- `DATA_MODE=fixture` (default). `archive` explicitly reports unavailable until
  verified coordinates and archived forecasts are integrated.
- `SUMMARY_BACKEND=template` (default). `llm` currently returns a labeled template
  fallback. No paid model API is called and no credits are consumed.
- `DATA_DIR`, `ARTIFACT_DIR`, `FIXTURE_DIR` can override the local paths.
- Future OpenAI credentials use server-side `OPENAI_API_KEY` and
  `OPENAI_MODEL=gpt-5.4-mini`; never put a key in frontend code. NVIDIA is reserved.
- Real archive inputs must prove initialization ≤ availability ≤ forecast origin,
  and cover every target hour. Reanalysis or realized weather is not a substitute.
- Map markers at `(0,0)` and `(0,0.03)` are intentionally fictional fixtures;
  real sites are not inferred from these coordinates.
- Full February replay, free-text questions, live APIs and React/FastAPI are not
  implemented. No success-returning placeholder scripts are provided.

## Verification

After fixture generation and training:

```sh
python -m pytest -q
```

Current result: **26 tests pass**, covering data identities/aggregation/timezone,
training cutoff and future-data isolation, weather chronology/coverage, cache
invalidation, forecast bounds, summary fallback, marker identity, and stale UI
results. Streamlit AppTest simulates UI events; it does not execute Leaflet JS.

Real Chromium checks additionally verified selector-driven forecast generation,
CSV download and next-day overlap comparison without JavaScript page errors.
Playwright was used only as a development verification tool; it is not in the
application requirements and is not needed to launch the demo.
