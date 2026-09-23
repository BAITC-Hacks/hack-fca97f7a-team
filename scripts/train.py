"""Reproducible local fitting of T1/T2, with optional measured-weather diagnostics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter

import numpy as np
import pandas as pd

from contracts import FEATURES, FIRST_ORIGIN, ForecastError, TURBINE_IDS
from data import ingest_sources
from model import predict_power, save_model, train_model


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--models-dir", type=Path, default=Path("artifacts/models"))
    parser.add_argument("--report-dir", type=Path, default=Path("artifacts/training"))
    parser.add_argument("--mode", choices=("fixture", "archive"), default="fixture",
                        help="Intended weather mode; training always uses real measurements and fetches no weather.")
    parser.add_argument("--skip-validation", action="store_true",
                        help="Skip separate January measured-weather diagnostic, not cutoff/input validation.")
    args = parser.parse_args(argv)
    started = perf_counter()
    try:
        history, audit = ingest_sources(args.data_dir, args.data_dir / "canonical")
        for turbine_id in TURBINE_IDS:
            if not audit["sources"][turbine_id]["matches_expected_sha256"]:
                raise ForecastError("DATA_INVALID", f"Unexpected supplied source hash for {turbine_id}")
        print(f"Ingestion: {len(history)} complete UTC hours from two verified sources", flush=True)
        models = {}
        latest = {}
        for turbine_id in TURBINE_IDS:
            diagnostic = None if args.skip_validation else _diagnose(history, turbine_id, args.report_dir)
            fit_start = perf_counter()
            bundle = train_model(history, FIRST_ORIGIN, turbine_id)
            fit_seconds = perf_counter() - fit_start
            bundle.metadata["source_sha256"] = audit["sources"][turbine_id]["sha256"]
            bundle.metadata["validation"] = diagnostic
            artifact_dir = save_model(bundle, args.models_dir)
            latest[turbine_id] = str(artifact_dir)
            models[turbine_id] = {
                "artifact_dir": str(artifact_dir),
                "model_id": bundle.metadata["model_id"],
                "source_sha256": bundle.metadata["source_sha256"],
                "training_rows": bundle.metadata["training_rows"],
                "train_last_interval_start": bundle.metadata["train_last_interval_start"],
                "fit_seconds": round(fit_seconds, 3),
                "validation": diagnostic,
            }
            print(f"{turbine_id}: fitted {bundle.metadata['training_rows']} hours in {fit_seconds:.2f}s; {artifact_dir}", flush=True)
        if models["T1"]["model_id"] == models["T2"]["model_id"]:
            raise ForecastError("DATA_INVALID", "Turbine model identities unexpectedly match")
        report = {
            "status": "ok", "train_cutoff": FIRST_ORIGIN,
            "training_data": "real_supplied_turbine_measurements",
            "intended_weather_mode": args.mode, "weather_fetched": False,
            "features": list(FEATURES), "target": "normalized_hourly_mean_power",
            "models": models, "elapsed_seconds": round(perf_counter() - started, 3),
            "audit_path": str(args.data_dir / "canonical" / "audit.json"),
            "limitations": ["Timezone/interval semantics assumed", "No February truth", "No verified archived-weather backtest"],
        }
        _write_json(args.report_dir / "training_report.json", report)
        _write_json(args.models_dir / "latest.json", latest)
        print(f"Training complete: {args.report_dir / 'training_report.json'}", flush=True)
        return 0
    except (ForecastError, OSError, ValueError) as exc:
        error = exc.to_dict() if isinstance(exc, ForecastError) else {"status": "error", "code": "DATA_INVALID", "message": str(exc), "trace": []}
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
