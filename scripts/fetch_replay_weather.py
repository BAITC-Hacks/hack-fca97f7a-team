"""Cache Open-Meteo Single Runs for a conditional February 2026 replay."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.adapters.replay_weather import cache_dir, prepare_replay_weather


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=28, choices=range(1, 29), metavar="1..28")
    parser.add_argument("--cache-only", action="store_true", help="Check cache without network requests")
    parser.add_argument("--output-dir", type=Path, default=cache_dir())
    args = parser.parse_args()
    report = prepare_replay_weather(args.output_dir, days=args.days, cache_only=args.cache_only)
    print(json.dumps({"status": report["status"], "cached_runs": report["cached_runs"],
                      "expected_runs": report["expected_runs"], "downloads": report["downloads"],
                      "failures": len(report["failures"]), "cache_dir": str(args.output_dir),
                      "availability_verified": False}, ensure_ascii=False))
    return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
