"""Fast deterministic inference smoke check for locally trained artifacts.

This is a wiring and output-contract check. Its synthetic weather is not
historical weather and its report makes no forecasting accuracy claim.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import numpy as np

import model
from contracts import FEATURES


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODELS_DIR = ROOT / "artifacts" / "models"
DEFAULT_OUTPUT = ROOT / "artifacts" / "training" / "smoke_report.json"
ORIGINS = ("2026-01-31T18:00:00Z", "2026-02-01T18:00:00Z")
HORIZONS = (24, 48)


def _weather_rows(origin: str, horizon: int, turbine_index: int) -> list[dict[str, float]]:
    """Create stable hourly weather that does not inspect any target data."""
    start = datetime.fromisoformat(origin.replace("Z", "+00:00"))
    rows = []
    for lead in range(1, horizon + 1):
        valid_at = start + timedelta(hours=lead)
        # Bounded, smoothly varying fixture values; turbine index only makes
        # the two deterministic request streams distinct.
        phase = (valid_at.timetuple().tm_yday * 24 + valid_at.hour + turbine_index * 7) / 11
        rows.append({
            "valid_at": valid_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "wind_speed_ms": round(5.5 + 2.2 * np.sin(phase), 6),
            "temperature_c": round(-2.0 + 4.5 * np.cos(phase / 2), 6),
        })
    return rows


def run(models_dir: Path) -> dict:
    latest_path = models_dir / "latest.json"
    try:
        index = json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read model index {latest_path}: {exc}") from exc
    if not isinstance(index, dict) or any(tid not in index for tid in ("T1", "T2")):
        raise RuntimeError("latest.json must map T1 and T2 to artifact directory paths")

    loaded = {}
    for turbine_id in ("T1", "T2"):
        artifact = Path(index[turbine_id])
        if not artifact.is_absolute():
            artifact = ROOT / artifact
        bundle = model.load_model(artifact)
        if bundle.metadata.get("turbine_id") != turbine_id:
            raise RuntimeError(f"Artifact for {turbine_id} contains a different turbine identity")
        loaded[turbine_id] = bundle

    cases = []
    for turbine_index, turbine_id in enumerate(("T1", "T2")):
        bundle = loaded[turbine_id]
        for origin in ORIGINS:
            for horizon in HORIZONS:
                rows = _weather_rows(origin, horizon, turbine_index)
                if len(rows) != horizon:
                    raise RuntimeError("Synthetic weather row count mismatch")
                if any(not all(feature in row for feature in FEATURES) for row in rows):
                    raise RuntimeError("Synthetic weather is missing model features")
                first = model.predict_power(bundle, rows)
                # Reload from disk and repeat to cover artifact load and stable
                # repeated inference, without asserting learned values.
                reloaded = model.load_model(Path(index[turbine_id]) if Path(index[turbine_id]).is_absolute()
                                            else ROOT / index[turbine_id])
                repeated = model.predict_power(reloaded, rows)
                values = np.asarray(first, dtype=float)
                if values.shape != (horizon,) or not np.isfinite(values).all():
                    raise RuntimeError(f"Invalid output size or nonfinite predictions for {turbine_id}")
                if np.any((values < 0) | (values > 1)):
                    raise RuntimeError(f"Prediction outside [0, 1] for {turbine_id}")
                if first != repeated:
                    raise RuntimeError(f"Reloaded model predictions differ for {turbine_id}")
                cases.append({
                    "turbine_id": turbine_id,
                    "origin": origin,
                    "horizon_hours": horizon,
                    "prediction_count": len(first),
                    "finite_and_bounded": True,
                    "reload_repeat_equal": True,
                    "model_id": bundle.metadata["model_id"],
                })
    return {
        "status": "ok",
        "source": "synthetic_weather",
        "forecast_accuracy_claim": False,
        "cases_checked": len(cases),
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR,
                        help="Directory containing latest.json (default: artifacts/models)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="JSON report destination (default: artifacts/training/smoke_report.json)")
    args = parser.parse_args(argv)
    models_dir = args.models_dir if args.models_dir.is_absolute() else ROOT / args.models_dir
    output = args.output if args.output.is_absolute() else ROOT / args.output
    try:
        report = run(models_dir)
    except Exception as exc:
        print(f"smoke_model: {exc}", file=sys.stderr)
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Passed {report['cases_checked']} smoke cases; report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
