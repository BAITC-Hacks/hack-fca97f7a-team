from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from data import SOURCE_STEM, ingest_sources


def _rows(start: str, count: int, power: float = 0.0) -> list[dict]:
    beginning = datetime.fromisoformat(start)
    return [
        {
            "Статистическое время": (beginning + timedelta(minutes=10 * n)).strftime("%Y-%m-%d %H:%M:%S"),
            "Средняя скорость ветра(m/s)": float(n + 1),
            "Нормализованная активная мощность": power,
            "Средняя температура окружающей среды(°C)": -2.0,
        }
        for n in range(count)
    ]


def _write(data_dir, t1, t2):
    data_dir.mkdir(parents=True, exist_ok=True)
    for number, rows in ((1, t1), (2, t2)):
        pd.DataFrame(rows).to_csv(data_dir / SOURCE_STEM.format(number), index=False)


def test_complete_hour_zero_power_duplicate_and_incomplete_hour(tmp_path):
    one = _rows("2026-01-31 00:00:00", 6)
    one.append(one[0].copy())  # Duplicate does not create a seventh sample.
    one.extend(_rows("2026-01-31 01:00:00", 5))
    two = _rows("2026-01-31 00:00:00", 6, power=0.5)
    _write(tmp_path / "data", one, two)

    history, audit = ingest_sources(tmp_path / "data", tmp_path / "out")

    assert len(history) == 2
    assert history["timestamp"].dt.tz is not None
    assert history.loc[history.turbine_id == "T1", "timestamp"].iloc[0].isoformat() == "2026-01-30T19:00:00+00:00"
    assert history.loc[history.turbine_id == "T1", "wind_speed_ms"].iloc[0] == 3.5
    assert history.loc[history.turbine_id == "T1", "power_norm"].iloc[0] == 0.0
    assert audit["sources"]["T1"]["duplicate_slot_rows"] == 2
    assert audit["sources"]["T1"]["incomplete_hours"] == 1
    assert (tmp_path / "out" / "history.csv").exists()
    assert (tmp_path / "out" / "audit.json").exists()


def test_almaty_2024_repeated_clock_hour_is_dropped(tmp_path):
    # 23:00–23:50 occurred twice when Almaty moved from UTC+6 to UTC+5.
    ambiguous = _rows("2024-02-29 23:00:00", 6)
    valid = _rows("2024-03-01 00:00:00", 6)
    _write(tmp_path, ambiguous + valid, _rows("2024-03-01 00:00:00", 6, power=0.5))

    history, audit = ingest_sources(tmp_path)

    assert audit["sources"]["T1"]["ambiguous_local_rows"] == 6
    assert audit["sources"]["T1"]["complete_hours"] == 1
    assert history.loc[history.turbine_id == "T1", "timestamp"].iloc[0].isoformat() == "2024-02-29T19:00:00+00:00"


def test_conflicting_duplicate_invalidates_affected_hour(tmp_path):
    one = _rows("2026-01-31 00:00:00", 6)
    conflicting = one[0].copy()
    conflicting["Средняя скорость ветра(m/s)"] = 100.0
    one.append(conflicting)
    _write(tmp_path, one, _rows("2026-01-31 00:00:00", 6, power=0.5))

    history, audit = ingest_sources(tmp_path)

    assert audit["sources"]["T1"]["conflicting_duplicate_slots"] == 1
    assert audit["sources"]["T1"]["complete_hours"] == 0
    assert history.turbine_id.tolist() == ["T2"]


def test_identical_source_hashes_are_rejected(tmp_path):
    rows = _rows("2026-01-31 00:00:00", 6)
    _write(tmp_path, rows, rows)
    with pytest.raises(ValueError, match="identical SHA-256"):
        ingest_sources(tmp_path)


def test_one_source_with_no_valid_slots_keeps_utc_dtype(tmp_path):
    invalid = _rows("2026-01-31 00:00:00", 1)
    invalid[0]["Статистическое время"] = "not a timestamp"
    _write(tmp_path, invalid, _rows("2026-01-31 00:00:00", 6, power=0.5))

    history, audit = ingest_sources(tmp_path)

    assert history.turbine_id.tolist() == ["T2"]
    assert str(history.timestamp.dt.tz) == "UTC"
    assert audit["sources"]["T1"]["complete_hours"] == 0
    assert audit["sources"]["T1"]["invalid_timestamp_rows"] == 1
