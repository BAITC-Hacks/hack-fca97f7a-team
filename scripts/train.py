"""Train once from supplied history, never during a Streamlit rerun."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd

from contracts import FIRST_ORIGIN, FEATURES, SITE_IDS, ForecastError, artifact_dir
from data import ingest_all, save_canonical
from model import save_model, train_model, predict_power


def _diagnose(history: pd.DataFrame, turbine_id: str, output_dir: Path) -> dict:
    """Strict temporal holdout, using measured weather; not an NWP backtest."""
    validation_start = "2026-01-01T00:00:00Z"
    model = train_model(history, validation_start, turbine_id)
    selected = history.loc[
        (history.turbine_id == turbine_id)
        & (history.timestamp >= pd.Timestamp(validation_start))
        & (history.timestamp + pd.Timedelta(hours=1) <= pd.Timestamp(FIRST_ORIGIN))
    ].sort_values("timestamp").copy()
    if selected.empty:
        raise ForecastError("DATA_INVALID", f"No completed January holdout hours for {turbine_id}")
    predicted = np.asarray(predict_power(model, selected[list(FEATURES)].to_dict("records")))
    truth = selected.power_norm.to_numpy(dtype=float)
    baseline = float(model.metadata["baseline_norm"])
    errors = predicted - truth
    report = {
        "kind": "chronological_measured_weather_diagnostic",
        "weather_input": "observed_same_hour_wind_and_temperature",
        "not_a_historical_weather_forecast_backtest": True,
        "validation_start": validation_start,
        "validation_end_exclusive": FIRST_ORIGIN,
        "scored_rows": len(selected),
        "training_rows": model.metadata["training_rows"],
        "train_last_interval_start": model.metadata["train_last_interval_start"],
        "mae": float(np.mean(np.abs(errors))),
        "rmse": float(np.sqrt(np.mean(errors ** 2))),
        "baseline_kind": "constant_last_pre_holdout_observation_for_entire_holdout",
        "baseline_norm": baseline,
        "baseline_mae": float(np.mean(np.abs(truth - baseline))),
        "baseline_rmse": float(np.sqrt(np.mean((truth - baseline) ** 2))),
        "limitations": [
            "Uses measured weather, which is unavailable for real future target hours.",
            "The constant baseline is frozen for all January, not refreshed every origin.",
            "No February truth or verified as-issued weather is available.",
            "Timezone and interval semantics are assumed.",
        ],
    }
    selected["predicted_power_norm"] = predicted
    selected["baseline_norm"] = baseline
    selected["weather_input"] = "observed_measurements_diagnostic_only"
    selected["timestamp"] = selected.timestamp.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    output_dir.mkdir(parents=True, exist_ok=True)
    selected.to_csv(output_dir / f"{turbine_id}_january_diagnostic.csv", index=False)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["fixture", "archive"], default="fixture",
                        help="Weather mode; training always uses real supplied history.")
    parser.add_argument("--skip-validation", action="store_true")
    args = parser.parse_args()
    history, audits = ingest_all()
    if {audit["turbine_id"] for audit in audits} != set(SITE_IDS):
        raise ForecastError("DATA_INVALID", "Для обучения нужны разные исходные истории T1 и T2.")
    if any(not audit.get("matches_expected_source_sha256", False) for audit in audits):
        raise ForecastError("DATA_INVALID", "Контрольная сумма исходного файла не совпадает.")
    save_canonical(history, audits)
    report_dir = artifact_dir() / "training"
    report_dir.mkdir(parents=True, exist_ok=True)
    for audit in audits:
        diagnostic = None if args.skip_validation else _diagnose(history, audit["turbine_id"], report_dir)
        fitted = train_model(history, FIRST_ORIGIN, audit["turbine_id"])
        fitted.metadata["source_sha256"] = audit["source_sha256"]
        fitted.metadata["validation"] = diagnostic
        if diagnostic is not None:
            (report_dir / f"{audit['turbine_id']}_metrics.json").write_text(json.dumps(diagnostic, indent=2))
        save_model(fitted)
        print(f"{audit['turbine_id']}: {fitted.metadata['training_rows']} training hours; "
              f"last interval {fitted.metadata['train_last_interval_start']}; {fitted.metadata['model_id'][:23]}")


if __name__ == "__main__":
    main()
