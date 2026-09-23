"""Canonical ingestion. Supplied files are immutable; generated data is audited."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from contracts import FEATURES, SITE_IDS, SITE_TIMEZONE, ForecastError, data_dir

COLUMNS = {
    "Статистическое время": "timestamp",
    "Средняя скорость ветра(m/s)": "wind_speed_ms",
    "Нормализованная активная мощность": "power_norm",
    "Средняя температура окружающей среды(°C)": "temperature_c",
}
VALUES = FEATURES + ["power_norm"]
EXPECTED_SOURCE_SHA256 = {
    "T1": "c4c341582fb2dd348b7187f0128cff265fe055f469413871ebb5db50eef58b5b",
    "T2": "820578cd18bb557cd30c2e102f3ae5a386dfc6c489a5a15743339c2b017305e5",
}


def source_path(turbine_id: str, directory: Path | None = None) -> Path:
    if turbine_id not in SITE_IDS:
        raise ForecastError("INVALID_INPUT", "Неизвестная турбина.")
    return (directory or data_dir()) / (
        f"Dataset HackAlemAI для участников 11.03.2023-28.02.2026 - turbine {turbine_id[1:]}.csv"
    )


def canonicalize(path: Path, turbine_id: str) -> tuple[pd.DataFrame, dict]:
    if turbine_id not in SITE_IDS:
        raise ForecastError("INVALID_INPUT", "Неизвестная турбина.")
    try:
        raw = pd.read_csv(path, encoding="utf-8-sig")
    except (OSError, ValueError) as exc:
        raise ForecastError("DATA_INVALID", f"Cannot read supplied history: {path.name}") from exc
    if not set(COLUMNS).issubset(raw.columns):
        raise ForecastError("DATA_INVALID", f"Unexpected columns in {path.name}.")
    frame = raw.rename(columns=COLUMNS)[["timestamp", *VALUES]].copy()
    naive = pd.to_datetime(frame["timestamp"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    if naive.dropna().duplicated().any():
        raise ForecastError("DATA_INVALID", f"Duplicate source timestamps in {path.name}.")
    for col in VALUES:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    numeric_ok = pd.Series(np.isfinite(frame[VALUES].to_numpy(dtype=float)).all(axis=1), index=frame.index)
    numeric_ok &= frame["wind_speed_ms"].ge(0) & frame["power_norm"].between(0, 1)
    grid_ok = naive.dt.minute.mod(10).eq(0) & naive.dt.second.eq(0)
    ambiguous_probe = naive.dt.tz_localize(SITE_TIMEZONE, ambiguous="NaT", nonexistent="shift_forward")
    nonexistent_probe = naive.dt.tz_localize(SITE_TIMEZONE, ambiguous=True, nonexistent="NaT")
    ambiguous = naive.notna() & ambiguous_probe.isna()
    nonexistent = naive.notna() & nonexistent_probe.isna()
    utc = naive.dt.tz_localize(SITE_TIMEZONE, ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")
    valid = numeric_ok & grid_ok & utc.notna()
    frame["timestamp"] = utc
    good = frame.loc[valid].sort_values("timestamp")
    if good["timestamp"].duplicated().any():
        raise ForecastError("DATA_INVALID", "Duplicate UTC timestamps after timezone conversion.")
    indexed = good.set_index("timestamp")
    means = indexed[VALUES].resample("h").mean()
    counts = indexed["power_norm"].resample("h").count()
    complete = means.loc[counts.eq(6)].reset_index()
    complete.insert(0, "turbine_id", turbine_id)
    source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    if good.empty:
        missing_slots = 0
    else:
        span = int((good["timestamp"].iloc[-1] - good["timestamp"].iloc[0]) / pd.Timedelta(minutes=10)) + 1
        missing_slots = span - len(good)
    audit = {
        "turbine_id": turbine_id,
        "source_file": path.name,
        "source_sha256": source_sha256,
        "matches_expected_source_sha256": source_sha256 == EXPECTED_SOURCE_SHA256[turbine_id],
        "source_rows": len(raw),
        "source_start_local": str(naive.min()),
        "source_end_local": str(naive.max()),
        "timezone": SITE_TIMEZONE,
        "timezone_status": "assumed",
        "interval_semantics": "assumed ten-minute interval starts",
        "invalid_numeric_rows": int((~numeric_ok).sum()),
        "invalid_timestamp_rows": int(naive.isna().sum()),
        "off_grid_rows": int((~grid_ok & naive.notna()).sum()),
        "ambiguous_or_nonexistent_rows": int((naive.notna() & utc.isna()).sum()),
        "ambiguous_local_rows": int(ambiguous.sum()),
        "nonexistent_local_rows": int(nonexistent.sum()),
        "excluded_source_rows": int((~valid).sum()),
        "missing_ten_minute_slots": missing_slots,
        "complete_hours": len(complete),
        "incomplete_hours": int(((counts > 0) & (counts < 6)).sum()),
        "empty_hours": int(counts.eq(0).sum()),
        "february_2026_rows": int(((naive.dt.year == 2026) & (naive.dt.month == 2)).sum()),
    }
    return complete, audit


def ingest_all(directory: Path | None = None) -> tuple[pd.DataFrame, list[dict]]:
    directory = directory or data_dir()
    frames, audits, seen = [], [], set()
    for turbine in SITE_IDS:
        path = source_path(turbine, directory)
        if not path.exists():
            continue
        frame, audit = canonicalize(path, turbine)
        if audit["source_sha256"] in seen:
            raise ForecastError("DATA_INVALID", "Two turbine files are identical; verify turbine identities.")
        seen.add(audit["source_sha256"])
        frames.append(frame)
        audits.append(audit)
    if not frames:
        raise ForecastError("DATA_INVALID", "No supplied turbine CSVs found in DATA_DIR.")
    return pd.concat(frames, ignore_index=True), audits


def save_canonical(history: pd.DataFrame, audits: list[dict]) -> None:
    directory = data_dir() / "canonical"
    directory.mkdir(parents=True, exist_ok=True)
    exported = history.copy()
    exported["timestamp"] = pd.to_datetime(exported["timestamp"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    exported.to_csv(directory / "history.csv", index=False)
    (directory / "ingestion_audit.json").write_text(json.dumps(audits, indent=2, ensure_ascii=False))
