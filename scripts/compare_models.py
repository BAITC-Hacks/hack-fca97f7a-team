"""Сравнить две настройки HGB на измеренной погоде; это не проверка погодного API."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from contracts import FIRST_ORIGIN, SITE_IDS, ForecastError
from data import ingest_all
from model import MODEL_VARIANTS, train_model
from scripts.evaluate import evaluate_window, score


PERIODS = {
    "2025-10": ("2025-10-01T00:00:00Z", "2025-11-01T00:00:00Z"),
    "2025-11": ("2025-11-01T00:00:00Z", "2025-12-01T00:00:00Z"),
    "2025-12": ("2025-12-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    "2026-01": ("2026-01-01T00:00:00Z", FIRST_ORIGIN),
}


def compare_period(history: pd.DataFrame, turbine_id: str, start: str, end: str) -> tuple[dict, pd.DataFrame]:
    """Train before the period; score identical daily 48-hour windows for both variants."""
    start_time, end_time = pd.Timestamp(start), pd.Timestamp(end)
    if (start_time.tzinfo is None or end_time.tzinfo is None
            or start_time >= end_time or end_time > pd.Timestamp(FIRST_ORIGIN)):
        raise ForecastError("INVALID_INPUT", "Период сравнения должен завершаться до заморозки обучения.")
    site_history = history.loc[
        history.turbine_id.eq(turbine_id)
        & (history.timestamp + pd.Timedelta(hours=1) <= end_time)
    ].sort_values("timestamp").reset_index(drop=True)
    # Every target interval must finish within the period. Same protocol as evaluate.py.
    origins = pd.date_range(start_time, end_time - pd.Timedelta(hours=49), freq="D")
    results, frames = {}, []
    paired_keys = None
    for variant in MODEL_VARIANTS:
        fitted = train_model(history, start, turbine_id, variant=variant)
        records, missing, clipped = [], 0, 0
        for origin in origins:
            points, absent, clips = evaluate_window(site_history, fitted, origin, 48)
            records.extend(points)
            missing += absent
            clipped += clips
        if not records:
            raise ForecastError("DATA_INVALID", "Нет завершённых целевых часов для сравнения моделей.")
        frame = pd.DataFrame(records)
        keys = list(frame[["origin", "valid_at", "actual_power_norm"]].itertuples(index=False, name=None))
        if paired_keys is not None and keys != paired_keys:
            raise ForecastError("DATA_INVALID", "Варианты модели оценены на разных целевых часах.")
        paired_keys = keys
        metrics = {}
        for name, selected in (("all_48h", frame), ("lead_1_24h", frame.loc[frame.lead_hour <= 24]),
                               ("lead_25_48h", frame.loc[frame.lead_hour > 24])):
            metrics[name] = ({"scored_pairs": len(selected), **score(
                selected.predicted_power_norm.to_numpy(), selected.actual_power_norm.to_numpy())}
                if len(selected) else {"scored_pairs": 0, "mae": None, "rmse": None, "r2": None})
        results[variant] = {
            "model_id": fitted.metadata["model_id"],
            "implementation": fitted.metadata["implementation"],
            "parameters": fitted.metadata["parameters"],
            "training_rows": fitted.metadata["training_rows"],
            "train_last_interval_start": fitted.metadata["train_last_interval_start"],
            "fitted_iterations": int(fitted.estimator.n_iter_),
            "daily_origins": len(origins),
            "possible_origin_lead_pairs": len(origins) * 48,
            "excluded_missing_complete_hour_pairs": missing,
            "unique_target_hours_scored": int(frame.valid_at.nunique()),
            "clipped_predictions": clipped,
            "metrics": metrics,
        }
        frames.append(frame.assign(variant=variant, turbine_id=turbine_id))
    return results, pd.concat(frames, ignore_index=True)


def run_comparison(output_dir: Path, data_directory: Path | None = None) -> dict:
    history, audits = ingest_all(data_directory)
    if ({audit["turbine_id"] for audit in audits} != set(SITE_IDS)
            or any(not audit["matches_expected_source_sha256"] for audit in audits)):
        raise ForecastError("DATA_INVALID", "Нужны проверенные разные исходные истории T1 и T2.")
    report = {
        "kind": "exploratory_chronological_measured_weather_comparison",
        "is_as_issued_weather_backtest": False,
        "weather_input": "observed_same_target_hour_scada_wind_and_temperature",
        "training_ceiling": FIRST_ORIGIN,
        "sources": audits,
        "periods": {},
        "limitations": [
            "Погода целевого часа измерена и неизвестна при реальном прогнозировании.",
            "Все четыре периода исследовательские и уже изучались; это не новый независимый тест.",
            "Суточные окна 48 часов перекрываются: метрики считают пары момент выпуска × горизонт.",
            "Нет проверенного архива прогнозов и февральской фактической мощности.",
            "Высота измерителя ветра неизвестна; соответствие прогнозному ветру 10 м не подтверждено.",
            "Сравнение не изменяет реестр активных моделей.",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    for period, (start, end) in PERIODS.items():
        report["periods"][period] = {"start": start, "end": end, "turbines": {}}
        for turbine_id in SITE_IDS:
            results, points = compare_period(history, turbine_id, start, end)
            filename = f"{period}_{turbine_id}_points.csv"
            points.to_csv(output_dir / filename, index=False)
            report["periods"][period]["turbines"][turbine_id] = {
                "variants": results, "points_csv": filename,
            }
    report["summary"] = {}
    for variant in MODEL_VARIANTS:
        groups = [turbine["variants"][variant]["metrics"]["all_48h"]
                  for period in report["periods"].values() for turbine in period["turbines"].values()]
        report["summary"][variant] = {
            "aggregation": "unweighted_mean_over_month_turbine_groups",
            "groups": len(groups),
            "mean_mae": float(np.mean([group["mae"] for group in groups])),
            "mean_rmse": float(np.mean([group["rmse"] for group in groups])),
            "worst_group_mae": max(group["mae"] for group in groups),
            "worst_group_rmse": max(group["rmse"] for group in groups),
        }
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/model_comparison"))
    args = parser.parse_args()
    report = run_comparison(args.output_dir)
    for variant, metrics in report["summary"].items():
        print(f"{variant}: средняя MAE {metrics['mean_mae']:.5f}; средняя RMSE {metrics['mean_rmse']:.5f}")
    print(f"Диагностика на измеренной погоде. Отчёт: {args.output_dir / 'report.json'}")


if __name__ == "__main__":
    main()
