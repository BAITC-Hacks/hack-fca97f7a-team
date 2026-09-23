from hashlib import sha256
import json

import numpy as np
import pandas as pd
import pytest

from contracts import FIRST_ORIGIN, ForecastError
from model import DEFAULT_VARIANT, MODEL_VARIANTS, load_model, predict_power, save_model, train_model


def training_history():
    stamps = pd.date_range("2026-01-28T00:00:00Z", "2026-02-02T00:00:00Z", freq="h")
    wind = 5 + 2 * np.sin(np.arange(len(stamps)) / 5)
    return pd.DataFrame({"turbine_id": "T2", "timestamp": stamps, "wind_speed_ms": wind,
                         "temperature_c": -2.0, "power_norm": wind / 12})


@pytest.mark.parametrize("variant", MODEL_VARIANTS)
def test_completed_hour_cutoff_and_future_data_cannot_change_model(variant):
    history = training_history()
    fitted = train_model(history, FIRST_ORIGIN, "T2", variant=variant)
    assert fitted.metadata["train_last_interval_start"] == "2026-01-31T17:00:00Z"
    future = history["timestamp"] >= pd.Timestamp(FIRST_ORIGIN)
    history.loc[future, ["wind_speed_ms", "temperature_c", "power_norm"]] = [999.0, 80.0, 1.0]
    other = train_model(history, "2026-02-02T18:00:00Z", "T2", variant=variant)
    assert fitted.metadata["model_id"] == other.metadata["model_id"]
    rows = [{"wind_speed_ms": 6.0, "temperature_c": -3.0}] * 48
    assert predict_power(fitted, rows) == predict_power(other, rows)
    assert np.isfinite(predict_power(fitted, rows)).all()


def test_model_variants_have_distinct_implementation_parameters_and_identity():
    history = training_history()
    baseline = train_model(history, FIRST_ORIGIN, "T2", variant="baseline")
    candidate = train_model(history, FIRST_ORIGIN, "T2", variant="candidate")
    default = train_model(history, FIRST_ORIGIN, "T2")

    assert DEFAULT_VARIANT == "candidate"
    assert default.metadata["model_id"] == candidate.metadata["model_id"]
    assert baseline.metadata["model_id"] != candidate.metadata["model_id"]
    assert baseline.metadata["implementation"] == "hourly-hgbr-v1"
    assert baseline.metadata["parameters"] == {
        "max_iter": 100, "max_leaf_nodes": 15, "random_state": 42,
    }
    assert candidate.metadata["implementation"] == "hourly-hgbr-v2"
    assert candidate.metadata["parameters"] == {
        "loss": "absolute_error", "max_iter": 300, "learning_rate": 0.04,
        "max_leaf_nodes": 15, "min_samples_leaf": 40, "l2_regularization": 1.0,
        "early_stopping": False, "random_state": 42,
    }
    assert baseline.estimator.get_params()["loss"] == "squared_error"
    assert candidate.estimator.get_params()["loss"] == "absolute_error"
    v1_identity = {
        "implementation": "hourly-hgbr-v1",
        "turbine_id": "T2",
        "cutoff": baseline.metadata["train_cutoff"],
        "canonical_sha256": baseline.metadata["canonical_sha256"],
        "feature_names": baseline.metadata["feature_names"],
        "parameters": baseline.metadata["parameters"],
        "python_version": baseline.metadata["python_version"],
        "library_versions": baseline.metadata["library_versions"],
    }
    digest = sha256(json.dumps(v1_identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert baseline.metadata["model_id"] == f"sha256:{digest}"
    assert train_model(history, FIRST_ORIGIN, "T2", variant=None).metadata["model_id"] == candidate.metadata["model_id"]
    with pytest.raises(ForecastError) as error:
        train_model(history, FIRST_ORIGIN, "T2", variant="unknown")
    assert error.value.code == "INVALID_INPUT"


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
