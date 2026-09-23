"""Local per-turbine regression. No UI, weather transport or paid inference."""
from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from contracts import FEATURES, FIRST_ORIGIN, SITE_IDS, ForecastError, artifact_dir, fingerprint, utc_time

PARAMS = {"max_iter": 100, "max_leaf_nodes": 15, "random_state": 42}


@dataclass
class PowerModel:
    estimator: HistGradientBoostingRegressor
    metadata: dict


def train_model(history: pd.DataFrame, origin: str, turbine_id: str) -> PowerModel:
    cutoff = min(utc_time(origin), utc_time(FIRST_ORIGIN))
    selected = history.loc[history["turbine_id"].eq(turbine_id)].copy()
    selected["timestamp"] = pd.to_datetime(selected["timestamp"], utc=True)
    selected = selected.loc[selected["timestamp"] + pd.Timedelta(hours=1) <= cutoff].sort_values("timestamp")
    if selected["timestamp"].duplicated().any():
        raise ForecastError("DATA_INVALID", "Duplicate canonical training hours.")
    values = selected[FEATURES + ["power_norm"]].to_numpy(dtype=float)
    if len(selected) < 24 or not np.isfinite(values).all():
        raise ForecastError("DATA_INVALID", "Training needs at least 24 complete, finite historical hours.")
    if not selected["power_norm"].between(0, 1).all() or not selected["wind_speed_ms"].ge(0).all():
        raise ForecastError("DATA_INVALID", "Training values violate normalized-power/wind units.")
    identity_rows = selected[["timestamp", *FEATURES, "power_norm"]].copy()
    identity_rows["timestamp"] = identity_rows["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    identity = fingerprint({"turbine_id": turbine_id, "rows": identity_rows.to_dict("records"),
                            "features": FEATURES, "params": PARAMS, "cutoff": cutoff.isoformat(),
                            "sklearn": sklearn.__version__})
    estimator = HistGradientBoostingRegressor(**PARAMS)
    with threadpool_limits(limits=1):
        estimator.fit(selected[FEATURES], selected["power_norm"])
    metadata = {
        "turbine_id": turbine_id, "model_id": identity,
        "train_origin": cutoff.isoformat().replace("+00:00", "Z"),
        "train_last_interval_start": identity_rows.iloc[-1]["timestamp"],
        "training_rows": len(selected), "features": FEATURES, "params": PARAMS,
        "baseline_norm": float(selected.iloc[-1]["power_norm"]),
        "training_source": "supplied turbine measurements",
        "sklearn_version": sklearn.__version__,
    }
    return PowerModel(estimator, metadata)


def predict_power(model: PowerModel, weather_rows: list[dict]) -> list[float]:
    features = pd.DataFrame(weather_rows)[FEATURES].astype(float)
    if not np.isfinite(features.to_numpy()).all():
        raise ForecastError("DATA_INVALID", "Prediction features must be finite.")
    with threadpool_limits(limits=1):
        return model.estimator.predict(features).tolist()


def predict_power_csv(model: PowerModel, csv_path: Path, *, turbine_id: str, origin: str,
                      horizon_hours: int, expected_sha256: str) -> list[float]:
    """Primary inference interface. Predictions are computed from the actual CSV file."""
    from model_input import read_model_input
    if model.metadata["turbine_id"] != turbine_id:
        raise ForecastError("MODEL_UNAVAILABLE", "Input CSV turbine does not match the fitted model.")
    rows = read_model_input(csv_path, turbine_id=turbine_id, origin=origin,
                            horizon_hours=horizon_hours, expected_sha256=expected_sha256)
    return predict_power(model, rows)


def save_model(model: PowerModel) -> None:
    directory = artifact_dir() / "models"
    directory.mkdir(parents=True, exist_ok=True)
    site = model.metadata["turbine_id"]
    (directory / f"{site}.pkl").write_bytes(pickle.dumps(model))
    (directory / f"{site}.json").write_text(json.dumps(model.metadata, indent=2))


def load_model(turbine_id: str) -> PowerModel:
    if turbine_id not in SITE_IDS:
        raise ForecastError("INVALID_INPUT", "Unknown turbine model.")
    path = artifact_dir() / "models" / f"{turbine_id}.pkl"
    try:
        # Only locally trained artifacts are accepted; never accept uploaded pickle files.
        fitted = pickle.loads(path.read_bytes())
    except (OSError, pickle.UnpicklingError, EOFError, AttributeError, ImportError, ValueError) as exc:
        raise ForecastError("MODEL_UNAVAILABLE", "Run python -m scripts.train --mode fixture first.") from exc
    if not isinstance(fitted, PowerModel) or fitted.metadata["turbine_id"] != turbine_id:
        raise ForecastError("MODEL_UNAVAILABLE", "Model artifact does not match the selected turbine.")
    return fitted
