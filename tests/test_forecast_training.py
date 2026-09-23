"""Chronology and source isolation for provider-feature training."""
import pandas as pd
import numpy as np
import pytest

from contracts import ForecastError
from scripts.train_forecast import align_history, promotion_gate, temporal_window


def test_join_never_uses_measured_features_or_cross_turbine_labels():
    times = pd.to_datetime(["2026-01-31T17:00Z", "2026-01-31T18:00Z"], utc=True)
    history = pd.DataFrame([
        {"turbine_id": tid, "timestamp": at, "wind_speed_ms": 99.,
         "temperature_c": 99., "power_norm": power}
        for tid, power in (("T1", .1), ("T2", .8)) for at in times])
    weather = pd.DataFrame([
        {"turbine_id": tid, "timestamp": at, "wind_speed_ms": wind, "temperature_c": 2.}
        for tid, wind in (("T1", 3.), ("T2", 4.)) for at in times])
    joined, audit = align_history(history, weather)
    assert joined.power_norm.tolist() == [.1, .8]
    assert joined.wind_speed_ms.tolist() == [3., 4.]
    assert joined.temperature_c.tolist() == [2., 2.]
    assert all(joined.timestamp == times[0])  # Final unfinished hour excluded.
    assert audit["T1"]["matched_hours"] == 1
    with pytest.raises(ForecastError):
        align_history(history, pd.concat([weather, weather.iloc[:1]]))


def test_missing_complete_power_hours_are_counted_not_filled():
    stamps = pd.date_range("2025-12-01", periods=3, freq="h", tz="UTC")
    weather = pd.DataFrame([{"turbine_id": tid, "timestamp": t,
                             "wind_speed_ms": 5., "temperature_c": 0.}
                            for tid in ("T1", "T2") for t in stamps])
    history = weather.loc[weather.timestamp.ne(stamps[1])].copy()
    history["power_norm"] = 0.  # Zero labels must remain.
    joined, audit = align_history(history, weather)
    assert len(joined) == 4 and (joined.power_norm == 0).all()
    assert audit["T1"]["excluded_missing_complete_power_hours"] == 1


def test_confirmation_boundaries_and_gate_tradeoff():
    frame = pd.DataFrame({"turbine_id": ["T1"] * 3,
                          "timestamp": pd.to_datetime(["2025-12-31T23:00Z",
                            "2026-01-01T00:00Z", "2026-01-01T01:00Z"], utc=True)})
    test = temporal_window(frame, "T1", "2026-01-01", "2026-01-01T02:00Z")
    assert len(test) == 2 and test.timestamp.min().hour == 0
    old, constant = {"mae": .3, "rmse": .4}, {"mae": .25}
    assert promotion_gate({"mae": .15, "rmse": .3}, old, constant)
    assert not promotion_gate({"mae": .15, "rmse": .5}, old, constant)
    assert not promotion_gate({"mae": .28, "rmse": .3}, old, constant)


def test_provider_comparison_preserves_original_measured_control():
    from model import predict_power, train_model
    from scripts.train_forecast import comparison

    stamps = pd.date_range("2025-12-25T00:00:00Z", "2026-01-03T00:00:00Z", freq="h")
    wind = 6 + 3 * np.sin(np.arange(len(stamps)) / 5)
    history = pd.DataFrame({"turbine_id": "T1", "timestamp": stamps,
                            "wind_speed_ms": wind, "temperature_c": 0.,
                            "power_norm": wind / 12})
    context = {"provider": "open-meteo", "model": "ecmwf_ifs", "wind_height_m": 10,
               "temperature_height_m": 2, "training_weather_kind": "retrospective_stitched_forecast",
               "availability_verified": False, "weather_csv_sha256": "a" * 64}
    _, points = comparison(history, history, "T1", "2026-01-01", "2026-01-03", "standard", context)
    baseline = train_model(history, "2026-01-01T00:00:00Z", "T1", variant="baseline")
    expected = predict_power(baseline, points[["wind_speed_ms", "temperature_c"]].to_dict("records"))
    np.testing.assert_array_equal(points.legacy_prediction.to_numpy(), expected)
