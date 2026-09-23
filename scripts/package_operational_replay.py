"""Package verified February outputs and models; raw weather must be fetched separately."""
from __future__ import annotations

import argparse
import importlib.metadata
import csv
import json
import math
import os
import re
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from backend.core.contracts import CSV_FIELDS, FIRST_ORIGIN, SITE_IDS, artifact_dir, expected_hours, iso, utc_time
from backend.ml.model import predict_power_csv
from backend.ml.model_input import read_model_input
from backend.adapters.weather import SITES
from scripts.package_replay import PROFILE, _active_model, _copy, _runtime, _sha


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != CSV_FIELDS:
            raise ValueError("Unexpected forecast CSV columns")
        return list(reader)


def _validate_report(directory: Path) -> tuple[dict, dict, dict]:
    report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    required = {"status": "ok", "mode": "archive", "weather_source": "operational",
                "full_february_replay": True, "historical_availability_verified": True,
                "complete_forecast_coverage": True, "truth_scored": False,
                "expected_runs": 56, "completed_runs": 56, "expected_rows": 2688,
                "actual_rows": 2688, "daily_rows": 1344, "output_file": "forecast.csv",
                "daily_output_file": "daily_forecast.csv", "failures": []}
    if any(report.get(key) != value for key, value in required.items()):
        raise ValueError("Only a complete verified operational February replay can be packaged")
    pairs = {(turbine, iso(utc_time(FIRST_ORIGIN) + timedelta(days=day)))
             for turbine in SITE_IDS for day in range(28)}
    runs = report.get("runs")
    if not isinstance(runs, list) or len(runs) != 56:
        raise ValueError("Expected 56 run records")
    by_pair = {}
    for run in runs:
        pair = run.get("turbine_id"), run.get("origin")
        provenance = run.get("weather_provenance", {})
        if (pair not in pairs or pair in by_pair or run.get("mode") != "archive"
                or run.get("horizon_hours") != 48 or provenance.get("provenance_status") != "verified"
                or not provenance.get("source_url") or not provenance.get("run_id")
                or provenance.get("availability_verified") is False):
            raise ValueError("Invalid replay identity or weather provenance")
        if not (utc_time(provenance["initialized_at"]) <= utc_time(provenance["available_at"])
                <= utc_time(pair[1])):
            raise ValueError("Weather publication violates historical chronology")
        if utc_time(run["train_last_interval_start"]) + timedelta(hours=1) > utc_time(FIRST_ORIGIN):
            raise ValueError("Model training crosses the frozen cutoff")
        by_pair[pair] = run
    rows = _read_csv(directory / "forecast.csv")
    if len(rows) != 2688:
        raise ValueError("Expected 2688 forecast rows")
    grouped = {pair: [] for pair in pairs}
    for row in rows:
        pair = row["turbine_id"], row["origin"]
        if pair not in by_pair:
            raise ValueError("Unexpected forecast turbine/origin")
        run = by_pair[pair]
        power = float(row["power_norm"])
        if (row["mode"] != "archive" or row["provenance_status"] != "verified"
                or row["model_id"] != run["model_id"]
                or row["run_id"] != run["weather_provenance"]["run_id"]
                or not math.isfinite(power) or not 0 <= power <= 1):
            raise ValueError("Forecast CSV disagrees with replay report")
        grouped[pair].append(row)
    for pair, run_rows in grouped.items():
        if ([row["valid_at"] for row in run_rows] != expected_hours(pair[1], 48)
                or [int(row["lead_hour"]) for row in run_rows] != list(range(1, 49))):
            raise ValueError("Missing, duplicate or reordered forecast hours")
    daily_rows = _read_csv(directory / "daily_forecast.csv")
    if daily_rows != [row for row in rows if int(row["lead_hour"]) <= 24]:
        raise ValueError("Daily series is not the exact first 24 hours of each forecast")
    return report, by_pair, grouped


def package_operational_replay(report_dir: Path, output_dir: Path, *,
                               source_artifacts: Path | None = None) -> dict:
    """Verify supplied CSV/model dependencies and atomically publish a compact kit.

    This package deliberately excludes GRIB/weather cache. Its hashes detect
    changes to packaged files; they are not independent publication attestations.
    A complete weather-to-model rerun requires fetching the source archive.
    """
    report_dir, output_dir = Path(report_dir), Path(output_dir)
    source_artifacts = Path(source_artifacts) if source_artifacts is not None else artifact_dir()
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("Output directory already exists; choose a new path")
    report, by_pair, forecast_rows = _validate_report(report_dir)
    models = {turbine: _active_model(source_artifacts, turbine) for turbine in SITE_IDS}
    for turbine, (model, model_path) in models.items():
        if _sha(model_path / "model.pkl") != model.metadata["artifact_sha256"]:
            raise ValueError("Model digest mismatch")
    for (turbine, origin), run in by_pair.items():
        model, _ = models[turbine]
        if model.metadata["model_id"] != run["model_id"]:
            raise ValueError("Replay did not use the active provider model")
        source_input = run["model_input"]
        digest = source_input.get("sha256", "")
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or source_input.get("filename") != f"{digest}.csv":
            raise ValueError("Invalid model input filename/digest")
        csv_path = source_artifacts / "model_inputs" / source_input["filename"]
        if csv_path.is_symlink() or _sha(csv_path) != digest:
            raise ValueError("Unsafe or changed model input")
        input_rows = read_model_input(csv_path, turbine_id=turbine, origin=origin, horizon_hours=48,
                         expected_sha256=digest)
        from backend.adapters.operational_weather import fetch_operational_weather
        weather = fetch_operational_weather(next(site for site in SITES if site["turbine_id"] == turbine), origin, 48, "archive")
        if input_rows != [{"turbine_id": turbine, **row} for row in weather["rows"]]:
            raise ValueError("Model input does not match independently revalidated archived weather")
        for key in ("raw_sha256", "initialized_at", "available_at", "run_id", "source_url", "availability_basis"):
            if weather["manifest"].get(key) != run["weather_provenance"].get(key):
                raise ValueError("Replay provenance differs from revalidated operational weather")
        predicted = predict_power_csv(model, csv_path, turbine_id=turbine, origin=origin,
                                      horizon_hours=48, expected_sha256=digest)
        if len(predicted) != 48 or any(
                not math.isfinite(value) or not math.isclose(min(1.0, max(0.0, value)),
                    float(row["power_norm"]), rel_tol=0, abs_tol=1e-12)
                for value, row in zip(predicted, forecast_rows[(turbine, origin)])):
            raise ValueError("Packaged model/input do not reproduce forecast power")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".operational-package-", dir=output_dir.parent))
    try:
        payload = temporary / "artifacts"
        for filename in ("report.json", "forecast.csv", "daily_forecast.csv"):
            _copy(report_dir / filename, temporary / filename)
        from backend.adapters.operational_weather import cache_dir, _run
        for origin in sorted({origin for _, origin in by_pair}):
            _, _, _, folder = _run(origin)
            _copy(cache_dir() / folder / "receipt.json", temporary / "weather_receipts" / f"{folder}.json")
        registry = {}
        for turbine, (model, model_path) in models.items():
            relative = f"{turbine}/{model.metadata['model_id'].removeprefix('sha256:')}"
            registry[turbine] = relative
            for filename in ("metadata.json", "model.pkl"):
                _copy(model_path / filename, payload / "models" / PROFILE / relative / filename)
        (payload / "models" / PROFILE / "latest.json").write_text(
            json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        for run in by_pair.values():
            filename = run["model_input"]["filename"]
            _copy(source_artifacts / "model_inputs" / filename, payload / "model_inputs" / filename)
        (temporary / "README.md").write_text(
            "# Февраль 2026: операционный прогноз\n\n"
            "56 запусков для T1/T2; 2688 строк прогнозов на 48 часов и 1344 строки "
            "неперекрывающегося февраля (первые 24 часа каждого запуска). Начало расчётов — "
            "31 января, 23:00 Asia/Almaty. Мощность нормализована [0,1]. "
            "Февральской фактической мощности нет, поэтому метрики точности не рассчитаны.\n\n"
            "В комплект входят отчёт, выходные CSV, точные входные CSV, две модели и 28 погодных квитанций с URL, диапазонами байтов, Last-Modified и SHA-256 исходных объектов. "
            "При упаковке проверены все даты, хеши входов, модели и воспроизводимость "
            "числовых прогнозов из входных CSV. Версии среды указаны в bundle_manifest.json.\n\n"
            "**Исходные GRIB и погодный кеш не включены.** Отчёт сохраняет ссылки и "
            "сведения о погодных выпусках. Полное воспроизведение от источника погоды "
            "требует сети и повторной загрузки операционного архива ECMWF. "
            "Контрольные суммы пакета подтверждают целостность файлов, а не служат "
            "независимым доказательством исторической публикации.\n\n"
            "Используйте доверенную копию проекта и совместимые версии зависимостей. "
            "Пакет содержит pickle обученных моделей; загружайте только доверенные артефакты.\n\n"
            "```sh\n"
            "ARTIFACT_DIR=<bundle>/artifacts python -m scripts.fetch_operational_weather\n"
            "ARTIFACT_DIR=<bundle>/artifacts python -m scripts.replay --weather-source operational --output-dir <bundle>/reproduced\n"
            "```\n\n"
            "Сравните reproduced/forecast.csv и reproduced/daily_forecast.csv с файлами "
            "этого комплекта. Загрузка архива проверяет время публикации копий относительно "
            "момента расчёта; это не утверждение о точном времени первой публикации. "
            "Никакого автоматического перехода к фактической погоде или условным данным нет.\n\n"
            "Источник: ECMWF Open Data, https://www.ecmwf.int/en/forecasts/datasets/open-data . "
            "Условия распространения: CC BY 4.0, https://creativecommons.org/licenses/by/4.0/ .\n",
            encoding="utf-8")
        files = {path.relative_to(temporary).as_posix(): {"sha256": _sha(path), "bytes": path.stat().st_size}
                 for path in sorted(temporary.rglob("*")) if path.is_file()}
        manifest = {"version": 1, "kind": "operational_february_outputs_and_models",
                    "full_february_replay": True, "historical_availability_verified": True,
                    "source_weather_included": False, "weather_receipts_included": True, "full_rerun_requires_network": True,
                    "input_to_power_reproduced": True, "runtime": {**_runtime(), "eccodes": importlib.metadata.version("eccodes")},
                    "expected_runs": report["expected_runs"], "actual_rows": report["actual_rows"],
                    "files": files}
        (temporary / "bundle_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        os.rename(temporary, output_dir)
        return manifest
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, default=artifact_dir() / "february_operational")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-artifacts", type=Path, default=artifact_dir())
    args = parser.parse_args()
    result = package_operational_replay(args.report_dir, args.output_dir, source_artifacts=args.source_artifacts)
    print(json.dumps({"output_dir": str(args.output_dir), "files": len(result["files"]),
                      "actual_rows": result["actual_rows"], "source_weather_included": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
