"""Per-turbine, frozen hourly power model and local artifact handling."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import pickle
from pathlib import Path
import platform

import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from contracts import FEATURES, FIRST_ORIGIN, ForecastError, validate_origin


_PARAMETERS = {"max_iter": 100, "max_leaf_nodes": 15, "random_state": 42}
_SCHEMA = 1
_IMPLEMENTATION = "hourly-hgbr-v1"
_UNITS = {"wind_speed_ms": "m/s", "temperature_c": "degC"}


@dataclass
class ModelBundle:
    estimator: HistGradientBoostingRegressor
    metadata: dict


def _iso(value: pd.Timestamp) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def _canonical_rows(frame: pd.DataFrame) -> bytes:
    """Stable bytes for precisely the sorted rows used by fit."""
    lines = []
    for row in frame.itertuples(index=False):
        lines.append(json.dumps(
            [_iso(row.timestamp), *[float(getattr(row, name)).hex() for name in FEATURES],
             float(row.power_norm).hex()],
            separators=(",", ":"),
        ))
    return ("\n".join(lines) + "\n").encode("ascii")


def train_model(history: pd.DataFrame, origin: str, turbine_id: str) -> ModelBundle:
    """Fit one turbine using only hours completed by both cutoffs."""
    if turbine_id not in {"T1", "T2"}:
        raise ForecastError("INVALID_INPUT", "Unknown turbine ID")
    requested_cutoff = validate_origin(origin)
    frozen_cutoff = validate_origin(FIRST_ORIGIN)
    cutoff = pd.Timestamp(min(requested_cutoff, frozen_cutoff))
    required = {"turbine_id", "timestamp", *FEATURES, "power_norm"}
    if not isinstance(history, pd.DataFrame) or not required.issubset(history.columns):
        raise ForecastError("DATA_INVALID", "Canonical history is missing required columns")
    selected = history.loc[history["turbine_id"] == turbine_id,
                           ["timestamp", *FEATURES, "power_norm"]].copy()
    if selected.empty:
        raise ForecastError("DATA_INVALID", f"No history for {turbine_id}")
    try:
        stamps = [pd.Timestamp(value) for value in selected["timestamp"]]
    except (ValueError, TypeError, OverflowError) as exc:
        raise ForecastError("DATA_INVALID", "Invalid history timestamp") from exc
    if any(pd.isna(stamp) or stamp.tzinfo is None or stamp.utcoffset() is None
           for stamp in stamps):
        raise ForecastError("DATA_INVALID", "History timestamps must be timezone-aware")
    selected["timestamp"] = pd.DatetimeIndex([stamp.tz_convert("UTC") for stamp in stamps])
    if any(stamp.minute or stamp.second or stamp.microsecond or stamp.nanosecond
           for stamp in selected["timestamp"]):
        raise ForecastError("DATA_INVALID", "History timestamps must start on exact UTC hours")
    selected = selected.loc[selected["timestamp"] + pd.Timedelta(hours=1) <= cutoff]
    selected = selected.sort_values("timestamp", kind="stable").reset_index(drop=True)
    if selected.empty:
        raise ForecastError("DATA_INVALID", "No complete hours before training cutoff")
    if selected["timestamp"].duplicated().any():
        raise ForecastError("DATA_INVALID", "Duplicate hourly timestamps")
    try:
        numeric = selected[[*FEATURES, "power_norm"]].apply(pd.to_numeric, errors="raise")
    except (ValueError, TypeError) as exc:
        raise ForecastError("DATA_INVALID", "Nonnumeric training feature or label") from exc
    values = numeric.to_numpy(dtype=float)
    if not np.isfinite(values).all() or np.any(values[:, 0] < 0):
        raise ForecastError("DATA_INVALID", "Training features or labels are invalid")
    if np.any((values[:, -1] < 0) | (values[:, -1] > 1)):
        raise ForecastError("DATA_INVALID", "Normalized power must be in [0, 1]")
    selected[[*FEATURES, "power_norm"]] = numeric
    canonical_sha = _digest(_canonical_rows(selected))
    identity = {
        "implementation": _IMPLEMENTATION,
        "turbine_id": turbine_id,
        "cutoff": _iso(cutoff),
        "canonical_sha256": canonical_sha,
        "feature_names": list(FEATURES),
        "parameters": _PARAMETERS,
        "python_version": platform.python_version(),
        "library_versions": {"numpy": np.__version__, "pandas": pd.__version__,
                             "scikit_learn": sklearn.__version__},
    }
    model_id = "sha256:" + _digest(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode())
    estimator = HistGradientBoostingRegressor(**_PARAMETERS)
    with threadpool_limits(limits=1):
        estimator.fit(values[:, :len(FEATURES)], values[:, -1])
    last = selected.iloc[-1]
    metadata = {
        "artifact_schema_version": _SCHEMA,
        "model_id": model_id,
        "turbine_id": turbine_id,
        "estimator": "HistGradientBoostingRegressor",
        "parameters": _PARAMETERS.copy(),
        "feature_names": list(FEATURES),
        "feature_units": _UNITS.copy(),
        "target": "power_norm",
        "target_unit": "normalized_fraction",
        "train_cutoff": _iso(cutoff),
        "train_last_interval_start": _iso(last.timestamp),
        "training_rows": len(selected),
        "source_sha256": None,
        "canonical_sha256": canonical_sha,
        "artifact_sha256": None,
        "timezone_assumption": "Asia/Almaty",
        "interval_semantics": "source timestamps are ten-minute interval starts; hourly timestamps are starts",
        "aggregation_policy": "six distinct ten-minute intervals per complete hour; arithmetic mean",
        "baseline_norm": float(last.power_norm),
        "baseline_interval_start": _iso(last.timestamp),
        "python_version": identity["python_version"],
        "library_versions": identity["library_versions"],
        "validation": None,
        "implementation": _IMPLEMENTATION,
    }
    return ModelBundle(estimator, metadata)


def predict_with_diagnostics(model: ModelBundle, weather_rows: list[dict]) -> tuple[list[float], int]:
    if not isinstance(model, ModelBundle) or not isinstance(model.estimator, HistGradientBoostingRegressor):
        raise ForecastError("MODEL_UNAVAILABLE", "Invalid model bundle")
    if model.metadata.get("feature_names") != list(FEATURES):
        raise ForecastError("MODEL_UNAVAILABLE", "Model feature order mismatch")
    if not isinstance(weather_rows, list) or not weather_rows:
        raise ForecastError("INVALID_INPUT", "Weather rows are required")
    features = []
    for row in weather_rows:
        if not isinstance(row, dict) or any(name not in row for name in FEATURES):
            raise ForecastError("DATA_INVALID", "Weather feature is missing")
        try:
            wind, temp = (float(row[name]) for name in FEATURES)
        except (TypeError, ValueError) as exc:
            raise ForecastError("DATA_INVALID", "Weather feature is nonnumeric") from exc
        if not np.isfinite(wind) or not np.isfinite(temp) or wind < 0:
            raise ForecastError("DATA_INVALID", "Weather feature is nonfinite or wind is negative")
        features.append((wind, temp))
    with threadpool_limits(limits=1):
        raw = np.asarray(model.estimator.predict(np.asarray(features, dtype=float)), dtype=float)
    if raw.shape != (len(features),) or not np.isfinite(raw).all():
        raise ForecastError("DATA_INVALID", "Model produced invalid predictions")
    clipped_count = int(np.count_nonzero((raw < 0) | (raw > 1)))
    return np.clip(raw, 0, 1).tolist(), clipped_count


def predict_power(model: ModelBundle, weather_rows: list[dict]) -> list[float]:
    return predict_with_diagnostics(model, weather_rows)[0]


def save_model(bundle: ModelBundle, output_root: str | Path) -> Path:
    """Write a versioned artifact; callers supply only a trusted local output root."""
    metadata = bundle.metadata.copy()
    turbine_id = metadata.get("turbine_id")
    model_id = metadata.get("model_id", "")
    if turbine_id not in {"T1", "T2"} or not isinstance(model_id, str) or not model_id.startswith("sha256:"):
        raise ForecastError("MODEL_UNAVAILABLE", "Invalid model identity")
    artifact_dir = Path(output_root) / turbine_id / model_id.removeprefix("sha256:")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    binary = pickle.dumps(bundle.estimator, protocol=pickle.HIGHEST_PROTOCOL)
    metadata["artifact_sha256"] = _digest(binary)
    (artifact_dir / "model.pkl").write_bytes(binary)
    (artifact_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    bundle.metadata["artifact_sha256"] = metadata["artifact_sha256"]
    return artifact_dir


def load_model(artifact_dir: str | Path) -> ModelBundle:
    """Load only a trusted locally generated artifact selected by the server."""
    path = Path(artifact_dir)
    try:
        metadata = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
        binary = (path / "model.pkl").read_bytes()
        if metadata.get("artifact_schema_version") != _SCHEMA:
            raise ValueError("artifact schema")
        model_id = metadata.get("model_id")
        identity = {
            "implementation": metadata.get("implementation"),
            "turbine_id": metadata.get("turbine_id"),
            "cutoff": metadata.get("train_cutoff"),
            "canonical_sha256": metadata.get("canonical_sha256"),
            "feature_names": metadata.get("feature_names"),
            "parameters": metadata.get("parameters"),
            "python_version": metadata.get("python_version"),
            "library_versions": metadata.get("library_versions"),
        }
        expected_id = "sha256:" + _digest(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode())
        saved_python = str(metadata.get("python_version", "")).split(".")[:2]
        running_python = platform.python_version().split(".")[:2]
        if (metadata.get("turbine_id") not in {"T1", "T2"}
                or not isinstance(model_id, str)
                or model_id != expected_id
                or path.name != model_id.removeprefix("sha256:")
                or path.parent.name != metadata["turbine_id"]
                or saved_python != running_python
                or metadata.get("library_versions", {}).get("scikit_learn") != sklearn.__version__
                or metadata.get("feature_names") != list(FEATURES)
                or metadata.get("feature_units") != _UNITS
                or metadata.get("estimator") != "HistGradientBoostingRegressor"
                or metadata.get("parameters") != _PARAMETERS
                or metadata.get("artifact_sha256") != _digest(binary)):
            raise ValueError("artifact identity or checksum")
        estimator = pickle.loads(binary)
        if not isinstance(estimator, HistGradientBoostingRegressor) or not hasattr(estimator, "n_features_in_") or estimator.n_features_in_ != len(FEATURES):
            raise ValueError("estimator incompatible")
        return ModelBundle(estimator, metadata)
    except (OSError, ValueError, TypeError, KeyError, pickle.UnpicklingError, AttributeError) as exc:
        raise ForecastError("MODEL_UNAVAILABLE", f"Model artifact unavailable or invalid: {exc}") from exc
