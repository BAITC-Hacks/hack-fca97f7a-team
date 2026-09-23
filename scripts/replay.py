"""Reproduce February 2026 forecasts; missing archive evidence is an explicit failure.

No training, LLM calls or invented weather. Default: 28 daily origins, two
registered turbines and 48-hour horizons (2,688 rows including March spillover).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
from datetime import timedelta
from pathlib import Path
import tempfile

from backend.services.agent import run_forecast
from backend.core.contracts import FIRST_ORIGIN, SITE_IDS, CSV_FIELDS, artifact_dir, expected_hours, forecast_csv, iso, utc_time


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     suffix=".tmp", delete=False) as stream:
        stream.write(content)
        temporary = Path(stream.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def run_replay(output_dir: Path, *, mode: str = "archive", days: int = 28,
               forecast=run_forecast) -> dict:
    if mode not in ("archive", "fixture") or not 1 <= days <= 28:
        raise ValueError("Replay requires archive/fixture and 1–28 daily origins")
    output_dir = Path(output_dir)
    rows, runs, failures = [], [], []
    for day in range(days):
        origin = iso(utc_time(FIRST_ORIGIN) + timedelta(days=day))
        for turbine in SITE_IDS:
            request = {"turbine_id": turbine, "origin": origin, "horizon_hours": 48, "mode": mode}
            try:
                result = forecast(request)
                if result.get("status") != "ok":
                    failures.append({**request, "code": result.get("code", "INTERNAL_ERROR"),
                                     "message": result.get("message", "Прогноз недоступен")})
                    continue
                expected = expected_hours(origin, 48)
                provenance = result["weather_provenance"]
                if (any(result.get(k) != v for k, v in request.items())
                        or [h["valid_at"] for h in result["hours"]] != expected
                        or any(not math.isfinite(h["power_norm"]) or not 0 <= h["power_norm"] <= 1
                               for h in result["hours"])
                        or provenance["provenance_status"] != ("verified" if mode == "archive" else "fixture")
                        or utc_time(provenance["initialized_at"]) > utc_time(provenance["available_at"])
                        or utc_time(provenance["available_at"]) > utc_time(origin)
                        or utc_time(result["train_last_interval_start"]) + timedelta(hours=1) > utc_time(FIRST_ORIGIN)):
                    raise ValueError("Replay result violates identity, chronology, coverage or power bounds")
                exported = list(csv.DictReader(io.StringIO(forecast_csv(result))))
                if len(exported) != 48:
                    raise ValueError("Replay output must contain exactly 48 rows per run")
                rows.extend(exported)
                runs.append({**request, "fingerprint": result["fingerprint"], "model_id": result["model_id"],
                             "model_input": result["model_input"], "weather_provenance": provenance})
            except Exception:
                # Internal paths/provider responses do not belong in the handoff report.
                failures.append({**request, "code": "REPLAY_INVALID", "message": "Расчёт не прошёл проверку replay"})
    unique = {(r["turbine_id"], r["origin"], r["valid_at"]) for r in rows}
    if len(unique) != len(rows):
        raise ValueError("Duplicate replay identities")
    complete = not failures and len(rows) == days * len(SITE_IDS) * 48
    submission_ready = complete and mode == "archive" and days == 28
    # Always distinguish diagnostic subsets and partial output from the full submission.
    filename = "forecast.csv" if submission_ready else "partial_forecast.csv"
    obsolete = output_dir / ("partial_forecast.csv" if submission_ready else "forecast.csv")
    if obsolete.exists():
        obsolete.unlink()
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    _atomic_write(output_dir / filename, stream.getvalue())
    report = {"status": "ok" if complete else "incomplete", "mode": mode,
              "full_february_replay": submission_ready, "truth_scored": False,
              "expected_runs": days * len(SITE_IDS), "completed_runs": len(runs),
              "expected_rows": days * len(SITE_IDS) * 48, "actual_rows": len(rows),
              "march_spillover_rows": sum(r["valid_at"] >= "2026-02-28T19:00:00Z" for r in rows),
              "output_file": filename, "runs": runs, "failures": failures,
              "limitations": ["Февральские метрики не рассчитаны: фактическая выработка отсутствует.",
                               "Формат итоговой сдачи должен быть сверён с требованиями организаторов."]}
    _atomic_write(output_dir / "report.json", json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("archive", "fixture"), default="archive")
    parser.add_argument("--days", type=int, default=28, help="Use 2 for a fixture rehearsal; full replay requires 28")
    parser.add_argument("--output-dir", type=Path, default=artifact_dir() / "replay")
    args = parser.parse_args()
    result = run_replay(args.output_dir, mode=args.mode, days=args.days)
    print(json.dumps({key: result[key] for key in ("status", "full_february_replay", "completed_runs",
                                                  "expected_runs", "actual_rows", "output_file")}, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
