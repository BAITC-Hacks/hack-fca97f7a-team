from pathlib import Path

import pandas as pd
import pytest

from contracts import ForecastError, ROOT
from data import COLUMNS, EXPECTED_SOURCE_SHA256, canonicalize, ingest_all


def write_source(path, timestamps, powers=None):
    columns = list(COLUMNS)
    pd.DataFrame({columns[0]: timestamps, columns[1]: [6.0] * len(timestamps),
                  columns[2]: powers if powers is not None else [0.3] * len(timestamps),
                  columns[3]: [-3.0] * len(timestamps)}).to_csv(path, index=False)


def test_complete_hours_only_and_zero_power_retained(tmp_path):
    times = [f"2026-01-30 00:{m:02}:00" for m in range(0, 60, 10)]
    times += [f"2026-01-30 01:{m:02}:00" for m in range(0, 50, 10)]
    path = tmp_path / "source.csv"
    write_source(path, times, [0.0] * 6 + [1.0] * 5)
    frame, audit = canonicalize(path, "T2")
    assert len(frame) == 1
    assert frame.iloc[0]["timestamp"] == pd.Timestamp("2026-01-29T19:00:00Z")
    assert frame.iloc[0]["power_norm"] == 0
    assert audit["complete_hours"] == audit["incomplete_hours"] == 1
    assert audit["missing_ten_minute_slots"] == 0


def test_duplicate_source_timestamp_rejected(tmp_path):
    path = tmp_path / "source.csv"
    write_source(path, ["2026-01-30 00:00:00"] * 2)
    with pytest.raises(ForecastError, match="Duplicate"):
        canonicalize(path, "T2")


def test_ambiguous_clock_change_is_reported(tmp_path):
    path = tmp_path / "source.csv"
    write_source(path, [f"2024-02-29 23:{m:02}:00" for m in range(0, 60, 10)]
                 + [f"2024-03-01 00:{m:02}:00" for m in range(0, 60, 10)])
    frame, audit = canonicalize(path, "T2")
    assert audit["ambiguous_or_nonexistent_rows"] == 6
    assert audit["ambiguous_local_rows"] == 6
    assert audit["nonexistent_local_rows"] == 0
    assert len(frame) == 1


def test_missing_slot_drops_hour_and_is_audited(tmp_path):
    path = tmp_path / "source.csv"
    times = [f"2026-01-30 00:{m:02}:00" for m in range(0, 60, 10) if m != 20]
    times += [f"2026-01-30 01:{m:02}:00" for m in range(0, 60, 10)]
    write_source(path, times)
    frame, audit = canonicalize(path, "T1")
    assert frame["timestamp"].tolist() == [pd.Timestamp("2026-01-29T20:00:00Z")]
    assert audit["missing_ten_minute_slots"] == 1
    assert audit["incomplete_hours"] == 1


def test_invalid_source_clock_and_off_grid_values_are_excluded(tmp_path):
    path = tmp_path / "source.csv"
    times = [f"2026-01-30 00:{m:02}:00" for m in range(0, 60, 10)]
    times += ["bad-clock", "2026-01-30 01:05:00"]
    write_source(path, times)
    frame, audit = canonicalize(path, "T1")
    assert len(frame) == 1
    assert audit["invalid_timestamp_rows"] == 1
    assert audit["off_grid_rows"] == 1
    assert audit["excluded_source_rows"] == 2


def test_real_sources_are_distinct_and_suffixed_copies_ignored(tmp_path):
    # Confirm current actual inputs and exact-name selection, without ingesting 300k rows per test.
    import hashlib
    from data import source_path
    one, two = source_path("T1"), source_path("T2")
    assert hashlib.sha256(one.read_bytes()).hexdigest() != hashlib.sha256(two.read_bytes()).hexdigest()
    times = [f"2026-01-30 00:{m:02}:00" for m in range(0, 60, 10)]
    canonical_name = source_path("T2", tmp_path)
    write_source(canonical_name, times)
    (tmp_path / canonical_name.name.replace(".csv", "(1).csv")).write_bytes(canonical_name.read_bytes())
    frame, audits = ingest_all(tmp_path)
    assert len(frame) == 1 and len(audits) == 1
    assert audits[0]["source_rows"] == 6
    assert audits[0]["matches_expected_source_sha256"] is False


def test_real_source_hashes_match_audited_identity():
    from data import source_path
    import hashlib
    for turbine, expected in EXPECTED_SOURCE_SHA256.items():
        assert hashlib.sha256(source_path(turbine).read_bytes()).hexdigest() == expected


def test_identical_files_cannot_be_two_turbines(tmp_path):
    from data import source_path
    times = [f"2026-01-30 00:{m:02}:00" for m in range(0, 60, 10)]
    one, two = source_path("T1", tmp_path), source_path("T2", tmp_path)
    write_source(one, times)
    two.write_bytes(one.read_bytes())
    with pytest.raises(ForecastError, match="identical"):
        ingest_all(tmp_path)
