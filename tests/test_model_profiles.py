import json
import shutil
from hashlib import sha256
import pickle

import numpy as np
import pandas as pd
import pytest

from backend.core.contracts import FIRST_ORIGIN, ForecastError
from backend.ml.model import (FORECAST_RECIPES, load_model, predict_power_csv,
                   save_model, train_model)
from backend.ml.model_input import write_model_input


def history():
    stamps = pd.date_range("2026-01-27T00:00:00Z", "2026-02-02T00:00:00Z", freq="h")
    wind = 5 + 2 * np.sin(np.arange(len(stamps)) / 5)
    return pd.DataFrame({"turbine_id": "T2", "timestamp": stamps,
                         "wind_speed_ms": wind, "temperature_c": -2.0,
                         "power_norm": wind / 12})


def context(digest="a" * 64):
    return {"provider": "open-meteo", "model": "ecmwf_ifs", "wind_height_m": 10,
            "temperature_height_m": 2,
            "training_weather_kind": "retrospective_stitched_forecast",
            "availability_verified": False, "weather_csv_sha256": digest}


def provider_model(rows=None, recipe="standard", digest="a" * 64):
    return train_model(history() if rows is None else rows, FIRST_ORIGIN, "T2",
                       profile="open_meteo_ecmwf_ifs_10m", recipe=recipe,
                       weather_context=context(digest))


def test_provider_profile_isolated_from_measured_registry(monkeypatch, tmp_path):
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    measured = train_model(history(), FIRST_ORIGIN, "T2")
    measured_path = save_model(measured)
    provider = provider_model()
    provider_path = save_model(provider)
    assert measured_path.parent.parent == tmp_path / "models"
    assert provider_path.parent.parent == tmp_path / "models" / "open_meteo_ecmwf_ifs_10m"
    assert load_model("T2").metadata["model_id"] == measured.metadata["model_id"]
    loaded = load_model("T2", profile="open_meteo_ecmwf_ifs_10m")
    assert loaded.metadata["model_id"] == provider.metadata["model_id"]
    assert loaded.metadata["profile"] == "open_meteo_ecmwf_ifs_10m"
    assert provider.metadata["model_id"] != measured.metadata["model_id"]
    with pytest.raises(ForecastError, match="другому профилю"):
        load_model(provider_path)


def test_provider_identity_binds_recipe_source_and_cutoff():
    first = provider_model()
    assert first.metadata["train_last_interval_start"] == "2026-01-31T17:00:00Z"
    assert provider_model(recipe="regularized").metadata["model_id"] != first.metadata["model_id"]
    assert provider_model(recipe="absolute").metadata["model_id"] != first.metadata["model_id"]
    assert provider_model(digest="b" * 64).metadata["model_id"] != first.metadata["model_id"]
    assert set(FORECAST_RECIPES) == {"standard", "regularized", "absolute"}
    later = history()
    later.loc[later.timestamp >= pd.Timestamp(FIRST_ORIGIN), "power_norm"] = 1
    assert provider_model(later).metadata["model_id"] == first.metadata["model_id"]
    for bad in [{**context(), "availability_verified": True},
                {**context(), "wind_height_m": 100},
                {**context(), "weather_csv_sha256": "bad"}]:
        with pytest.raises(ForecastError):
            train_model(history(), FIRST_ORIGIN, "T2",
                        profile="open_meteo_ecmwf_ifs_10m", weather_context=bad)


@pytest.mark.parametrize("recipe", tuple(FORECAST_RECIPES))
def test_provider_recipe_and_v1_identity_unchanged_by_measured_variants(recipe):
    model = provider_model(recipe=recipe)
    metadata = model.metadata
    assert metadata["implementation"] == "hourly-hgbr-v1"
    assert metadata["parameters"] == FORECAST_RECIPES[recipe]
    assert metadata["params"] == FORECAST_RECIPES[recipe]
    assert model.estimator.get_params(deep=False) == type(model.estimator)(
        **FORECAST_RECIPES[recipe]).get_params(deep=False)
    identity = {
        "implementation": "hourly-hgbr-v1",
        "turbine_id": "T2",
        "cutoff": metadata["train_cutoff"],
        "canonical_sha256": metadata["canonical_sha256"],
        "feature_names": metadata["feature_names"],
        "parameters": FORECAST_RECIPES[recipe],
        "python_version": metadata["python_version"],
        "library_versions": metadata["library_versions"],
        "profile": "open_meteo_ecmwf_ifs_10m",
        "recipe": recipe,
        "weather_context": context(),
    }
    digest = sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert metadata["model_id"] == f"sha256:{digest}"
    assert train_model(history(), FIRST_ORIGIN, "T2", profile="open_meteo_ecmwf_ifs_10m",
                       recipe=recipe, weather_context=context(), variant=None).metadata["model_id"] == metadata["model_id"]


def test_cross_profile_variants_rejected():
    for variant in ("baseline", "candidate"):
        with pytest.raises(ForecastError) as error:
            train_model(history(), FIRST_ORIGIN, "T2", profile="open_meteo_ecmwf_ifs_10m",
                        weather_context=context(), variant=variant)
        assert error.value.code == "INVALID_INPUT"
    with pytest.raises(ForecastError) as error:
        train_model(history(), FIRST_ORIGIN, "T2", recipe="absolute", variant="candidate")
    assert error.value.code == "INVALID_INPUT"


def test_provider_metadata_tampering_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    path = save_model(provider_model())
    metadata_path = path / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["weather_context"]["weather_csv_sha256"] = "b" * 64
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(ForecastError, match="Артефакт"):
        load_model("T2", profile="open_meteo_ecmwf_ifs_10m")


def test_provider_estimator_configuration_tampering_rejected_with_updated_checksum(tmp_path):
    path = save_model(provider_model(), tmp_path)
    model_path = path / "model.pkl"
    estimator = pickle.loads(model_path.read_bytes())
    estimator.set_params(loss="absolute_error")
    binary = pickle.dumps(estimator, protocol=pickle.HIGHEST_PROTOCOL)
    model_path.write_bytes(binary)
    metadata_path = path / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["artifact_sha256"] = sha256(binary).hexdigest()
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ForecastError) as error:
        load_model(path, profile="open_meteo_ecmwf_ifs_10m")
    assert error.value.code == "MODEL_UNAVAILABLE"


def test_provider_registry_relative_artifact_root_and_wrong_profile(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ARTIFACT_DIR", "artifacts")
    with pytest.raises(ForecastError, match="scripts.train_forecast --activate"):
        load_model("T2", profile="open_meteo_ecmwf_ifs_10m")
    path = save_model(provider_model())
    registry = tmp_path / "artifacts" / "models" / "open_meteo_ecmwf_ifs_10m" / "latest.json"
    assert json.loads(registry.read_text())["T2"] == f"T2/{path.name}"
    assert load_model("T2", profile="open_meteo_ecmwf_ifs_10m").metadata["profile"] == "open_meteo_ecmwf_ifs_10m"
    # Older local registries can contain a path relative to the working directory.
    registry.write_text(json.dumps({"T2": str(path)}))
    assert load_model("T2", profile="open_meteo_ecmwf_ifs_10m").metadata["profile"] == "open_meteo_ecmwf_ifs_10m"
    metadata_path = path / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["profile"] = "measured"
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(ForecastError, match="Артефакт"):
        load_model("T2", profile="open_meteo_ecmwf_ifs_10m")


def test_provider_registry_survives_relocation_and_rejects_other_turbine(monkeypatch, tmp_path):
    source = tmp_path / "source" / "artifacts"
    monkeypatch.setenv("ARTIFACT_DIR", str(source))
    path = save_model(provider_model())
    target = tmp_path / "moved" / "artifacts"
    shutil.copytree(source, target)
    monkeypatch.setenv("ARTIFACT_DIR", str(target))
    monkeypatch.chdir(tmp_path)
    assert load_model("T2", profile="open_meteo_ecmwf_ifs_10m").metadata["model_id"] == "sha256:" + path.name
    index = target / "models" / "open_meteo_ecmwf_ifs_10m" / "latest.json"
    index.write_text(json.dumps({"T2": f"../T1/{path.name}"}))
    with pytest.raises(ForecastError, match="Реестр"):
        load_model("T2", profile="open_meteo_ecmwf_ifs_10m")


def test_provider_uses_same_canonical_csv_boundary(monkeypatch, tmp_path):
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    fitted = provider_model()
    rows = [{"valid_at": (pd.Timestamp(FIRST_ORIGIN) + pd.Timedelta(hours=i)).isoformat()
             .replace("+00:00", "Z"), "wind_speed_ms": 4 + i / 10,
             "temperature_c": -2.0} for i in range(1, 25)]
    info = write_model_input(rows, "T2", FIRST_ORIGIN, 24)
    path = tmp_path / "model_inputs" / info["filename"]
    predictions = predict_power_csv(fitted, path, turbine_id="T2", origin=FIRST_ORIGIN,
                                    horizon_hours=24, expected_sha256=info["sha256"])
    assert len(predictions) == 24 and np.isfinite(predictions).all()
    with pytest.raises(ForecastError):
        predict_power_csv(fitted, path, turbine_id="T1", origin=FIRST_ORIGIN,
                          horizon_hours=24, expected_sha256=info["sha256"])
