"""Read-only February handoff audit; no network, inference, training or GRIB decode."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from backend.adapters.operational_weather import cache_dir, BASE, STEPS, PARAMS
from backend.core.contracts import FIRST_ORIGIN, artifact_dir, expected_hours, fingerprint, iso, utc_time


def audit(report_dir: Path, inputs_root: Path, weather_root: Path) -> dict:
    checks = []
    def check(name, condition):
        checks.append({"check": name, "passed": bool(condition)})
    try:
        report = json.loads((report_dir / "report.json").read_text())
        rows = list(csv.DictReader((report_dir / "forecast.csv").open()))
        daily = list(csv.DictReader((report_dir / "daily_forecast.csv").open()))
        runs = report["runs"]
        origins = [iso(utc_time(FIRST_ORIGIN) + timedelta(days=i)) for i in range(28)]
        expected = {(t, o) for t in ("T1", "T2") for o in origins}
        indexed = {(r["turbine_id"], r["origin"]): r for r in runs}
        check("Полный операционный отчёт", report.get("status") == "ok" and report.get("weather_source") == "operational"
              and report.get("full_february_replay") is True and report.get("historical_availability_verified") is True
              and not report.get("failures"))
        check("56 уникальных запусков", len(runs) == 56 and set(indexed) == expected)
        check("2688 строк, по 48 на запуск", len(rows) == 2688 and Counter((r["turbine_id"], r["origin"]) for r in rows) == Counter({k: 48 for k in expected}))
        check("1344 строки месячного ряда", len(daily) == 1344 and daily == [r for r in rows if int(r["lead_hour"]) <= 24])
        zone = ZoneInfo("Asia/Almaty")
        check("672 уникальных февральских часа на турбину", all(
            len({r["valid_at"] for r in daily if r["turbine_id"] == t}) == 672
            and all(utc_time(r["valid_at"]).astimezone(zone).strftime("%Y-%m") == "2026-02" for r in daily if r["turbine_id"] == t)
            for t in ("T1", "T2")))
        check("Мощность конечна и в [0,1]", all(math.isfinite(float(r["power_norm"])) and 0 <= float(r["power_norm"]) <= 1 for r in rows))
        check("Нет выдуманной оценки по факту", report.get("truth_scored") is False)
        receipts = set()
        for key, run in indexed.items():
            selected = [r for r in rows if (r["turbine_id"], r["origin"]) == key]
            provenance = run["weather_provenance"]
            origin = utc_time(run["origin"])
            label = f"{key[0]} {key[1]}"
            check("Часы и идентичность CSV: " + label, [r["valid_at"] for r in selected] == expected_hours(run["origin"], 48)
                  and [int(r["lead_hour"]) for r in selected] == list(range(1, 49))
                  and all(r["model_id"] == run["model_id"] and r["run_id"] == provenance["run_id"]
                          and r["mode"] == "archive" and r["provenance_status"] == "verified" for r in selected))
            check("Хронология: " + label, provenance["provenance_status"] == "verified"
                  and provenance["availability_basis"] == "operational_object_last_modified"
                  and utc_time(provenance["initialized_at"]) <= utc_time(provenance["available_at"]) <= origin
                  and utc_time(run["train_last_interval_start"]) + timedelta(hours=1) <= utc_time(FIRST_ORIGIN))
            descriptor = run["model_input"]
            input_path = inputs_root / descriptor["filename"]
            raw = input_path.read_bytes()
            input_rows = list(csv.DictReader(raw.decode().splitlines()))
            check("Точный входной CSV: " + label, input_path.resolve().parent == inputs_root.resolve()
                  and hashlib.sha256(raw).hexdigest() == descriptor["sha256"]
                  and descriptor["row_count"] == len(input_rows) == 48
                  and [r["valid_at"] for r in input_rows] == expected_hours(run["origin"], 48)
                  and list(input_rows[0]) == descriptor["columns"]
                  and all(r["turbine_id"] == key[0] and math.isfinite(float(r["wind_speed_ms"]))
                          and math.isfinite(float(r["temperature_c"])) for r in input_rows))
            folder = weather_root / origin.strftime("%Y%m%d-00z")
            receipt = json.loads((folder / "receipt.json").read_text())
            check("Привязка к погодному свидетельству: " + label,
                  receipt["origin"] == run["origin"] and receipt["receipt_sha256"] == provenance["raw_sha256"]
                  and utc_time(provenance["available_at"]) == max(utc_time(m["last_modified"]) for m in receipt["objects"].values()))
            if folder not in receipts:
                receipts.add(folder)
                objects = receipt["objects"]
                check("68 частей исходных объектов: " + folder.name, set(objects) == {f"{s}-{p}" for s in STEPS for p in ("index", *PARAMS)}
                      and receipt["receipt_sha256"] == fingerprint({k: v for k, v in receipt.items() if k != "receipt_sha256"})[7:])
                check("Хеши и сроки объектов: " + folder.name, all(
                    hashlib.sha256((folder / f"{name}.bin").read_bytes()).hexdigest() == meta["sha256"]
                    and meta["url"].startswith(BASE + "/" + origin.strftime("%Y%m%d/00z/ifs/0p25/oper/"))
                    and utc_time(provenance["initialized_at"]) <= utc_time(meta["last_modified"]) <= origin
                    for name, meta in objects.items()))
        check("Одна замороженная модель на турбину", all(len({r["model_id"] for r in runs if r["turbine_id"] == t}) == 1 for t in ("T1", "T2")))
        check("28 отдельных погодных выпусков", len(receipts) == 28)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        checks.append({"check": "Все обязательные файлы доступны и корректны", "passed": False, "reason": type(exc).__name__})
    return {"status": "ok" if checks and all(c["passed"] for c in checks) else "incomplete", "checks": checks,
            "limitations": ["Фактической мощности февраля нет; точность не оценена.",
                            "Аудит сверяет локальные свидетельства; GRIB декодируется и проверяется погодным адаптером.",
                            "Проверенное происхождение погоды не подтверждает точность модели мощности."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, default=Path("artifacts/february_operational"))
    parser.add_argument("--inputs-root", type=Path, default=artifact_dir() / "model_inputs")
    parser.add_argument("--weather-root", type=Path, default=cache_dir())
    args = parser.parse_args()
    result = audit(args.report_dir, args.inputs_root, args.weather_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
