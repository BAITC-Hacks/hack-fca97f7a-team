"""Chronological measured-weather diagnostics for the two turbine regressors.

The future-hour features here are observed SCADA measurements. These numbers are
not an as-issued weather-forecast backtest or February forecast accuracy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from backend.core.contracts import FEATURES, FIRST_ORIGIN, SITE_IDS
from backend.ml.data import ingest_all
from backend.ml.model import _PARAMETERS as MODEL_PARAMETERS, _raw_predictions, train_model


PERIODS = {
    "development": ("2025-12-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    "january_test": ("2026-01-01T00:00:00Z", FIRST_ORIGIN),
}
HORIZONS = (24, 48)


def _iso(value: pd.Timestamp) -> str:
    return value.isoformat().replace("+00:00", "Z")


def latest_completed_power(site_history: pd.DataFrame, origin: pd.Timestamp) -> tuple[float, pd.Timestamp]:
    """Find the latest observation available when a forecast is issued."""
    eligible = site_history.loc[site_history["timestamp"] + pd.Timedelta(hours=1) <= origin]
    if eligible.empty:
        raise ValueError(f"No completed power observation at {_iso(origin)}")
    last = eligible.iloc[-1]
    return float(last["power_norm"]), last["timestamp"]


def score(predicted: np.ndarray, truth: np.ndarray) -> dict:
    """R² uses the observed target mean; constant targets have undefined R²."""
    if len(truth) == 0 or predicted.shape != truth.shape:
        raise ValueError("Scoring requires paired nonempty prediction and truth arrays")
    errors = predicted - truth
    denominator = float(np.sum((truth - np.mean(truth)) ** 2))
    return {
        "mae": float(np.mean(np.abs(errors))),
        "rmse": float(np.sqrt(np.mean(errors ** 2))),
        "r2": float(1 - np.sum(errors ** 2) / denominator) if denominator > 0 else None,
    }


def evaluate_window(
    site_history: pd.DataFrame,
    model: object,
    origin: pd.Timestamp,
    horizon: int,
    *,
    predictor=_raw_predictions,
) -> tuple[list[dict], int, int]:
    """Score available target hours and count missing complete-hour truth."""
    baseline, baseline_at = latest_completed_power(site_history, origin)
    indexed = site_history.set_index("timestamp")
    valid_hours = [origin + pd.Timedelta(hours=lead) for lead in range(1, horizon + 1)]
    available = [stamp for stamp in valid_hours if stamp in indexed.index]
    if not available:
        return [], horizon, 0
    target = indexed.loc[available]
    weather_rows = target[list(FEATURES)].to_dict("records")
    raw = np.asarray(predictor(model, weather_rows), dtype=float)
    if raw.shape != (len(target),) or not np.isfinite(raw).all():
        raise ValueError("Predictor returned missing, nonfinite or misaligned values")
    clipped = int(np.count_nonzero((raw < 0) | (raw > 1)))
    predicted = np.clip(raw, 0, 1)
    records = []
    for stamp, (_, row), estimate in zip(available, target.iterrows(), predicted, strict=True):
        records.append({
            "origin": _iso(origin),
            "valid_at": _iso(stamp),
            "lead_hour": int((stamp - origin) / pd.Timedelta(hours=1)),
            "actual_power_norm": float(row["power_norm"]),
            "predicted_power_norm": float(estimate),
            "baseline_power_norm": baseline,
            "baseline_observed_at": _iso(baseline_at),
            "baseline_age_hours": float((origin - (baseline_at + pd.Timedelta(hours=1))) / pd.Timedelta(hours=1)),
            "wind_speed_ms": float(row["wind_speed_ms"]),
            "temperature_c": float(row["temperature_c"]),
        })
    return records, horizon - len(available), clipped


def _plot_window(rows: pd.DataFrame, path_stem: Path, turbine_id: str, origin: str) -> None:
    """Plot one 48-hour window, leaving actual-data gaps visibly broken."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    times = pd.date_range(pd.Timestamp(origin) + pd.Timedelta(hours=1), periods=48, freq="h", tz="UTC")
    series = rows.copy()
    series["valid_at"] = pd.to_datetime(series["valid_at"], utc=True)
    series = series.set_index("valid_at").reindex(times)
    fig, ax = plt.subplots(figsize=(10, 4.5), constrained_layout=True)
    for column, label, color in (
        ("actual_power_norm", "Measured power", "#152e45"),
        ("predicted_power_norm", "HGB using measured weather", "#e17627"),
        ("baseline_power_norm", "Last power at origin", "#3a9b84"),
    ):
        ax.plot(times, series[column], label=label, color=color, linewidth=2)
    ax.set(title=f"{turbine_id}: origin {origin} · measured-weather diagnostic",
           xlabel="Target hour (UTC)", ylabel="Normalized hourly power")
    ax.set_ylim(-0.02, 1.02)
    ax.grid(alpha=0.25)
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=8, tz=times.tz))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M", tz=times.tz))
    ax.legend(loc="upper right")
    fig.savefig(path_stem.with_suffix(".png"), dpi=180)
    fig.savefig(path_stem.with_suffix(".svg"))
    plt.close(fig)


def run_evaluation(output_dir: Path, data_directory: Path | None = None) -> dict:
    history, audits = ingest_all(data_directory)
    if {audit["turbine_id"] for audit in audits} != set(SITE_IDS):
        raise ValueError("Both distinct turbine sources are required")
    for audit in audits:
        if audit["february_2026_rows"]:
            raise ValueError("This diagnostic expects no February 2026 truth")
    history = history.copy()
    history["timestamp"] = pd.to_datetime(history["timestamp"], utc=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "kind": "chronological_measured_weather_diagnostic",
        "weather_input": "observed_same_target_hour_scada_wind_and_temperature",
        "is_as_issued_weather_backtest": False,
        "first_origin_training_ceiling": FIRST_ORIGIN,
        "regressor": "HistGradientBoostingRegressor",
        "parameters": MODEL_PARAMETERS,
        "sources": {a["turbine_id"]: {"sha256": a["source_sha256"],
                                      "source_rows": a["source_rows"],
                                      "complete_hours": a["complete_hours"]} for a in audits},
        "periods": {},
    }
    for period_name, (start_text, end_text) in PERIODS.items():
        start, end = pd.Timestamp(start_text), pd.Timestamp(end_text)
        period_result = {"start_inclusive": start_text, "end_exclusive": end_text, "turbines": {}}
        for turbine_id in SITE_IDS:
            site_history = history.loc[history["turbine_id"].eq(turbine_id)].sort_values("timestamp").reset_index(drop=True)
            model = train_model(history, start_text, turbine_id)
            turbine_result = {"model_id": model.metadata["model_id"],
                              "training_rows": int(model.metadata["training_rows"]),
                              "train_last_interval_start": model.metadata["train_last_interval_start"],
                              "horizons": {}}
            for horizon in HORIZONS:
                origins = pd.date_range(start, end - pd.Timedelta(hours=horizon + 1), freq="D", tz="UTC")
                records: list[dict] = []
                missing, clipped = 0, 0
                for origin in origins:
                    points, absent, clips = evaluate_window(site_history, model, origin, horizon)
                    records.extend(points)
                    missing += absent
                    clipped += clips
                if not records:
                    raise ValueError(f"No scored points for {period_name}, {turbine_id}, {horizon}h")
                frame = pd.DataFrame(records)
                file_name = f"{period_name}_{turbine_id}_{horizon}h_points.csv"
                frame.to_csv(output_dir / file_name, index=False)
                truth = frame["actual_power_norm"].to_numpy(dtype=float)
                pred = frame["predicted_power_norm"].to_numpy(dtype=float)
                baseline = frame["baseline_power_norm"].to_numpy(dtype=float)
                model_score, baseline_score = score(pred, truth), score(baseline, truth)
                metrics = {
                    "daily_origins": len(origins),
                    "possible_origin_lead_pairs": len(origins) * horizon,
                    "scored_origin_lead_pairs": len(frame),
                    "excluded_missing_complete_hour_pairs": missing,
                    "unique_target_hours_scored": int(frame["valid_at"].nunique()),
                    "clipped_model_predictions": clipped,
                    "baseline_kind": "last_completed_observed_power_at_each_origin",
                    "baseline_max_age_hours": float(frame["baseline_age_hours"].max()),
                    "model": model_score,
                    "baseline": baseline_score,
                    "mae_improvement_vs_baseline": baseline_score["mae"] - model_score["mae"],
                    "rmse_improvement_vs_baseline": baseline_score["rmse"] - model_score["rmse"],
                    "points_csv": file_name,
                }
                if period_name == "january_test" and horizon == 48:
                    coverage = frame.groupby("origin").size().sort_values(ascending=False)
                    chosen_origin = str(coverage.index[0])
                    plot_stem = f"{turbine_id}_january_48h_example"
                    _plot_window(frame.loc[frame["origin"].eq(chosen_origin)],
                                 output_dir / plot_stem, turbine_id, chosen_origin)
                    metrics["example_plot_png"] = plot_stem + ".png"
                    metrics["example_plot_svg"] = plot_stem + ".svg"
                    metrics["example_origin"] = chosen_origin
                    metrics["example_scored_hours"] = int(coverage.iloc[0])
                turbine_result["horizons"][str(horizon)] = metrics
            period_result["turbines"][turbine_id] = turbine_result
        result["periods"][period_name] = period_result
    result["limitations"] = [
        "Future-hour wind and temperature are measurements, unavailable at a real forecast origin.",
        "The January protocol was fixed here without tuning, but January has been inspected in earlier local diagnostics.",
        "Overlapping daily 24/48-hour windows count origin-lead pairs; unique target counts are also reported.",
        "No February truth or verified as-issued weather forecast archive is available.",
        "Source timezone and ten-minute interval-start semantics are assumptions.",
    ]
    (output_dir / "report.json").write_text(json.dumps(result, indent=2, ensure_ascii=False,
                                                        allow_nan=False) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/evaluation"))
    parser.add_argument("--data-dir", type=Path, default=None)
    args = parser.parse_args()
    report = run_evaluation(args.output_dir, args.data_dir)
    for period_name, period in report["periods"].items():
        for turbine, value in period["turbines"].items():
            for horizon, metrics in value["horizons"].items():
                print(f"{period_name} {turbine} {horizon}h: {metrics['scored_origin_lead_pairs']} pairs; "
                      f"HGB MAE {metrics['model']['mae']:.4f}, RMSE {metrics['model']['rmse']:.4f}, "
                      f"R² {metrics['model']['r2']:.4f}; baseline MAE {metrics['baseline']['mae']:.4f}")
    print(f"Wrote {args.output_dir / 'report.json'}")


if __name__ == "__main__":
    main()
