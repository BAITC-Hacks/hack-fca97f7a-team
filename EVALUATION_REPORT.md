# Chronological model diagnostic

The retained model is a separate `HistGradientBoostingRegressor` for T1 and T2,
using hourly mean wind speed and air temperature to predict normalized hourly
power in [0, 1]. The MLmodel and main branches already used the **same regressor,
feature pair, and hyperparameters** (`max_iter=100`, `max_leaf_nodes=15`,
`random_state=42`). Their artifact validation and inference boundaries differed;
there is no evidence of a distinct MLmodel regressor outperforming main.
No hyperparameters were changed after seeing these results.

The measured-weather diagnostic favors retaining this HGB recipe over a simple
persistence baseline for the current demo. **It does not establish 24/48-hour
forecast accuracy:** each predicted target hour uses wind and temperature
measured during that same future hour. A real forecast will use weather issued
at or before its origin, with different measurement height and error. Verified
as-issued archived weather and February power truth are unavailable.

## Protocol

- Ingest the distinct supplied T1/T2 CSVs, assume ten-minute timestamps are
  interval starts in Asia/Almaty, convert to UTC, and retain only complete hours
  with six distinct samples. The source audit found 142,360 T1 rows (23,666
  complete hours) and 149,499 T2 rows (24,784 complete hours). Source SHA-256:
  T1 `c4c341582fb2dd348b7187f0128cff265fe055f469413871ebb5db50eef58b5b`,
  T2 `820578cd18bb557cd30c2e102f3ae5a386dfc6c489a5a15743339c2b017305e5`.
- Development check: fit on observations completed by **2025-12-01 00:00 UTC**;
  score daily origins in December. Fixed January test: refit the same recipe on
  observations completed by **2026-01-01 00:00 UTC**; score daily origins from
  January 1 through January 30 (24h) or January 29 (48h). Every scored target
  interval ends by the frozen **2026-01-31 18:00 UTC** limit. These January
  scores were previously inspected in a simpler local diagnostic; this protocol
  was fixed without tuning the model to them, but they are not pristine unseen
  evidence.
- At each origin, the baseline holds the most recent **completed** observed
  power hour constant across that origin's 24 or 48 leads. Its maximum age was
  zero hours in January. The HGB is held fixed within each period, while the
  baseline refreshes at each daily origin. Missing complete-hour truth is
  excluded and counted. The 48h daily windows overlap, so metrics are over
  origin–lead pairs rather than independent target hours; the machine report
  includes unique target counts.
- MAE and RMSE are absolute normalized-power units. R² is relative to the mean
  of the scored truth and can be negative. F1 applies to classification, so it
  is not an appropriate score for this continuous output. Prediction values
  are clipped to [0, 1] as in the app; no evaluated prediction required clipping.

## Results

| Period | Turbine | Horizon | Scored / missing pairs | HGB MAE | HGB RMSE | HGB R² | Baseline MAE | Baseline RMSE | Baseline R² |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| December development | T1 | 24h | 716 / 4 | 0.0285 | 0.0550 | 0.9793 | 0.3357 | 0.4601 | -0.4490 |
| December development | T1 | 48h | 1,384 / 8 | 0.0289 | 0.0557 | 0.9786 | 0.3578 | 0.4729 | -0.5392 |
| December development | T2 | 24h | 710 / 10 | 0.0319 | 0.0840 | 0.9509 | 0.3363 | 0.4619 | -0.4845 |
| December development | T2 | 48h | 1,372 / 20 | 0.0323 | 0.0852 | 0.9492 | 0.3632 | 0.4786 | -0.6060 |
| January test | T1 | 24h | 720 / 0 | 0.0237 | 0.0483 | 0.9788 | 0.3296 | 0.4461 | -0.8031 |
| January test | T1 | 48h | 1,392 / 0 | 0.0239 | 0.0490 | 0.9780 | 0.3521 | 0.4634 | -0.9657 |
| January test | T2 | 24h | 720 / 0 | 0.0259 | 0.0627 | 0.9643 | 0.3281 | 0.4429 | -0.7856 |
| January test | T2 | 48h | 1,392 / 0 | 0.0262 | 0.0636 | 0.9627 | 0.3441 | 0.4561 | -0.9179 |

The January 48h HGB MAE is 0.0239 for T1 and 0.0262 for T2, versus 0.3521
and 0.3441 for origin-refreshed persistence. This large gap mainly shows that
same-hour measured wind and temperature explain measured power much better than
holding the origin value constant. It cannot be converted into an expected
advantage for a real weather forecast. The deployed models are later refits
through the January 31 cutoff; testing those on January would leak targets, so
this report tests the same fitting recipe trained only through January 1.

## Reproduce and inspect

From the repository root, after installing `requirements.txt`:

```sh
MPLCONFIGDIR=/private/tmp/matplotlib-eval python -m scripts.evaluate
python -m pytest -q tests/test_evaluation.py
```

The CLI writes `artifacts/evaluation/report.json`, eight point-level CSVs with
origin, target, lead, measured features, truth, HGB prediction, persistence value
and baseline observation time, plus representative 48h January plots for
[`T1`](artifacts/evaluation/T1_january_48h_example.png) and
[`T2`](artifacts/evaluation/T2_january_48h_example.png) in PNG and SVG. Generated
files are ignored by Git; rerun the command to create these links locally. The
plots show January 1 origins, chosen for complete 48h observed coverage. They
illustrate the measured-weather diagnostic and are not issued forecasts.
