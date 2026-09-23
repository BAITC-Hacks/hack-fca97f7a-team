"""Train once from supplied history, never during a Streamlit rerun."""
import argparse

from contracts import FIRST_ORIGIN
from data import ingest_all, save_canonical
from model import save_model, train_model


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["fixture", "archive"], default="fixture",
                        help="Weather mode; training always uses real supplied history.")
    parser.parse_args()
    history, audits = ingest_all()
    save_canonical(history, audits)
    for audit in audits:
        fitted = train_model(history, FIRST_ORIGIN, audit["turbine_id"])
        fitted.metadata["source_sha256"] = audit["source_sha256"]
        save_model(fitted)
        print(f"{audit['turbine_id']}: {fitted.metadata['training_rows']} training hours; "
              f"last interval {fitted.metadata['train_last_interval_start']}; {fitted.metadata['model_id'][:23]}")


if __name__ == "__main__":
    main()
