import hashlib

import pytest

from contracts import FIRST_ORIGIN, ForecastError, artifact_dir
from model_input import COLUMNS, read_model_input, write_model_input
from weather import fetch_weather, load_sites


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
    from model import load_model, predict_power_csv
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
