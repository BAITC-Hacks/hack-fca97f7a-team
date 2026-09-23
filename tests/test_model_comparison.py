"""The comparison must pair identical targets and preserve temporal boundaries."""

import numpy as np
import pandas as pd
import pytest

from contracts import FIRST_ORIGIN, ForecastError
from model import train_model
from scripts import compare_models


def test_comparison_pairs_models_excludes_missing_truth_and_ignores_later_data(monkeypatch):
    stamps = pd.date_range("2025-09-28T00:00:00Z", "2025-10-06T00:00:00Z", freq="h")
    frame = pd.DataFrame({
        "turbine_id": "T1", "timestamp": stamps,
        "wind_speed_ms": 5 + np.sin(np.arange(len(stamps)) / 3),
        "temperature_c": 2., "power_norm": .4 + .1 * np.sin(np.arange(len(stamps)) / 3),
    })
    frame = frame.loc[frame.timestamp != pd.Timestamp("2025-10-02T12:00:00Z")].copy()
    calls = []

    def capture_train(history, origin, turbine_id, *, variant):
        fitted = train_model(history, origin, turbine_id, variant=variant)
        calls.append((origin, fitted.metadata))
        return fitted

    monkeypatch.setattr(compare_models, "train_model", capture_train)
    results, points = compare_models.compare_period(
        frame, "T1", "2025-10-01T00:00:00Z", "2025-10-05T00:00:00Z")
    assert len(calls) == 2
    assert all(origin == "2025-10-01T00:00:00Z" for origin, _ in calls)
    assert all(meta["train_last_interval_start"] == "2025-09-30T23:00:00Z" for _, meta in calls)
    assert all(value["training_rows"] == 72 for value in results.values())
    paired = [group[["origin", "valid_at", "actual_power_norm"]].reset_index(drop=True)
              for _, group in points.groupby("variant")]
    pd.testing.assert_frame_equal(*paired)
    assert points.valid_at.max() == "2025-10-04T00:00:00Z"
    for result in results.values():
        assert result["daily_origins"] == 2
        assert result["excluded_missing_complete_hour_pairs"] == 2
        assert result["metrics"]["all_48h"]["scored_pairs"] == 94
        assert (result["metrics"]["lead_1_24h"]["scored_pairs"]
                + result["metrics"]["lead_25_48h"]["scored_pairs"]) == 94
    # The discarded future data cannot change fitting, scored keys, or predictions.
    frame.loc[frame.timestamp >= pd.Timestamp("2025-10-05T00:00:00Z"),
              ["wind_speed_ms", "temperature_c", "power_norm"]] = [999., 99., 1.]
    repeated, repeated_points = compare_models.compare_period(
        frame, "T1", "2025-10-01T00:00:00Z", "2025-10-05T00:00:00Z")
    assert repeated == results
    pd.testing.assert_frame_equal(repeated_points, points)


def test_comparison_cannot_extend_into_february():
    with pytest.raises(ForecastError, match="заморозки"):
        compare_models.compare_period(pd.DataFrame(), "T1", FIRST_ORIGIN, "2026-02-02T00:00:00Z")
