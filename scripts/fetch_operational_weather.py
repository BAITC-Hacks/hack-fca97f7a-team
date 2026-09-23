"""Fetch original ECMWF IFS operational GRIB fields for February 2026 replay."""
from __future__ import annotations

import argparse
import json

from backend.adapters.operational_weather import prepare_operational_weather


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=28, help="Daily issues from 31 January (1..28)")
    parser.add_argument("--start-day", type=int, default=0, help="Zero-based starting daily issue (0..27)")
    args = parser.parse_args()
    report = prepare_operational_weather(days=args.days, start_day=args.start_day)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
