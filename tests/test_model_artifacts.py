from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import pickle

import numpy as np
import pandas as pd
import pytest

from backend.core.contracts import ForecastError
from backend.ml.model import MODEL_VARIANTS, load_model, predict_power, predict_with_diagnostics, save_model, train_model


def history() -> pd.DataFrame:
    start = datetime(2026, 1, 28, tzinfo=timezone.utc)
    rows = []
    for turbine_id in ("T1", "T2"):
        for index in range(95):
            rows.append({
                "turbine_id": turbine_id,
                "timestamp": start + timedelta(hours=index),
                "wind_speed_ms": float(index % 16),
                "temperature_c": float(index % 20 - 10),
                "power_norm": float(min(1, (index % 16) / 17 + (turbine_id == "T2") * .05)),
            })
    return pd.DataFrame(rows)


@pytest.mark.parametrize("variant", MODEL_VARIANTS)
def test_completed_hour_cutoff_and_frozen_origin(variant):
    frame = history()
    first = train_model(frame, "2026-01-31T18:00:00Z", "T1", variant=variant)
    later = train_model(frame, "2026-02-03T18:00:00Z", "T1", variant=variant)
    assert first.metadata["train_last_interval_start"] == "2026-01-31T17:00:00Z"
    assert first.metadata["training_rows"] == 90
    assert first.metadata["model_id"] == later.metadata["model_id"]
    assert first.metadata["baseline_interval_start"] == "2026-01-31T17:00:00Z"
    earlier = train_model(frame, "2026-01-31T17:00:00Z", "T1", variant=variant)
    assert earlier.metadata["training_rows"] == 89
    assert earlier.metadata["model_id"] != first.metadata["model_id"]


def test_turbine_separation_and_training_identity():
    frame = history()
    t1 = train_model(frame, "2026-01-31T18:00:00Z", "T1")
    t2 = train_model(frame, "2026-01-31T18:00:00Z", "T2")
    assert t1.metadata["model_id"] != t2.metadata["model_id"]
    changed = frame.copy()
    changed.loc[(changed.turbine_id == "T1") & (changed.timestamp == datetime(2026, 1, 29, tzinfo=timezone.utc)), "power_norm"] = .99
    revised = train_model(changed, "2026-01-31T18:00:00Z", "T1")
    assert revised.metadata["model_id"] != t1.metadata["model_id"]
    assert train_model(frame, "2026-01-31T18:00:00Z", "T1").metadata["model_id"] == t1.metadata["model_id"]


def test_prediction_validation_and_bounds():
    bundle = train_model(history(), "2026-01-31T18:00:00Z", "T1")
    rows = [{"wind_speed_ms": float(i), "temperature_c": -5.0} for i in range(24)]
    values, clipped = predict_with_diagnostics(bundle, rows)
    assert values == predict_power(bundle, rows)
    assert len(values) == 24 and all(np.isfinite(values))
    assert all(0 <= value <= 1 for value in values)
    assert clipped >= 0
    for bad in ([{"wind_speed_ms": 1.0}], [{"wind_speed_ms": np.nan, "temperature_c": 2.0}],
                [{"wind_speed_ms": -1.0, "temperature_c": 2.0}]):
        with pytest.raises(ForecastError):
            predict_power(bundle, bad)


@pytest.mark.parametrize("variant", MODEL_VARIANTS)
def test_artifact_round_trip_and_corruption(tmp_path, variant):
    bundle = train_model(history(), "2026-01-31T18:00:00Z", "T2", variant=variant)
    path = save_model(bundle, tmp_path)
    loaded = load_model(path)
    rows = [{"wind_speed_ms": 9.0, "temperature_c": -2.0}]
    assert predict_power(loaded, rows) == predict_power(bundle, rows)
    assert loaded.metadata["model_id"] == bundle.metadata["model_id"]
    assert loaded.metadata["parameters"] == bundle.metadata["parameters"]
    assert loaded.metadata["params"] == bundle.metadata["parameters"]
    (path / "model.pkl").write_bytes(b"corrupt")
    with pytest.raises(ForecastError) as error:
        load_model(path)
    assert error.value.code == "MODEL_UNAVAILABLE"


@pytest.mark.parametrize("field", ("implementation", "parameters"))
def test_unknown_metadata_configuration_rejected_even_with_recomputed_identity(tmp_path, field):
    bundle = train_model(history(), "2026-01-31T18:00:00Z", "T2")
    path = save_model(bundle, tmp_path)
    metadata_path = path / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if field == "implementation":
        metadata[field] = "hourly-hgbr-v3"
    else:
        metadata[field]["learning_rate"] = 0.05
        metadata["params"] = metadata[field].copy()
    identity = {
        "implementation": metadata["implementation"],
        "turbine_id": metadata["turbine_id"],
        "cutoff": metadata["train_cutoff"],
        "canonical_sha256": metadata["canonical_sha256"],
        "feature_names": metadata["feature_names"],
        "parameters": metadata["parameters"],
        "python_version": metadata["python_version"],
        "library_versions": metadata["library_versions"],
    }
    digest = sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    metadata["model_id"] = f"sha256:{digest}"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    tampered_path = path.rename(path.parent / digest)
    with pytest.raises(ForecastError) as error:
        load_model(tampered_path)
    assert error.value.code == "MODEL_UNAVAILABLE"


@pytest.mark.parametrize("variant", MODEL_VARIANTS)
def test_estimator_configuration_rejected_even_with_updated_checksum(tmp_path, variant):
    bundle = train_model(history(), "2026-01-31T18:00:00Z", "T2", variant=variant)
    path = save_model(bundle, tmp_path)
    model_path = path / "model.pkl"
    estimator = pickle.loads(model_path.read_bytes())
    if variant == "baseline":
        estimator.set_params(early_stopping=False)
    else:
        estimator.set_params(loss="squared_error")
    binary = pickle.dumps(estimator, protocol=pickle.HIGHEST_PROTOCOL)
    model_path.write_bytes(binary)
    metadata_path = path / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["artifact_sha256"] = sha256(binary).hexdigest()
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ForecastError) as error:
        load_model(path)
    assert error.value.code == "MODEL_UNAVAILABLE"


def test_invalid_training_rows_fail():
    frame = history()
    frame["timestamp"] = frame["timestamp"].astype(object)
    frame.loc[0, "timestamp"] = datetime(2026, 1, 28)
    with pytest.raises(ForecastError) as error:
        train_model(frame, "2026-01-31T18:00:00Z", "T1")
    assert error.value.code == "DATA_INVALID"
    frame = history()
    frame.loc[0, "timestamp"] = datetime(2026, 1, 28, 0, 30, tzinfo=timezone.utc)
    with pytest.raises(ForecastError) as error:
        train_model(frame, "2026-01-31T18:00:00Z", "T1")
    assert error.value.code == "DATA_INVALID"
    frame = history()
    frame.loc[0, "power_norm"] = 1.1
    with pytest.raises(ForecastError) as error:
        train_model(frame, "2026-01-31T18:00:00Z", "T1")
    assert error.value.code == "DATA_INVALID"
    with pytest.raises(ForecastError):
        train_model(history(), "2026-01-31T18:00:00Z", "T3")


def test_registry_load_by_turbine_and_legacy_compatibility(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    bundle = train_model(history(), "2026-01-31T18:00:00Z", "T1", variant="baseline")
    directory = tmp_path / "models"
    directory.mkdir()
    (directory / "T1.pkl").write_bytes(pickle.dumps(bundle))
    assert load_model("T1").metadata["model_id"] == bundle.metadata["model_id"]
    save_model(bundle)
    assert load_model("T1").metadata["train_origin"] == bundle.metadata["train_cutoff"]
    (directory / "latest.json").write_text('{"T1":"missing"}')
    with pytest.raises(ForecastError):
        load_model("T1")  # A broken new registry must not silently fall back.


def test_csv_inference_preserves_raw_values_for_agent_clipping(tmp_path, monkeypatch):
    from backend.core.contracts import FIRST_ORIGIN, expected_hours
    from backend.ml.model_input import write_model_input
    from backend.ml.model import predict_power_csv
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    bundle = train_model(history(), FIRST_ORIGIN, "T1")
    rows = [{"valid_at": stamp, "wind_speed_ms": 6., "temperature_c": -2.}
            for stamp in expected_hours(FIRST_ORIGIN, 24)]
    csv = write_model_input(rows, "T1", FIRST_ORIGIN, 24)
    monkeypatch.setattr(bundle.estimator, "predict", lambda values: np.array([-.2, 1.2] + [.5] * 22))
    raw = predict_power_csv(bundle, tmp_path / "model_inputs" / csv["filename"],
                            turbine_id="T1", origin=FIRST_ORIGIN, horizon_hours=24,
                            expected_sha256=csv["sha256"])
    assert raw[:2] == [-.2, 1.2]
    bounded, count = predict_with_diagnostics(bundle, rows)
    assert bounded[:2] == [0., 1.] and count == 2
