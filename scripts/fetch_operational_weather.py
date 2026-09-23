"""Fetch original ECMWF IFS operational GRIB fields for February 2026 replay."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from backend.adapters.operational_weather import cache_dir, prepare_operational_weather


def _chunk(start_day: int, days: int, cache_only: bool = False) -> dict:
    return prepare_operational_weather(start_day=start_day, days=days,
                                       cache_only=cache_only)


def _write_report(report: dict) -> None:
    root = cache_dir()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=root,
                                     prefix=".fetch-report-", delete=False) as stream:
        json.dump(report, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
        temporary = Path(stream.name)
    try:
        os.replace(temporary, root / "fetch_report.json")
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=28, help="Daily issues from 31 January (1..28)")
    parser.add_argument("--start-day", type=int, default=0, help="Zero-based starting daily issue (0..27)")
    parser.add_argument("--cache-only", action="store_true", help="Validate existing receipts without network")
    parser.add_argument("--workers", type=int, default=4, help="Parallel day groups for download (1..4)")
    args = parser.parse_args()
    if not 1 <= args.workers <= 4:
        parser.error("--workers must be 1..4")
    if not 1 <= args.days <= 28 or not 0 <= args.start_day < 28 or args.start_day + args.days > 28:
        parser.error("--start-day and --days must select 1..28 daily issues")
    worker_count = 1 if args.cache_only else min(args.workers, args.days)
    quotient, remainder = divmod(args.days, worker_count)
    ranges = []
    next_day = args.start_day
    for index in range(worker_count):
        count = quotient + (index < remainder)
        ranges.append((next_day, count))
        next_day += count
    if worker_count == 1:
        parts = [_chunk(*ranges[0], cache_only=args.cache_only)]
    else:
        with ProcessPoolExecutor(max_workers=worker_count) as pool:
            parts = list(pool.map(_chunk, (item[0] for item in ranges),
                                  (item[1] for item in ranges)))
    completed = sorted(origin for part in parts for origin in part["completed_origins"])
    failures = sorted((failure for part in parts for failure in part["failures"]),
                      key=lambda item: item["origin"])
    report = {"status": "ok" if not failures and len(completed) == args.days else "incomplete",
              "completed_days": len(completed), "expected_days": args.days,
              "completed_origins": completed, "failures": failures,
              "source": parts[0]["source"],
              "availability_basis": parts[0]["availability_basis"]}
    _write_report(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
