import numpy as np
import pandas as pd
import pytest

from backend.core.contracts import FIRST_ORIGIN, ForecastError
from backend.ml.model import load_model, predict_power, save_model, train_model


def training_history():
    stamps = pd.date_range("2026-01-28T00:00:00Z", "2026-02-02T00:00:00Z", freq="h")
    wind = 5 + 2 * np.sin(np.arange(len(stamps)) / 5)
    return pd.DataFrame({"turbine_id": "T2", "timestamp": stamps, "wind_speed_ms": wind,
                         "temperature_c": -2.0, "power_norm": wind / 12})


def test_completed_hour_cutoff_and_future_data_cannot_change_model():
    history = training_history()
    fitted = train_model(history, FIRST_ORIGIN, "T2")
    assert fitted.metadata["train_last_interval_start"] == "2026-01-31T17:00:00Z"
    future = history["timestamp"] >= pd.Timestamp(FIRST_ORIGIN)
    history.loc[future, ["wind_speed_ms", "temperature_c", "power_norm"]] = [999.0, 80.0, 1.0]
    other = train_model(history, "2026-02-02T18:00:00Z", "T2")
    assert fitted.metadata["model_id"] == other.metadata["model_id"]
    rows = [{"wind_speed_ms": 6.0, "temperature_c": -3.0}] * 48
    assert predict_power(fitted, rows) == predict_power(other, rows)
    assert np.isfinite(predict_power(fitted, rows)).all()


def test_duplicate_canonical_hours_rejected():
    history = training_history()
    duplicate = pd.concat([history, history.iloc[:1]], ignore_index=True)
    with pytest.raises(ForecastError, match="повторяющиеся"):
        train_model(duplicate, FIRST_ORIGIN, "T2")


def test_model_requires_meaningful_history():
    with pytest.raises(ForecastError, match="не менее 24"):
        train_model(training_history().iloc[:5], FIRST_ORIGIN, "T2")


def test_versioned_artifact_loads_by_turbine_and_rejects_corruption(monkeypatch, tmp_path):
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    fitted = train_model(training_history(), FIRST_ORIGIN, "T2")
    artifact = save_model(fitted)
    loaded = load_model("T2")
    assert loaded.metadata["model_id"] == fitted.metadata["model_id"]
    assert loaded.metadata["train_origin"] == FIRST_ORIGIN
    assert loaded.metadata["train_last_interval_start"] == "2026-01-31T17:00:00Z"
    assert loaded.metadata["features"] == ["wind_speed_ms", "temperature_c"]
    rows = [{"wind_speed_ms": 6.0, "temperature_c": -3.0}] * 24
    assert predict_power(loaded, rows) == predict_power(fitted, rows)
    with pytest.raises(ForecastError, match="Реестр"):
        load_model("T1")
    (artifact / "model.pkl").write_bytes(b"corrupt model")
    with pytest.raises(ForecastError, match="Артефакт"):
        load_model("T2")
