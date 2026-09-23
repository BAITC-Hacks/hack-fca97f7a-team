"""Fit two versioned turbine models from immutable supplied measurements."""

from __future__ import annotations

import argparse

from contracts import FIRST_ORIGIN, SITE_IDS, ForecastError
from data import ingest_all, save_canonical
from model import save_model, train_model


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("fixture", "archive"), default="fixture",
                        help="Inference weather mode; training always uses real supplied measurements.")
    args = parser.parse_args(argv)
    history, audits = ingest_all()
    by_turbine = {audit["turbine_id"]: audit for audit in audits}
    if set(by_turbine) != set(SITE_IDS) or len(audits) != len(SITE_IDS):
        raise ForecastError("DATA_INVALID", "Для обучения нужны разные исходные истории T1 и T2.")
    for turbine_id in SITE_IDS:
        if not by_turbine[turbine_id].get("matches_expected_source_sha256", False):
            raise ForecastError("DATA_INVALID", f"Контрольная сумма исходного файла {turbine_id} не совпадает.")
    save_canonical(history, audits)
    for turbine_id in SITE_IDS:
        audit = by_turbine[turbine_id]
        fitted = train_model(history, FIRST_ORIGIN, turbine_id)
        fitted.metadata["source_sha256"] = audit["source_sha256"]
        artifact = save_model(fitted)
        print(f"{turbine_id}: {fitted.metadata['training_rows']} complete training hours; "
              f"last interval {fitted.metadata['train_last_interval_start']}; "
              f"model {fitted.metadata['model_id']}; artifact {artifact}")
    print(f"Weather mode {args.mode} does not affect training or fetch forecast weather.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
