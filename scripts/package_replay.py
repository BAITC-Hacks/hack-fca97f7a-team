"""Package a reproducible, explicitly conditional February replay artifact."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from backend.adapters.replay_weather import _read_entry, _request, cache_dir
from backend.adapters.weather import SITES
from backend.core.contracts import CSV_FIELDS, FIRST_ORIGIN, ROOT, SITE_IDS, artifact_dir, expected_hours, iso, utc_time
from backend.ml.model import _load_versioned
from backend.ml.model_input import read_model_input

PROFILE = "open_meteo_ecmwf_ifs_10m"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"Missing or unsafe source artifact: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _validate_report(report_dir: Path) -> tuple[dict, dict]:
    report = json.loads((report_dir / "report.json").read_text(encoding="utf-8"))
    expected_pairs = {(site, iso(utc_time(FIRST_ORIGIN) + timedelta(days=day)))
                      for day in range(28) for site in SITE_IDS}
    if (report.get("status") != "ok" or report.get("mode") != "archive"
            or report.get("weather_source") != "provider-documented"
            or report.get("complete_forecast_coverage") is not True
            or report.get("full_february_replay") is not False
            or report.get("historical_availability_verified") is not False
            or report.get("truth_scored") is not False
            or report.get("expected_runs") != 56 or report.get("completed_runs") != 56
            or report.get("expected_rows") != 2688 or report.get("actual_rows") != 2688
            or report.get("output_file") != "documented_forecast.csv"
            or report.get("daily_output_file") != "documented_daily_forecast.csv"
            or report.get("daily_rows") != 1344
            or report.get("failures") != [] or not isinstance(report.get("runs"), list)
            or len(report["runs"]) != 56):
        raise ValueError("Replay report is incomplete or claims verified availability")
    by_pair = {}
    for run in report["runs"]:
        pair = (run.get("turbine_id"), run.get("origin"))
        if (pair not in expected_pairs or pair in by_pair or run.get("horizon_hours") != 48
                or run.get("mode") != "archive" or not isinstance(run.get("model_input"), dict)
                or not isinstance(run.get("weather_provenance"), dict)):
            raise ValueError("Replay report contains an invalid or duplicate run")
        by_pair[pair] = run
    if set(by_pair) != expected_pairs:
        raise ValueError("Replay report lacks a required turbine/origin")
    forecast_path = report_dir / "documented_forecast.csv"
    with forecast_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != CSV_FIELDS:
            raise ValueError("Replay forecast CSV has unexpected columns")
        rows = list(reader)
    if len(rows) != 2688:
        raise ValueError("Replay forecast CSV must have 2688 rows")
    csv_by_pair = {}
    for row in rows:
        pair = (row["turbine_id"], row["origin"])
        if pair not in by_pair or row["mode"] != "archive" or row["provenance_status"] != "provider_documented":
            raise ValueError("Replay forecast CSV identity/provenance mismatch")
        if row["model_id"] != by_pair[pair]["model_id"] or row["run_id"] != by_pair[pair]["weather_provenance"]["run_id"]:
            raise ValueError("Replay forecast CSV model/weather run mismatch")
        power = float(row["power_norm"])
        if not math.isfinite(power) or not 0 <= power <= 1:
            raise ValueError("Replay forecast CSV contains invalid power")
        csv_by_pair.setdefault(pair, []).append(row)
    for pair, run_rows in csv_by_pair.items():
        if ([row["valid_at"] for row in run_rows] != expected_hours(pair[1], 48)
                or [int(row["lead_hour"]) for row in run_rows] != list(range(1, 49))):
            raise ValueError("Replay forecast CSV has missing or reordered hours")
    with (report_dir / "documented_daily_forecast.csv").open(newline="", encoding="utf-8") as stream:
        daily_reader = csv.DictReader(stream)
        if daily_reader.fieldnames != CSV_FIELDS:
            raise ValueError("Daily replay CSV has unexpected columns")
        daily_rows = list(daily_reader)
    if daily_rows != [row for row in rows if int(row["lead_hour"]) <= 24]:
        raise ValueError("Daily replay CSV is not the first 24 hours of each run")
    return report, by_pair


def _runtime() -> dict:
    names = ("numpy", "pandas", "scikit-learn", "scipy", "httpx", "threadpoolctl")
    return {"python": platform.python_version(),
            "packages": {name: importlib.metadata.version(name) for name in names}}


def _active_model(source_artifacts: Path, turbine: str):
    root = source_artifacts / "models" / PROFILE
    registry = json.loads((root / "latest.json").read_text(encoding="utf-8"))
    indexed = Path(registry[turbine])
    candidates = ([indexed] if indexed.is_absolute() else [root / indexed, ROOT / indexed, Path.cwd() / indexed])
    allowed_parent = (root / turbine).resolve()
    path = next((candidate for candidate in candidates
                 if candidate.resolve().parent == allowed_parent and candidate.is_dir()), None)
    if path is None:
        raise ValueError("Active model registry points outside the selected turbine")
    bundle = _load_versioned(path)
    if bundle.metadata.get("turbine_id") != turbine or bundle.metadata.get("profile") != PROFILE:
        raise ValueError("Active model registry has wrong turbine or profile")
    return bundle, path


def package_replay(report_dir: Path, output_dir: Path, *, weather_dir: Path | None = None,
                   source_artifacts: Path | None = None) -> dict:
    """Verify exact dependencies, then atomically publish an artifact directory."""
    report_dir, output_dir = Path(report_dir), Path(output_dir)
    weather_dir = Path(weather_dir) if weather_dir is not None else cache_dir()
    source_artifacts = Path(source_artifacts) if source_artifacts is not None else artifact_dir()
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("Output directory already exists; choose a new package path")
    report, by_pair = _validate_report(report_dir)
    models = {}
    for turbine in SITE_IDS:
        fitted, model_path = _active_model(source_artifacts, turbine)
        model_id = fitted.metadata["model_id"]
        if _sha(model_path / "model.pkl") != fitted.metadata["artifact_sha256"]:
            raise ValueError("Active model artifact digest mismatch")
        models[turbine] = (model_id, model_path)
    for (turbine, origin), run in by_pair.items():
        if run["model_id"] != models[turbine][0]:
            raise ValueError("Replay used a model other than the active provider model")
        source_input = run["model_input"]
        filename, digest = source_input.get("filename"), source_input.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64 or filename != f"{digest}.csv":
            raise ValueError("Model input filename/digest mismatch")
        input_path = source_artifacts / "model_inputs" / filename
        if _sha(input_path) != digest:
            raise ValueError("Model input checksum mismatch")
        input_rows = read_model_input(input_path, turbine_id=turbine, origin=origin, horizon_hours=48,
                                      expected_sha256=digest)
        site = next(site for site in SITES if site["turbine_id"] == turbine)
        identity, timing, name = _request(site, origin, 48, "archive")
        bundle = _read_entry(weather_dir / name, identity, timing, 48)
        provenance = run["weather_provenance"]
        if (provenance.get("provenance_status") != "provider_documented"
                or provenance.get("availability_verified") is not False
                or provenance.get("available_at") is not None
                or provenance.get("initialized_at") != bundle["manifest"]["initialized_at"]
                or provenance.get("assumed_available_by") != bundle["manifest"]["assumed_available_by"]
                or provenance.get("availability_basis") != bundle["manifest"]["availability_basis"]
                or provenance.get("source_url") != bundle["manifest"]["source_url"]
                or provenance.get("raw_sha256") != bundle["manifest"]["raw_sha256"]
                or provenance.get("forecast_sha256") != bundle["manifest"]["forecast_sha256"]
                or provenance.get("run_id") != bundle["manifest"]["run_id"]):
            raise ValueError("Replay weather provenance disagrees with cached raw run")
        if input_rows != [{"turbine_id": turbine, **row} for row in bundle["rows"]]:
            raise ValueError("Model input CSV disagrees with cached weather features")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".replay-package-", dir=output_dir.parent))
    try:
        payload = temporary / "artifacts"
        _copy(report_dir / "report.json", payload / "february_replay" / "report.json")
        _copy(report_dir / "documented_forecast.csv", payload / "february_replay" / "documented_forecast.csv")
        _copy(report_dir / "documented_daily_forecast.csv", payload / "february_replay" / "documented_daily_forecast.csv")
        for turbine, (model_id, model_path) in models.items():
            target = payload / "models" / PROFILE / turbine / model_id.removeprefix("sha256:")
            _copy(model_path / "metadata.json", target / "metadata.json")
            _copy(model_path / "model.pkl", target / "model.pkl")
        model_index = {turbine: f"{turbine}/{models[turbine][0].removeprefix('sha256:')}" for turbine in SITE_IDS}
        index_path = payload / "models" / PROFILE / "latest.json"
        index_path.write_text(json.dumps(model_index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        for run in by_pair.values():
            filename = run["model_input"]["filename"]
            destination = payload / "model_inputs" / filename
            if not destination.exists():
                _copy(source_artifacts / "model_inputs" / filename, destination)
        for turbine, origin in by_pair:
            site = next(site for site in SITES if site["turbine_id"] == turbine)
            _, _, name = _request(site, origin, 48, "archive")
            for filename in ("raw.json", "manifest.json"):
                _copy(weather_dir / name / filename, payload / "replay_weather" / name / filename)
        readme = ("# Февральский прогноз: переносимый пакет\n\n"
                  "Содержит 56 расчётов для T1/T2 (48 часов каждый), сохранённые погодные выпуски "
                  "Open-Meteo, входные CSV и две использованные модели. "
                  "Доступность каждого выпуска в прошлом **предполагается** по консервативному правилу; "
                  "исторический журнал публикации отсутствует. Февральской фактической мощности нет, "
                  "поэтому точность не рассчитана.\n\n"
                  "Погодные данные: Open-Meteo Single Runs, модель ECMWF IFS. "
                  "Документация источника: https://open-meteo.com/en/docs/single-runs-api . "
                  "Условия Open-Meteo: https://open-meteo.com/en/terms . "
                  "Данные предоставлены по CC BY 4.0: https://creativecommons.org/licenses/by/4.0/ . "
                  "Источник исходной модели: https://www.ecmwf.int/en/forecasts/datasets/open-data .\n\n"
                  "Для повторного расчёта используйте доверенную копию кода проекта и совместимые версии "
                  "Python/scikit-learn из bundle_manifest.json. Загружайте pickle только из доверенного пакета.\n\n"
                  "```sh\n"
                  "ARTIFACT_DIR=<bundle>/artifacts REPLAY_WEATHER_DIR=<bundle>/artifacts/replay_weather "
                  "python -m scripts.replay --weather-source provider-documented --output-dir <bundle>/reproduced\n"
                  "```\n\n"
                  "Сравните reproduced/documented_forecast.csv с "
                  "artifacts/february_replay/documented_forecast.csv и "
                  "reproduced/documented_daily_forecast.csv с соответствующим файлом пакета.\n")
        (temporary / "README.md").write_text(readme, encoding="utf-8")
        files = {}
        for path in sorted(temporary.rglob("*")):
            if path.is_file():
                relative = path.relative_to(temporary).as_posix()
                files[relative] = {"sha256": _sha(path), "bytes": path.stat().st_size}
        bundle_manifest = {"version": 1, "kind": "provider_documented_february_replay",
                           "availability_verified": False, "full_february_replay": False,
                           "complete_forecast_coverage": True, "runtime": _runtime(),
                           "expected_runs": report["expected_runs"], "actual_rows": report["actual_rows"],
                           "files": files}
        (temporary / "bundle_manifest.json").write_text(
            json.dumps(bundle_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.rename(temporary, output_dir)
        return bundle_manifest
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, default=artifact_dir() / "february_replay")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--weather-dir", type=Path, default=cache_dir())
    args = parser.parse_args()
    root = (artifact_dir() / "submission").resolve()
    if not args.output_dir.resolve().is_relative_to(root):
        parser.error("--output-dir must be under artifacts/submission")
    result = package_replay(args.report_dir, args.output_dir, weather_dir=args.weather_dir)
    print(json.dumps({"output_dir": str(args.output_dir), "files": len(result["files"]),
                      "actual_rows": result["actual_rows"], "availability_verified": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
