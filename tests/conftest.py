"""Never use paid model APIs from the automated test suite."""
import pytest


@pytest.fixture(autouse=True)
def offline_llm(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")


@pytest.fixture(autouse=True)
def isolated_live_weather_cache():
    from weather import clear_live_weather_cache
    clear_live_weather_cache()
    yield
    clear_live_weather_cache()


@pytest.fixture
def provider_model_factory():
    """A real fitted estimator, with synthetic training data and explicit domain."""
    import pandas as pd
    from model import train_model
    from contracts import FIRST_ORIGIN

    def make(turbine_id):
        frame = pd.DataFrame({"turbine_id": [turbine_id] * 96,
            "timestamp": pd.date_range("2026-01-26", periods=96, freq="h", tz="UTC"),
            "wind_speed_ms": [float(i % 12) for i in range(96)],
            "temperature_c": [float(i % 20) for i in range(96)],
            "power_norm": [(i % 12) / 12 for i in range(96)]})
        return train_model(frame, FIRST_ORIGIN, turbine_id,
            profile="open_meteo_ecmwf_ifs_10m", weather_context={
                "provider": "open-meteo", "model": "ecmwf_ifs", "wind_height_m": 10,
                "temperature_height_m": 2, "training_weather_kind": "retrospective_stitched_forecast",
                "availability_verified": False, "weather_csv_sha256": "a" * 64})
    return make
