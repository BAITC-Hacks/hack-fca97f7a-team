"""One-command February 2026 operational forecast handoff.

Acquires original ECMWF weather, runs frozen power models for 28 daily issues,
audits chronology and input/output coverage, and optionally packages the result.
No model training, LLM request, or actual February weather is involved.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from backend.adapters.operational_weather import cache_dir
from backend.core.contracts import artifact_dir
from scripts.audit_february import audit
from scripts.package_operational_replay import package_operational_replay
from scripts.replay import _atomic_write, run_replay


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-only", action="store_true",
                        help="Validate already downloaded operational GRIB, without network")
    parser.add_argument("--workers", type=int, default=4,
                        help="Parallel source-download worker groups, 1..4")
    parser.add_argument("--output-dir", type=Path,
                        default=artifact_dir() / "february_operational")
    parser.add_argument("--package-dir", type=Path,
                        help="Optional new directory for a compact, checked submission kit")
    args = parser.parse_args()
    if not 1 <= args.workers <= 4:
        parser.error("--workers must be 1..4")
    command = [sys.executable, "-m", "scripts.fetch_operational_weather",
               "--days", "28", "--workers", str(args.workers)]
    # Replay itself verifies every cached raw dependency before inference.
    # Avoid decoding all 28 runs twice for an explicitly offline replay.
    if not args.cache_only and subprocess.run(command, check=False).returncode:
        print("Не удалось подтвердить все 28 архивных погодных выпусков ECMWF.", file=sys.stderr)
        return 2

    report = run_replay(args.output_dir, mode="archive", days=28,
                        weather_source="operational")
    if report["status"] != "ok" or report["full_february_replay"] is not True:
        print(json.dumps({"status": "incomplete", "completed_runs": report["completed_runs"],
                          "expected_runs": report["expected_runs"]}, ensure_ascii=False))
        return 2

    checked = audit(args.output_dir, artifact_dir() / "model_inputs", cache_dir())
    _atomic_write(args.output_dir / "audit.json",
                  json.dumps(checked, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    if checked["status"] != "ok":
        print(json.dumps({"status": "incomplete", "audit_failed": [item["check"] for item in checked["checks"]
                          if not item["passed"]]}, ensure_ascii=False))
        return 2

    packaged = None
    if args.package_dir is not None:
        manifest = package_operational_replay(args.output_dir, args.package_dir,
                                              source_artifacts=artifact_dir())
        packaged = {"path": str(args.package_dir), "files": len(manifest["files"])}
    print(json.dumps({"status": "ok", "weather_origins": 28,
                      "forecast_runs": report["completed_runs"],
                      "forecast_rows": report["actual_rows"],
                      "daily_rows": report["daily_rows"],
                      "historical_availability_verified": report["historical_availability_verified"],
                      "truth_scored": report["truth_scored"],
                      "output_dir": str(args.output_dir), "package": packaged}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
