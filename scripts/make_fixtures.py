"""Generate reproducible synthetic weather for the two demo origins and sites."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import timedelta

from backend.core.contracts import fixture_dir, iso, utc_time
from backend.adapters.weather import SITES

RUNS = (
    ("r1", "2026-01-31T18:00:00Z", "2026-01-31T06:00:00Z", "2026-01-31T14:00:00Z"),
    ("r2", "2026-02-01T18:00:00Z", "2026-02-01T06:00:00Z", "2026-02-01T14:00:00Z"),
)


def main() -> None:
    directory = fixture_dir()
    directory.mkdir(parents=True, exist_ok=True)
    for site_index, site in enumerate(SITES):
        for run_index, (run, origin, initialized, available) in enumerate(RUNS):
            start = utc_time(origin)
            rows = []
            for lead in range(1, 49):
                phase = lead / 5.0 + site_index * 0.9 + run_index * 1.3
                rows.append({"valid_at": iso(start + timedelta(hours=lead)),
                             "wind_speed_ms": round(7.5 + 2.7 * math.sin(phase) + 0.55 * math.cos(lead / 11), 3),
                             "temperature_c": round(-4.0 + 4.2 * math.sin(lead / 9 + run_index + site_index / 3), 3)})
            raw = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
            manifest = {"turbine_id": site["turbine_id"], "run_id": f"fixture-{run}",
                        "provider": "synthetic deterministic fixture", "source_url": f"fixture://{site['turbine_id']}/{run}",
                        "retrieved_at": available, "initialized_at": initialized,
                        "available_at": available, "availability_basis": "synthetic fixture schedule",
                        "provenance_status": "fixture", "raw_sha256": hashlib.sha256(raw).hexdigest(),
                        "interpolation": "none"}
            path = directory / f"{site['turbine_id']}-{run}.json"
            path.write_text(json.dumps({"manifest": manifest, "rows": rows}, indent=2) + "\n")
            print(f"{path}: {len(rows)} synthetic hours")


if __name__ == "__main__":
    main()
