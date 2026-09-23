"""Per-turbine, frozen hourly power model and local artifact handling."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
import pickle
from pathlib import Path
import platform
import re

import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from backend.core.contracts import FEATURES, FIRST_ORIGIN, ROOT, SITE_IDS, ForecastError, artifact_dir, utc_time


_PARAMETERS = {"max_iter": 100, "max_leaf_nodes": 15, "random_state": 42}
_PROVIDER_PROFILE = "open_meteo_ecmwf_ifs_10m"
FORECAST_RECIPES = {
    "standard": {"max_iter": 100, "max_leaf_nodes": 15, "random_state": 42,
                 "early_stopping": False},
    "regularized": {"max_iter": 200, "max_leaf_nodes": 7, "min_samples_leaf": 80,
                    "l2_regularization": 10, "learning_rate": 0.05,
                    "random_state": 42, "early_stopping": False},
    "absolute": {"max_iter": 200, "max_leaf_nodes": 7, "min_samples_leaf": 80,
                 "l2_regularization": 10, "learning_rate": 0.05,
                 "random_state": 42, "early_stopping": False,
                 "loss": "absolute_error"},
}
_SCHEMA = 1
_IMPLEMENTATION = "hourly-hgbr-v1"
_UNITS = {"wind_speed_ms": "m/s", "temperature_c": "degC"}


@dataclass
class ModelBundle:
    estimator: HistGradientBoostingRegressor
    metadata: dict


# Retain the name used by the current FastAPI model contract.
PowerModel = ModelBundle


def _iso(value: pd.Timestamp) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def _canonical_rows(frame: pd.DataFrame) -> bytes:
    """Stable bytes for precisely the sorted rows used by fit."""
    lines = []
    for row in frame.itertuples(index=False):
        lines.append(json.dumps(
            [_iso(row.timestamp), *[float(getattr(row, name)).hex() for name in FEATURES],
             float(row.power_norm).hex()],
            separators=(",", ":"),
        ))
    return ("\n".join(lines) + "\n").encode("ascii")


def _validated_weather_context(context: dict | None) -> dict:
    expected = {"provider": "open-meteo", "model": "ecmwf_ifs", "wind_height_m": 10,
                "temperature_height_m": 2,
                "training_weather_kind": "retrospective_stitched_forecast",
                "availability_verified": False}
    if (not isinstance(context, dict) or set(context) != set(expected) | {"weather_csv_sha256"}
            or any(type(context[key]) is not type(value) or context[key] != value
                   for key, value in expected.items())
            or not isinstance(context["weather_csv_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", context["weather_csv_sha256"]) is None):
        raise ForecastError("DATA_INVALID", "Контекст погодных данных модели некорректен.")
    return dict(context)


def _profile_recipe(profile: str, recipe: str, weather_context: dict | None) -> tuple[dict, dict | None]:
    if profile == "measured":
        if recipe != "standard" or weather_context is not None:
            raise ForecastError("INVALID_INPUT", "Профиль измеренной погоды требует стандартную модель.")
        return _PARAMETERS.copy(), None
    if profile != _PROVIDER_PROFILE or recipe not in FORECAST_RECIPES:
        raise ForecastError("INVALID_INPUT", "Неизвестный профиль или рецепт модели.")
    return FORECAST_RECIPES[recipe].copy(), _validated_weather_context(weather_context)


def train_model(history: pd.DataFrame, origin: str, turbine_id: str, *,
                profile: str = "measured", recipe: str = "standard",
                weather_context: dict | None = None) -> ModelBundle:
    """Fit one turbine using only hours completed by both cutoffs."""
    if turbine_id not in SITE_IDS:
        raise ForecastError("INVALID_INPUT", "Неизвестная турбина.")
    parameters, weather_context = _profile_recipe(profile, recipe, weather_context)
    requested_cutoff = utc_time(origin)
    frozen_cutoff = utc_time(FIRST_ORIGIN)
    if requested_cutoff.minute or requested_cutoff.second or requested_cutoff.microsecond:
        raise ForecastError("INVALID_INPUT", "Время обучения должно начинаться ровно в начале часа UTC.")
    cutoff = pd.Timestamp(min(requested_cutoff, frozen_cutoff))
    required = {"turbine_id", "timestamp", *FEATURES, "power_norm"}
    if not isinstance(history, pd.DataFrame) or not required.issubset(history.columns):
        raise ForecastError("DATA_INVALID", "В истории нет обязательных столбцов.")
    selected = history.loc[history["turbine_id"] == turbine_id,
                           ["timestamp", *FEATURES, "power_norm"]].copy()
    if selected.empty:
        raise ForecastError("DATA_INVALID", f"Нет истории для {turbine_id}.")
    try:
        stamps = [pd.Timestamp(value) for value in selected["timestamp"]]
    except (ValueError, TypeError, OverflowError) as exc:
        raise ForecastError("DATA_INVALID", "Некорректная временная метка в истории.") from exc
    if any(pd.isna(stamp) or stamp.tzinfo is None or stamp.utcoffset() is None
           for stamp in stamps):
        raise ForecastError("DATA_INVALID", "Временные метки истории должны содержать часовой пояс.")
    selected["timestamp"] = pd.DatetimeIndex([stamp.tz_convert("UTC") for stamp in stamps])
    if any(stamp.minute or stamp.second or stamp.microsecond or stamp.nanosecond
           for stamp in selected["timestamp"]):
        raise ForecastError("DATA_INVALID", "Временные метки истории должны начинаться ровно в начале часа UTC.")
    selected = selected.loc[selected["timestamp"] + pd.Timedelta(hours=1) <= cutoff]
    selected = selected.sort_values("timestamp", kind="stable").reset_index(drop=True)
    if len(selected) < 24:
        raise ForecastError("DATA_INVALID", "Для обучения требуется не менее 24 полных исторических часов.")
    if selected["timestamp"].duplicated().any():
        raise ForecastError("DATA_INVALID", "В истории есть повторяющиеся часовые метки.")
    try:
        numeric = selected[[*FEATURES, "power_norm"]].apply(pd.to_numeric, errors="raise")
    except (ValueError, TypeError) as exc:
        raise ForecastError("DATA_INVALID", "Признак или целевое значение обучения не является числом.") from exc
    values = numeric.to_numpy(dtype=float)
    if not np.isfinite(values).all() or np.any(values[:, 0] < 0):
        raise ForecastError("DATA_INVALID", "Признаки или целевые значения обучения некорректны.")
    if np.any((values[:, -1] < 0) | (values[:, -1] > 1)):
        raise ForecastError("DATA_INVALID", "Нормализованная мощность должна быть в диапазоне [0, 1].")
    selected[[*FEATURES, "power_norm"]] = numeric
    canonical_sha = _digest(_canonical_rows(selected))
    identity = {
        "implementation": _IMPLEMENTATION,
        "turbine_id": turbine_id,
        "cutoff": _iso(cutoff),
        "canonical_sha256": canonical_sha,
        "feature_names": list(FEATURES),
        "parameters": parameters,
        "python_version": platform.python_version(),
        "library_versions": {"numpy": np.__version__, "pandas": pd.__version__,
                             "scikit_learn": sklearn.__version__},
    }
    if profile != "measured":
        identity.update({"profile": profile, "recipe": recipe,
                         "weather_context": weather_context})
    model_id = "sha256:" + _digest(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode())
    estimator = HistGradientBoostingRegressor(**parameters)
    with threadpool_limits(limits=1):
        estimator.fit(values[:, :len(FEATURES)], values[:, -1])
    last = selected.iloc[-1]
    metadata = {
        "artifact_schema_version": _SCHEMA,
        "model_id": model_id,
        "turbine_id": turbine_id,
        "estimator": "HistGradientBoostingRegressor",
        "parameters": parameters.copy(),
        "feature_names": list(FEATURES),
        "feature_units": _UNITS.copy(),
        "target": "power_norm",
        "target_unit": "normalized_fraction",
        "train_cutoff": _iso(cutoff),
        "train_origin": _iso(cutoff),
        "train_last_interval_start": _iso(last.timestamp),
        "training_rows": len(selected),
        "features": list(FEATURES),
        "params": parameters.copy(),
        "training_source": ("supplied turbine measurements" if profile == "measured"
                            else "retrospective Open-Meteo forecast features aligned to supplied turbine power"),
        "sklearn_version": sklearn.__version__,
        "source_sha256": None,
        "canonical_sha256": canonical_sha,
        "artifact_sha256": None,
        "timezone_assumption": "Asia/Almaty",
        "interval_semantics": "source timestamps are ten-minute interval starts; hourly timestamps are starts",
        "aggregation_policy": "six distinct ten-minute intervals per complete hour; arithmetic mean",
        "baseline_norm": float(last.power_norm),
        "baseline_interval_start": _iso(last.timestamp),
        "python_version": identity["python_version"],
        "library_versions": identity["library_versions"],
        "validation": None,
        "implementation": _IMPLEMENTATION,
        "profile": profile,
        "recipe": recipe,
        "weather_context": weather_context,
        "feature_distribution": {
            name: {"min": float(numeric[name].min()), "p01": float(numeric[name].quantile(.01)),
                   "p99": float(numeric[name].quantile(.99)), "max": float(numeric[name].max())}
            for name in FEATURES
        },
    }
    return ModelBundle(estimator, metadata)


def _raw_predictions(model: ModelBundle, weather_rows: list[dict]) -> np.ndarray:
    if not isinstance(model, ModelBundle) or not isinstance(model.estimator, HistGradientBoostingRegressor):
        raise ForecastError("MODEL_UNAVAILABLE", "Артефакт модели некорректен.")
    if model.metadata.get("feature_names") != list(FEATURES):
        raise ForecastError("MODEL_UNAVAILABLE", "Порядок признаков модели не совпадает с входом.")
    if not isinstance(weather_rows, list) or not weather_rows:
        raise ForecastError("INVALID_INPUT", "Для прогноза необходимы строки погоды.")
    features = []
    for row in weather_rows:
        if not isinstance(row, dict) or any(name not in row for name in FEATURES):
            raise ForecastError("DATA_INVALID", "В строке погоды отсутствует признак.")
        try:
            wind, temp = (float(row[name]) for name in FEATURES)
        except (TypeError, ValueError) as exc:
            raise ForecastError("DATA_INVALID", "Признак погоды не является числом.") from exc
        if not np.isfinite(wind) or not np.isfinite(temp) or wind < 0:
            raise ForecastError("DATA_INVALID", "Признак погоды не является конечным числом или скорость ветра отрицательна.")
        features.append((wind, temp))
    input_features = (pd.DataFrame(features, columns=FEATURES)
                      if hasattr(model.estimator, "feature_names_in_")
                      else np.asarray(features, dtype=float))
    with threadpool_limits(limits=1):
        raw = np.asarray(model.estimator.predict(input_features), dtype=float)
    if raw.shape != (len(features),) or not np.isfinite(raw).all():
        raise ForecastError("DATA_INVALID", "Модель вернула некорректные значения прогноза.")
    return raw


def predict_with_diagnostics(model: ModelBundle, weather_rows: list[dict]) -> tuple[list[float], int]:
    raw = _raw_predictions(model, weather_rows)
    clipped_count = int(np.count_nonzero((raw < 0) | (raw > 1)))
    return np.clip(raw, 0, 1).tolist(), clipped_count


def predict_power(model: ModelBundle, weather_rows: list[dict]) -> list[float]:
    """Return bounded values for local diagnostics outside orchestration."""
    return predict_with_diagnostics(model, weather_rows)[0]


def predict_power_csv(model: ModelBundle, csv_path: Path, *, turbine_id: str, origin: str,
                      horizon_hours: int, expected_sha256: str) -> list[float]:
    """Read and validate the exact canonical input file before inference."""
    from backend.ml.model_input import read_model_input
    if model.metadata.get("turbine_id") != turbine_id:
        raise ForecastError("MODEL_UNAVAILABLE", "Турбина во входном CSV не совпадает с моделью.")
    rows = read_model_input(csv_path, turbine_id=turbine_id, origin=origin,
                            horizon_hours=horizon_hours, expected_sha256=expected_sha256)
    return _raw_predictions(model, rows).tolist()


def save_model(bundle: ModelBundle, output_root: str | Path | None = None) -> Path:
    """Write a versioned artifact; callers supply only a trusted local output root."""
    metadata = bundle.metadata.copy()
    turbine_id = metadata.get("turbine_id")
    model_id = metadata.get("model_id", "")
    if turbine_id not in SITE_IDS or not isinstance(model_id, str) or not model_id.startswith("sha256:"):
        raise ForecastError("MODEL_UNAVAILABLE", "Идентификатор модели некорректен.")
    profile = metadata.get("profile", "measured")
    if profile not in ("measured", _PROVIDER_PROFILE):
        raise ForecastError("MODEL_UNAVAILABLE", "Профиль модели некорректен.")
    output_root = Path(output_root) if output_root is not None else artifact_dir() / "models"
    if profile != "measured":
        output_root /= profile
    model_directory = output_root / turbine_id / model_id.removeprefix("sha256:")
    model_directory.mkdir(parents=True, exist_ok=True)
    binary = pickle.dumps(bundle.estimator, protocol=pickle.HIGHEST_PROTOCOL)
    metadata["artifact_sha256"] = _digest(binary)
    (model_directory / "model.pkl").write_bytes(binary)
    (model_directory / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    bundle.metadata["artifact_sha256"] = metadata["artifact_sha256"]
    index_path = output_root / "latest.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
        if not isinstance(index, dict):
            raise ValueError("model index is not a mapping")
    except (OSError, ValueError) as exc:
        raise ForecastError("MODEL_UNAVAILABLE", "Не удалось обновить реестр моделей.") from exc
    # Keep the registry portable when artifacts are copied to another machine.
    index[turbine_id] = str(model_directory.relative_to(output_root))
    temporary = index_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, index_path)
    return model_directory


def _load_versioned(path: Path) -> ModelBundle:
    """Verify locally generated metadata and checksum before unpickling."""
    try:
        metadata = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
        binary = (path / "model.pkl").read_bytes()
        if metadata.get("artifact_schema_version") != _SCHEMA:
            raise ValueError("artifact schema")
        model_id = metadata.get("model_id")
        identity = {
            "implementation": metadata.get("implementation"),
            "turbine_id": metadata.get("turbine_id"),
            "cutoff": metadata.get("train_cutoff"),
            "canonical_sha256": metadata.get("canonical_sha256"),
            "feature_names": metadata.get("feature_names"),
            "parameters": metadata.get("parameters"),
            "python_version": metadata.get("python_version"),
            "library_versions": metadata.get("library_versions"),
        }
        profile = metadata.get("profile", "measured")
        recipe = metadata.get("recipe", "standard")
        if profile == "measured":
            if recipe != "standard" or metadata.get("weather_context") is not None:
                raise ValueError("measured model profile")
            expected_parameters = _PARAMETERS
        elif profile == _PROVIDER_PROFILE:
            expected_parameters = FORECAST_RECIPES.get(recipe)
            if expected_parameters is None:
                raise ValueError("provider model recipe")
            context = _validated_weather_context(metadata.get("weather_context"))
            identity.update({"profile": profile, "recipe": recipe,
                             "weather_context": context})
        else:
            raise ValueError("model profile")
        expected_id = "sha256:" + _digest(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode())
        saved_python = str(metadata.get("python_version", "")).split(".")[:2]
        running_python = platform.python_version().split(".")[:2]
        if (metadata.get("turbine_id") not in SITE_IDS
                or not isinstance(model_id, str)
                or model_id != expected_id
                or path.name != model_id.removeprefix("sha256:")
                or path.parent.name != metadata["turbine_id"]
                or saved_python != running_python
                or metadata.get("library_versions", {}).get("scikit_learn") != sklearn.__version__
                or metadata.get("feature_names") != list(FEATURES)
                or metadata.get("feature_units") != _UNITS
                or metadata.get("estimator") != "HistGradientBoostingRegressor"
                or metadata.get("parameters") != expected_parameters
                or metadata.get("artifact_sha256") != _digest(binary)):
            raise ValueError("artifact identity or checksum")
        estimator = pickle.loads(binary)
        if not isinstance(estimator, HistGradientBoostingRegressor) or not hasattr(estimator, "n_features_in_") or estimator.n_features_in_ != len(FEATURES):
            raise ValueError("estimator incompatible")
        # The existing agent consumes these stable keys. They are aliases of
        # versioned metadata and do not change the artifact identity.
        metadata["train_origin"] = metadata["train_cutoff"]
        metadata["features"] = list(FEATURES)
        metadata["params"] = expected_parameters.copy()
        metadata["profile"] = profile
        metadata["recipe"] = recipe
        metadata["sklearn_version"] = sklearn.__version__
        return ModelBundle(estimator, metadata)
    except (OSError, ValueError, TypeError, KeyError, ForecastError, pickle.UnpicklingError,
            EOFError, AttributeError, ImportError) as exc:
        raise ForecastError("MODEL_UNAVAILABLE", "Артефакт модели отсутствует или повреждён.") from exc


def load_model(turbine_id: str | Path, *, profile: str = "measured") -> ModelBundle:
    """Resolve the selected turbine's versioned artifact without retraining."""
    if profile not in ("measured", _PROVIDER_PROFILE):
        raise ForecastError("INVALID_INPUT", "Неизвестный профиль модели.")
    if isinstance(turbine_id, Path) or (isinstance(turbine_id, str) and turbine_id not in SITE_IDS
                                           and ("/" in turbine_id or "\\" in turbine_id)):
        bundle = _load_versioned(Path(turbine_id))
        if bundle.metadata["profile"] != profile:
            raise ForecastError("MODEL_UNAVAILABLE", "Артефакт относится к другому профилю.")
        return bundle
    if turbine_id not in SITE_IDS:
        raise ForecastError("INVALID_INPUT", "Неизвестная модель турбины.")
    models_root = artifact_dir() / "models"
    if profile != "measured":
        models_root /= profile
    index_path = models_root / "latest.json"
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            indexed_value = index[turbine_id]
            if not isinstance(indexed_value, str) or not indexed_value:
                raise ValueError("invalid model index path")
            indexed = Path(indexed_value)
            # Older registries wrote absolute paths or paths relative to the
            # repository CWD. New registries are relative to latest.json.
            candidates = ([indexed] if indexed.is_absolute() else
                          [index_path.parent / indexed, ROOT / indexed, Path.cwd() / indexed])
            allowed_parent = (models_root / turbine_id).resolve()
            path = next((candidate for candidate in candidates
                         if candidate.resolve().parent == allowed_parent and candidate.is_dir()), None)
            if path is None:
                raise ValueError("model index path outside selected turbine")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ForecastError("MODEL_UNAVAILABLE", "Реестр моделей отсутствует или повреждён.") from exc
        bundle = _load_versioned(path)
        if bundle.metadata["turbine_id"] != turbine_id or bundle.metadata["profile"] != profile:
            raise ForecastError("MODEL_UNAVAILABLE", "Артефакт относится к другой турбине.")
        return bundle
    if profile != "measured":
        raise ForecastError("MODEL_UNAVAILABLE", "Артефакт погодной модели отсутствует. Выполните python -m scripts.train_forecast --activate.")
    # Existing flat artifacts remain usable during migration. The next CLI
    # training run writes versioned files and an index; no request trains.
    try:
        fitted = pickle.loads((models_root / f"{turbine_id}.pkl").read_bytes())
        if (not isinstance(fitted, ModelBundle)
                or fitted.metadata.get("turbine_id") != turbine_id
                or not isinstance(fitted.estimator, HistGradientBoostingRegressor)
                or fitted.metadata.get("features") != list(FEATURES)):
            raise ValueError("flat artifact identity")
        if (fitted.metadata.get("sklearn_version") != sklearn.__version__
                or utc_time(fitted.metadata["train_origin"]) > utc_time(FIRST_ORIGIN)):
            raise ValueError("flat artifact training compatibility")
        fitted.metadata["feature_names"] = list(FEATURES)
        fitted.metadata["train_cutoff"] = fitted.metadata["train_origin"]
        return fitted
    except (OSError, ValueError, KeyError, TypeError, pickle.UnpicklingError,
            EOFError, AttributeError, ImportError) as exc:
        raise ForecastError("MODEL_UNAVAILABLE", "Модель недоступна. Выполните python -m scripts.train --mode fixture.") from exc
