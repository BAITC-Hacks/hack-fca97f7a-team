import hashlib
import pickle

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import HistGradientBoostingRegressor

from backend.core.contracts import FIRST_ORIGIN, ForecastError, artifact_dir
from backend.ml.model_input import COLUMNS, read_model_input, write_model_input
from backend.adapters.weather import fetch_weather, load_sites


@pytest.fixture
def csv_input(monkeypatch, tmp_path):
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    rows = fetch_weather(load_sites()[1], FIRST_ORIGIN, 48, "fixture")["rows"]
    metadata = write_model_input(rows, "T2", FIRST_ORIGIN, 48)
    path = artifact_dir() / "model_inputs" / metadata["filename"]
    return rows, metadata, path


def test_weather_written_and_read_as_exact_model_csv(csv_input):
    rows, metadata, path = csv_input
    assert path.read_text().splitlines()[0] == ",".join(COLUMNS)
    assert len(path.read_text().splitlines()) == 49
    parsed = read_model_input(path, turbine_id="T2", origin=FIRST_ORIGIN,
                              horizon_hours=48, expected_sha256=metadata["sha256"])
    assert [{k: v for k, v in row.items() if k != "turbine_id"} for row in parsed] == rows
    assert write_model_input(rows, "T2", FIRST_ORIGIN, 48) == metadata


def test_csv_mutation_rejected(csv_input):
    _, metadata, path = csv_input
    path.write_text(path.read_text().replace("T2", "T1"))
    with pytest.raises(ForecastError, match="checksum"):
        read_model_input(path, turbine_id="T2", origin=FIRST_ORIGIN,
                         horizon_hours=48, expected_sha256=metadata["sha256"])
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ForecastError, match="identity"):
        read_model_input(path, turbine_id="T2", origin=FIRST_ORIGIN,
                         horizon_hours=48, expected_sha256=digest)


def test_csv_is_required_by_prediction(csv_input, monkeypatch):
    from backend.ml.model import load_model, predict_power_csv
    _, metadata, path = csv_input
    with monkeypatch.context() as original_artifacts:
        original_artifacts.delenv("ARTIFACT_DIR", raising=False)
        fitted = load_model("T2")
    predictions = predict_power_csv(fitted, path, turbine_id="T2", origin=FIRST_ORIGIN,
                                    horizon_hours=48, expected_sha256=metadata["sha256"])
    assert len(predictions) == 48
    path.unlink()
    with pytest.raises(ForecastError, match="Cannot read"):
        predict_power_csv(fitted, path, turbine_id="T2", origin=FIRST_ORIGIN,
                          horizon_hours=48, expected_sha256=metadata["sha256"])


def test_legacy_flat_artifact_remains_usable_through_csv(csv_input, monkeypatch, tmp_path):
    from backend.ml.model import PowerModel, load_model, predict_power_csv
    _, metadata, path = csv_input
    legacy_root = tmp_path / "legacy"
    models_dir = legacy_root / "models"
    models_dir.mkdir(parents=True)
    features = pd.DataFrame({"wind_speed_ms": np.linspace(2, 12, 30),
                             "temperature_c": np.linspace(-5, 5, 30)})
    estimator = HistGradientBoostingRegressor(max_iter=100, max_leaf_nodes=15, random_state=42)
    estimator.fit(features, np.linspace(0, 1, 30))
    legacy = PowerModel(estimator, {
        "turbine_id": "T2", "model_id": "sha256:legacy", "features": ["wind_speed_ms", "temperature_c"],
        "train_origin": FIRST_ORIGIN, "train_last_interval_start": "2026-01-31T17:00:00Z",
        "baseline_norm": 0.3, "sklearn_version": __import__("sklearn").__version__,
    })
    (models_dir / "T2.pkl").write_bytes(pickle.dumps(legacy))
    monkeypatch.setenv("ARTIFACT_DIR", str(legacy_root))
    loaded = load_model("T2")
    assert loaded.metadata["feature_names"] == ["wind_speed_ms", "temperature_c"]
    predicted = predict_power_csv(loaded, path, turbine_id="T2", origin=FIRST_ORIGIN,
                                  horizon_hours=48, expected_sha256=metadata["sha256"])
    assert len(predicted) == 48 and np.isfinite(predicted).all()
