"""Chronological provider-input experiment and optional local model activation.

Historical Forecast API stitches short leads. This experiment measures source
compatibility, not verified 24/48-hour as-issued forecast skill.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from backend.core.contracts import FEATURES, FIRST_ORIGIN, SITE_IDS, ForecastError, artifact_dir
from backend.ml.data import ingest_all
from backend.ml.model import FORECAST_RECIPES, _raw_predictions, save_model, train_model
from scripts.evaluate import score
from scripts.fetch_training_weather import load_training_weather

PROFILE = "open_meteo_ecmwf_ifs_10m"
# Fix these before inspecting candidate results. January was already inspected
# in earlier diagnostics; it is reported explicitly as previously viewed.
DEVELOPMENT = [("2025-09-01", "2025-10-01"), ("2025-10-01", "2025-11-01")]
CONFIRMATION = [("2025-11-01", "2025-12-01"), ("2025-12-01", "2026-01-01"),
                ("2026-01-01", FIRST_ORIGIN)]


def stamp(value: str) -> pd.Timestamp:
    value = pd.Timestamp(value)
    return value.tz_localize("UTC") if value.tzinfo is None else value.tz_convert("UTC")


def align_history(history: pd.DataFrame, weather: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Join by turbine AND UTC hour; never fill missing labels or copy features."""
    frames = []
    for frame in (history, weather):
        frame = frame.copy()
        frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
        if frame.duplicated(["turbine_id", "timestamp"]).any():
            raise ForecastError("DATA_INVALID", "Повторяются часы турбины в обучающих данных.")
        frames.append(frame)
    history, weather = frames
    ceiling = stamp(FIRST_ORIGIN)
    weather = weather.loc[weather.timestamp + pd.Timedelta(hours=1) <= ceiling]
    history = history.loc[history.timestamp + pd.Timedelta(hours=1) <= ceiling]
    merged = weather[["turbine_id", "timestamp", *FEATURES]].merge(
        history[["turbine_id", "timestamp", "power_norm"]],
        on=["turbine_id", "timestamp"], how="inner", validate="one_to_one")
    if merged.empty or not np.isfinite(merged[[*FEATURES, "power_norm"]].to_numpy(float)).all():
        raise ForecastError("DATA_INVALID", "Нет корректных совпадающих часов погоды и мощности.")
    audit = {}
    for tid in SITE_IDS:
        available = weather.loc[weather.turbine_id.eq(tid)]
        matched = merged.loc[merged.turbine_id.eq(tid)]
        if matched.empty:
            raise ForecastError("DATA_INVALID", "Для обеих турбин нужны совпадающие часы.")
        audit[tid] = {"weather_hours": len(available), "matched_hours": len(matched),
                      "excluded_missing_complete_power_hours": len(available) - len(matched),
                      "first_hour": matched.timestamp.min().isoformat(),
                      "last_hour": matched.timestamp.max().isoformat()}
    return merged.sort_values(["turbine_id", "timestamp"]).reset_index(drop=True), audit


def metrics(predicted, truth) -> dict:
    predicted, truth = np.asarray(predicted, float), np.asarray(truth, float)
    result = score(predicted, truth)
    result.update(bias=float(np.mean(predicted - truth)),
                  absolute_error_p90=float(np.quantile(np.abs(predicted - truth), .9)),
                  mean_prediction=float(np.mean(predicted)), mean_truth=float(np.mean(truth)))
    return result


def temporal_window(frame: pd.DataFrame, turbine: str, start: str, end: str) -> pd.DataFrame:
    return frame.loc[frame.turbine_id.eq(turbine) & frame.timestamp.ge(stamp(start))
                     & (frame.timestamp + pd.Timedelta(hours=1)).le(stamp(end))].copy()


def comparison(history, joined, tid, start, end, recipe, context):
    test = temporal_window(joined, tid, start, end)
    expected = int((stamp(end) - stamp(start)) / pd.Timedelta(hours=1))
    if len(test) < max(24, .90 * expected):
        raise ForecastError("DATA_INVALID", "Покрытие проверочного периода ниже 90%.")
    cutoff = stamp(start).isoformat()
    fitted = train_model(joined, cutoff, tid, profile=PROFILE, recipe=recipe, weather_context=context)
    legacy = train_model(history, cutoff, tid)
    rows = test[FEATURES].to_dict("records")
    raw = _raw_predictions(fitted, rows)
    test["prediction"] = np.clip(raw, 0, 1)
    test["legacy_prediction"] = np.clip(_raw_predictions(legacy, rows), 0, 1)
    completed = joined.loc[joined.turbine_id.eq(tid)
                           & (joined.timestamp + pd.Timedelta(hours=1)).le(stamp(start))]
    test["training_mean_prediction"] = completed.power_norm.mean()
    truth = test.power_norm.to_numpy(float)
    result = {"start": start, "end": end, "hours": len(test),
              "excluded_hours": int((stamp(end) - stamp(start)) / pd.Timedelta(hours=1)) - len(test),
              "training_rows": fitted.metadata["training_rows"],
              "training_last_hour": fitted.metadata["train_last_interval_start"],
              "candidate": metrics(test.prediction, truth),
              "legacy_on_provider_weather": metrics(test.legacy_prediction, truth),
              "training_mean_baseline": metrics(test.training_mean_prediction, truth),
              "clipped_predictions": int(np.sum((raw < 0) | (raw > 1)))}
    return result, test


def promotion_gate(candidate: dict, legacy: dict, constant: dict) -> bool:
    """Require useful MAE improvement without trading away squared-error quality."""
    return (candidate["mae"] <= .95 * legacy["mae"]
            and candidate["rmse"] <= legacy["rmse"]
            and candidate["mae"] < constant["mae"])


def run(weather_dir: Path, output_dir: Path, *, activate: bool = False) -> dict:
    weather, manifest = load_training_weather(weather_dir)
    history, audits = ingest_all()
    if len(audits) != 2 or any(not a["matches_expected_source_sha256"] for a in audits):
        raise ForecastError("DATA_INVALID", "Нужны две исходные истории с подтверждёнными контрольными суммами.")
    joined, join_audit = align_history(history, weather)
    context = {"provider": "open-meteo", "model": "ecmwf_ifs", "wind_height_m": 10,
               "temperature_height_m": 2, "training_weather_kind": "retrospective_stitched_forecast",
               "availability_verified": False, "weather_csv_sha256": manifest["csv_sha256"]}
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {"kind": "chronological_provider_input_diagnostic", "is_as_issued_forecast_backtest": False,
              "profile": PROFILE, "weather_context": context, "join_audit": join_audit,
              "development_periods": DEVELOPMENT, "confirmation_periods": CONFIRMATION,
              "selection_rule": "lowest equal-weight mean MAE across turbines and development months",
              "development": {}, "confirmation": {}, "activated": False,
              "limitations": ["Архив склеен из первых часов выпусков; качество на 24/48 ч не проверено.",
                              "Историческая доступность выпусков к origin не подтверждена.",
                              "Январь ранее просмотрен; он не является нетронутым тестом.",
                              "Высота датчика, нормализация мощности и семантика времени не подтверждены.",
                              "Нет февральской фактической мощности; нет калиброванных интервалов неопределённости."]}
    # All selection uses development only; confirmation is evaluated after the recipe is fixed.
    selection = {}
    for recipe in FORECAST_RECIPES:
        entries = []
        for tid in SITE_IDS:
            for start, end in DEVELOPMENT:
                result, _ = comparison(history, joined, tid, start, end, recipe, context)
                entries.append({"turbine_id": tid, **result})
        report["development"][recipe] = entries
        selection[recipe] = float(np.mean([e["candidate"]["mae"] for e in entries]))
        print(f"Разработка {recipe}: MAE {selection[recipe]:.4f}", flush=True)
    recipe = min(selection, key=selection.get)
    report["selected_recipe"] = recipe
    report["development_selection_mae"] = selection
    all_gates = True
    for tid in SITE_IDS:
        monthly, points = [], []
        for start, end in CONFIRMATION:
            result, test = comparison(history, joined, tid, start, end, recipe, context)
            monthly.append(result)
            test["period_start"] = start
            points.append(test)
        frame = pd.concat(points, ignore_index=True)
        truth = frame.power_norm.to_numpy(float)
        summary = {"candidate": metrics(frame.prediction, truth),
                   "legacy_on_provider_weather": metrics(frame.legacy_prediction, truth),
                   "training_mean_baseline": metrics(frame.training_mean_prediction, truth)}
        gate = promotion_gate(summary["candidate"], summary["legacy_on_provider_weather"],
                              summary["training_mean_baseline"])
        # A pooled improvement must not hide a worse individual month.
        gate &= all(m["candidate"]["mae"] < m["legacy_on_provider_weather"]["mae"]
                    and m["candidate"]["rmse"] <= m["legacy_on_provider_weather"]["rmse"]
                    for m in monthly)
        all_gates &= gate
        segments = {}
        for label, mask in (("low_power_lt_0.1", frame.power_norm.lt(.1)),
                            ("medium_power", frame.power_norm.ge(.1) & frame.power_norm.lt(.7)),
                            ("high_power_ge_0.7", frame.power_norm.ge(.7))):
            if mask.any():
                segments[label] = {"hours": int(mask.sum()),
                                   **metrics(frame.loc[mask, "prediction"], frame.loc[mask, "power_norm"])}
        report["confirmation"][tid] = {"monthly": monthly, "pooled": summary,
                                       "segments": segments, "promotion_gate": bool(gate)}
        frame.to_csv(output_dir / f"{tid}_confirmation_points.csv", index=False)
        print(f"Проверка {tid}: MAE {summary['candidate']['mae']:.4f}; "
              f"раньше {summary['legacy_on_provider_weather']['mae']:.4f}; gate={gate}", flush=True)
    report["promotion_gate_passed"] = bool(all_gates)
    if activate and all_gates:
        for audit in audits:
            tid = audit["turbine_id"]
            bundle = train_model(joined, FIRST_ORIGIN, tid, profile=PROFILE,
                                 recipe=recipe, weather_context=context)
            bundle.metadata["source_sha256"] = audit["source_sha256"]
            bundle.metadata["validation"] = {"kind": report["kind"],
                "forecast_accuracy_verified": False, "selected_recipe": recipe,
                "confirmation": report["confirmation"][tid]}
            save_model(bundle)
        report["activated"] = True
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2,
                                                        allow_nan=False) + "\n", encoding="utf-8")
    if activate and not all_gates:
        raise ForecastError("MODEL_UNAVAILABLE", "Новая модель не прошла критерий улучшения; активация отменена.")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weather-dir", type=Path, default=artifact_dir() / "training_weather")
    parser.add_argument("--output-dir", type=Path, default=artifact_dir() / "forecast_evaluation")
    parser.add_argument("--activate", action="store_true", help="Активировать профиль после проверки улучшения.")
    args = parser.parse_args()
    run(args.weather_dir, args.output_dir, activate=args.activate)


if __name__ == "__main__":
    main()
