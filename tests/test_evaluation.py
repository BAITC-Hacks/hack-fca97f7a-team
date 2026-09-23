"""Evaluation chronology, missing truth and metric boundaries."""

import numpy as np
import pandas as pd
import pytest

from scripts.evaluate import evaluate_window, latest_completed_power, score


def _history() -> pd.DataFrame:
    stamps = pd.to_datetime([
        "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z",
        "2026-01-01T02:00:00Z", "2026-01-01T04:00:00Z",
    ], utc=True)
    return pd.DataFrame({
        "turbine_id": ["T1"] * 4,
        "timestamp": stamps,
        "wind_speed_ms": [4., 5., 6., 8.],
        "temperature_c": [0., 1., 2., 4.],
        "power_norm": [0.2, 0.3, 0.4, 0.8],
    })


def test_persistence_only_uses_completed_observations_at_origin():
    history = _history()
    at_one = pd.Timestamp("2026-01-01T01:00:00Z")
    value, observed_at = latest_completed_power(history, at_one)
    assert value == 0.2
    assert observed_at == pd.Timestamp("2026-01-01T00:00:00Z")
    with pytest.raises(ValueError, match="No completed"):
        latest_completed_power(history, pd.Timestamp("2026-01-01T00:00:00Z"))


def test_window_counts_missing_truth_and_clips_inference_without_lookahead():
    history = _history()
    captured = []

    def predict(_model, weather):
        captured.extend(weather)
        return [1.2, -0.1]

    rows, missing, clipped = evaluate_window(
        history, object(), pd.Timestamp("2026-01-01T01:00:00Z"), 3, predictor=predict)
    assert missing == 1  # +1 and +3 exist; +2 lacks six source intervals.
    assert clipped == 2
    assert [row["lead_hour"] for row in rows] == [1, 3]
    assert [row["predicted_power_norm"] for row in rows] == [1.0, 0.0]
    assert [row["baseline_power_norm"] for row in rows] == [0.2, 0.2]
    assert all(row["baseline_observed_at"] == "2026-01-01T00:00:00Z" for row in rows)
    assert captured == [{"wind_speed_ms": 6., "temperature_c": 2.},
                        {"wind_speed_ms": 8., "temperature_c": 4.}]


def test_score_r2_can_be_negative_and_is_undefined_for_constant_truth():
    metrics = score(np.array([0., 0.]), np.array([0., 1.]))
    assert metrics["mae"] == 0.5
    assert metrics["rmse"] == pytest.approx(np.sqrt(.5))
    assert metrics["r2"] == -1.
    assert score(np.array([0.3, 0.3]), np.array([0.3, 0.3]))["r2"] is None
