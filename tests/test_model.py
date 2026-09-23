import numpy as np
import pandas as pd
import pytest

from contracts import FIRST_ORIGIN, ForecastError
from model import predict_power, train_model


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
    with pytest.raises(ForecastError, match="Duplicate"):
        train_model(duplicate, FIRST_ORIGIN, "T2")


def test_model_requires_meaningful_history():
    with pytest.raises(ForecastError, match="at least 24"):
        train_model(training_history().iloc[:5], FIRST_ORIGIN, "T2")
