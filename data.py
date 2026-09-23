"""Audited conversion of supplied ten-minute turbine measurements to UTC hours."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


SOURCE_STEM = "Dataset HackAlemAI для участников 11.03.2023-28.02.2026 - turbine {}.csv"
SOURCE_IDS = {"T1": 1, "T2": 2}
EXPECTED_HASHES = {
    "T1": "c4c341582fb2dd348b7187f0128cff265fe055f469413871ebb5db50eef58b5b",
    "T2": "820578cd18bb557cd30c2e102f3ae5a386dfc6c489a5a15743339c2b017305e5",
}
SOURCE_COLUMNS = {
    "Статистическое время": "timestamp",
    "Средняя скорость ветра(m/s)": "wind_speed_ms",
    "Нормализованная активная мощность": "power_norm",
    "Средняя температура окружающей среды(°C)": "temperature_c",
}
VALUE_COLUMNS = ["wind_speed_ms", "temperature_c", "power_norm"]
HISTORY_COLUMNS = ["turbine_id", "timestamp", *VALUE_COLUMNS]
LOCAL_ZONE = "Asia/Almaty"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _iso(value: pd.Timestamp | None) -> str | None:
    return None if value is None or pd.isna(value) else value.isoformat().replace("+00:00", "Z")


def _ingest_one(path: Path, turbine_id: str, source_hash: str) -> tuple[pd.DataFrame, dict]:
    raw = pd.read_csv(path, encoding="utf-8", low_memory=False)
    missing = set(SOURCE_COLUMNS) - set(raw.columns)
    if missing:
        raise ValueError(f"{path.name}: missing source columns: {sorted(missing)}")
    raw = raw[list(SOURCE_COLUMNS)].rename(columns=SOURCE_COLUMNS)
    local = pd.to_datetime(raw["timestamp"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    invalid_timestamp = local.isna()
    off_grid = local.notna() & ((local.dt.minute % 10 != 0) | (local.dt.second != 0))

    # Two passes distinguish clock times repeated at the 2024 offset change
    # from times skipped at other historical changes. Neither is guessed.
    ambiguous_probe = local.dt.tz_localize(LOCAL_ZONE, ambiguous="NaT", nonexistent="shift_forward")
    nonexistent_probe = local.dt.tz_localize(LOCAL_ZONE, ambiguous=True, nonexistent="NaT")
    ambiguous = local.notna() & ambiguous_probe.isna()
    nonexistent = local.notna() & nonexistent_probe.isna()
    localized = local.dt.tz_localize(LOCAL_ZONE, ambiguous="NaT", nonexistent="NaT")

    numeric = raw[VALUE_COLUMNS].apply(pd.to_numeric, errors="coerce")
    finite = np.isfinite(numeric.to_numpy(dtype=float)).all(axis=1)
    invalid_numeric = pd.Series(~finite, index=raw.index)
    invalid_range = pd.Series(
        finite & ((numeric["wind_speed_ms"] < 0) | (numeric["power_norm"] < 0) | (numeric["power_norm"] > 1)),
        index=raw.index,
    )
    good = ~(invalid_timestamp | off_grid | ambiguous | nonexistent | invalid_numeric | invalid_range)
    slots = numeric.loc[good].copy()
    slots["timestamp"] = localized.loc[good].dt.tz_convert("UTC")

    duplicate_rows = int(slots.duplicated("timestamp", keep=False).sum())
    conflict = slots.groupby("timestamp", sort=False)[VALUE_COLUMNS].nunique(dropna=False).gt(1).any(axis=1)
    conflicting_slots = int(conflict.sum())
    if conflicting_slots:
        slots = slots.loc[~slots["timestamp"].isin(conflict.index[conflict])]
    slots = slots.drop_duplicates("timestamp").sort_values("timestamp")

    if slots.empty:
        hourly = pd.DataFrame(columns=HISTORY_COLUMNS)
        hourly["timestamp"] = pd.to_datetime(hourly["timestamp"], utc=True)
        incomplete_hours = missing_hours = missing_slots = 0
        utc_min = utc_max = None
    else:
        slots["hour"] = slots["timestamp"].dt.floor("h")
        groups = slots.groupby("hour", sort=True)
        counts = groups.size()
        complete = counts[counts == 6].index
        hourly = groups[VALUE_COLUMNS].mean().loc[complete].reset_index().rename(columns={"hour": "timestamp"})
        hourly.insert(0, "turbine_id", turbine_id)
        hourly = hourly[HISTORY_COLUMNS]
        incomplete_hours = int((counts < 6).sum())
        utc_min, utc_max = slots["timestamp"].min(), slots["timestamp"].max()
        span_slots = int((utc_max - utc_min) / pd.Timedelta(minutes=10)) + 1
        missing_slots = span_slots - len(slots)
        span_hours = int((utc_max.floor("h") - utc_min.floor("h")) / pd.Timedelta(hours=1)) + 1
        missing_hours = span_hours - len(counts)

    valid_local = local.dropna()
    audit = {
        "filename": path.name,
        "sha256": source_hash,
        "matches_expected_sha256": source_hash == EXPECTED_HASHES[turbine_id],
        "rows": int(len(raw)),
        "local_min": valid_local.min().isoformat() if len(valid_local) else None,
        "local_max": valid_local.max().isoformat() if len(valid_local) else None,
        "utc_min": _iso(utc_min),
        "utc_max": _iso(utc_max),
        "invalid_timestamp_rows": int(invalid_timestamp.sum()),
        "ambiguous_local_rows": int(ambiguous.sum()),
        "nonexistent_local_rows": int(nonexistent.sum()),
        "off_grid_rows": int(off_grid.sum()),
        "invalid_numeric_rows": int(invalid_numeric.sum()),
        "invalid_range_rows": int(invalid_range.sum()),
        "duplicate_slot_rows": duplicate_rows,
        "conflicting_duplicate_slots": conflicting_slots,
        "missing_ten_minute_slots": missing_slots,
        "incomplete_hours": incomplete_hours,
        "missing_hours": missing_hours,
        "complete_hours": int(len(hourly)),
    }
    return hourly, audit


def ingest_sources(data_dir: str | Path, output_dir: str | Path | None = None) -> tuple[pd.DataFrame, dict]:
    """Ingest only the two exact supplied filenames, keeping identities distinct.

    The returned hourly timestamps are UTC-aware interval starts. When supplied,
    ``output_dir`` receives ``history.csv`` and ``audit.json``.
    """
    data_dir = Path(data_dir)
    paths = {site: data_dir / SOURCE_STEM.format(number) for site, number in SOURCE_IDS.items()}
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing turbine source files: {missing}")
    hashes = {site: _sha256(path) for site, path in paths.items()}
    if len(set(hashes.values())) != len(hashes):
        raise ValueError("Turbine sources have identical SHA-256 hashes; separate measurements are required")

    histories: list[pd.DataFrame] = []
    sources: dict[str, dict] = {}
    for site, path in paths.items():
        history, source_audit = _ingest_one(path, site, hashes[site])
        histories.append(history)
        sources[site] = source_audit
    history = pd.concat(histories, ignore_index=True)[HISTORY_COLUMNS]
    history = history.sort_values(["turbine_id", "timestamp"]).reset_index(drop=True)
    audit = {
        "timezone_assumption": LOCAL_ZONE,
        "timestamp_semantics": "ten-minute interval starts; complete UTC hours use six distinct slots",
        "sources": sources,
        "total_complete_hours": int(len(history)),
        "expected_sha256": EXPECTED_HASHES,
    }
    if output_dir is not None:
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        export = history.copy()
        export["timestamp"] = export["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        export.to_csv(destination / "history.csv", index=False)
        (destination / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return history, audit
