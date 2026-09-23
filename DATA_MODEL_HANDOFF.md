# Data and model handoff

The active React + FastAPI application and its exact routes, DTOs, CSV schema and
Python interfaces are documented in [CONTRACTS.md](CONTRACTS.md). This handoff
records the measured data audit and the feature agreement needed by the weather
and model streams. It does not establish access to operational weather archives.

## Source audit

`data.py` selects the two exact supplied filenames, separately identifies T1/T2,
and rejects identical source files. Supplied CSVs and the organizer brief are
unchanged. The source filename says February 2026, but both files end at local
`2026-01-31 23:50:00`; neither contains a February 2026 row.

| Turbine | Source rows | SHA-256 | Ambiguous / nonexistent clock rows | Missing ten-minute slots across source span | Incomplete / empty hours | Complete UTC hours | Frozen training hours |
|---|---:|---|---:|---:|---:|---:|---:|
| T1 | 142,360 | `c4c341582fb2dd348b7187f0128cff265fe055f469413871ebb5db50eef58b5b` | 6 / 0 | 10,004 | 96 / 1,631 | 23,666 | 23,665 |
| T2 | 149,499 | `820578cd18bb557cd30c2e102f3ae5a386dfc6c489a5a15743339c2b017305e5` | 6 / 0 | 2,865 | 219 / 390 | 24,784 | 24,783 |

The audit assumes source timestamps mark ten-minute interval **starts** in
`Asia/Almaty`; that convention has not been confirmed by the data provider.
Ambiguous or nonexistent local clocks are excluded before UTC conversion.
Each retained UTC hour averages six distinct ten-minute samples of wind speed,
temperature and normalized power. Incomplete hours are excluded, including
hours affected by outages; zero-power samples remain. `missing_ten_minute_slots`
counts gaps from the first to last retained UTC slot, including excluded clock
rows, while `empty_hours` counts hours with no retained slot. The sources have
no invalid timestamp, off-grid or numeric rows beyond the six ambiguous rows
per turbine. The generated audit is `data/canonical/ingestion_audit.json`.

The frozen first origin is `2026-01-31T18:00:00Z`. A training hour qualifies
only when its end is at or before that origin; the last included interval starts
at 17:00 UTC. The local files end at 23:50 Asia/Almaty (18:50 UTC), so their
final 18:00 UTC hour is excluded from both models. February targets and measured
February weather never enter training. No February truth is available for scoring.

An isolated `python -m scripts.train --mode fixture` run reproduced both model
IDs: T1 `sha256:4bc8c75b20c024fbd6b50eb7a9f9bfdfe603a87c9f6bea97bb47e623c43e58b8`
and T2 `sha256:50af7fceacac388e91d7339662de578e9a785d16efddfb64f69b166923fc1a9b`.
Both last included interval starts are `2026-01-31T17:00:00Z`. Versioned model
metadata records source/canonical/artifact hashes, feature names and units,
training cutoff, parameters and Python/scikit-learn versions. Eight FastAPI
fixture requests (two turbines × two origins × 24/48 hours) succeeded while
consuming the exact downloadable input CSV, with zero clipped values.

## Feature and inference agreement

| Field | Training source | Prediction CSV | Status |
|---|---|---|---|
| `wind_speed_ms` | Source `Средняя скорость ветра(m/s)`, averaged over a complete hour | `weather.fetch_weather` normalized m/s | Unit and order match; measured height and future provider target height remain unconfirmed. |
| `temperature_c` | Source `Средняя температура окружающей среды(°C)`, averaged over a complete hour | Weather adapter normalized °C | Unit and order match; sensor and provider representativeness remain unconfirmed. |
| `valid_at` / `timestamp` | UTC start of a complete measurement hour | UTC start of forecast hour, from origin+1h through origin+24/48h | Timestamp convention is implemented; source interval semantics remain an assumption. |
| `power_norm` | Source normalized active power, averaged over a complete hour | Output in [0,1] | Capacity and normalization denominator are unknown; no MW/MWh conversion or farm total. |

The canonical inference CSV is version `weather-features-v1` with columns
`turbine_id,valid_at,wind_speed_ms,temperature_c`. `model_input.py` writes the
content-addressed CSV and `model.predict_power_csv` reads and validates the exact
bytes before inference. The model expects `[wind_speed_ms, temperature_c]` in that
order. No target column enters the CSV. `weather.py` currently serves explicitly
synthetic fixtures and fictional coordinates `(0,0)` and `(0,0.03)`; it does not
declare wind height, a real provider, or as-issued availability. In particular,
there is **no justified wind-height conversion** at this stage. A future provider
must document its target height, interpolation and available-at evidence before
claiming physical alignment with the measured feature or archive readiness.

The model was fit on measured weather but is asked to predict from forecast
weather. This domain shift has not been measured. Any chronological holdout
using measured features evaluates the regression fit under measured inputs; it
is not accuracy of the end-to-end weather forecast. No weather archive, February
replay or February truth is present, so forecast accuracy is unclaimed.

A reproducible chronological diagnostic is in
[EVALUATION_REPORT.md](EVALUATION_REPORT.md). On January 24/48-hour windows,
the HGB models scored T1 MAE 0.0237/0.0239 and RMSE 0.0483/0.0490; T2 MAE
0.0259/0.0262 and RMSE 0.0627/0.0636. R² was 0.9788/0.9780 for T1 and
0.9643/0.9627 for T2. The corresponding origin-refreshed persistence MAE was
0.3296/0.3521 for T1 and 0.3281/0.3441 for T2. These are normalized-power
units using **same-future-hour measured wind and temperature**, not weather
available at a real forecast origin. The two branches used the same HGB recipe;
the integration retained a compatible versioned artifact format and CSV boundary,
without a claim that one branch's regressor is numerically superior.

## Reproduction and next work

From the repository root with Python 3.12+ and Node 22+:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m scripts.make_fixtures
python -m scripts.train --mode fixture
python -m scripts.evaluate --output-dir artifacts/evaluation
python -m pytest -q
npm --prefix frontend ci
npm --prefix frontend run build
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Generated canonical history/audits live in ignored `data/canonical/`; fitted
models, model-input CSVs and evaluation outputs live in ignored `artifacts/`.
The chronological measured-weather scores and example plots are described in
[EVALUATION_REPORT.md](EVALUATION_REPORT.md). Stream A must verify
site coordinates, wind variable height and actual as-issued weather availability
before implementing an archive adapter. Stream B should keep the frozen cutoff
and measured-weather baseline, then add full February replay
only after verified archives arrive. Stream C should retain Russian labels for
fixture weather, fictional coordinates, normalized power and explanation backend.
The fixture demo works locally but does not satisfy full organizer replay scope.
