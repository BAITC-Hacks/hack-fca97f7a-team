"""Computed prose for a completed forecast.

This module only formats facts already present in the forecast result. It does
not call a model, fetch weather, or make new numeric predictions.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from contracts import FIRST_ORIGIN, SITE_TIMEZONE, fingerprint


def _local_time(value: str, timezone_name: str) -> str:
    """Format an ISO timestamp in the result's site timezone."""
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, TypeError):
        zone = ZoneInfo(SITE_TIMEZONE)
    return stamp.astimezone(zone).strftime("%b %-d, %Y %H:%M %Z")


def _format_power(value: object) -> str:
    return f"{float(value):.2f}"


def summarize_forecast(result: dict, backend: str = "template") -> dict:
    """Return a short summary grounded in a successful forecast's analysis.

    ``backend='llm'`` remains an explicit stub in this slice: it returns the
    same computed template and identifies why no LLM paraphrase was attempted.
    """
    if backend not in ("template", "llm"):
        raise ValueError("backend must be 'template' or 'llm'.")
    if not isinstance(result, dict) or result.get("status") != "ok":
        raise ValueError("A successful forecast result is required.")

    analysis = result.get("analysis")
    if not isinstance(analysis, dict):
        raise ValueError("Forecast result is missing computed analysis.")
    required = ("peak_power_norm", "peak_at", "min_power_norm", "min_at")
    if any(key not in analysis or analysis[key] is None for key in required):
        raise ValueError("Forecast analysis must include peak and minimum values and times.")

    timezone_name = result.get("timezone") or SITE_TIMEZONE
    peak_at = _local_time(analysis["peak_at"], timezone_name)
    min_at = _local_time(analysis["min_at"], timezone_name)
    text = (
        f"The forecast peak is {_format_power(analysis['peak_power_norm'])} normalized power "
        f"at {peak_at}; its lowest value is {_format_power(analysis['min_power_norm'])} "
        f"at {min_at}. These values are normalized fractions, not MW or MWh."
    )

    provenance = result.get("weather_provenance", {})
    status = provenance.get("provenance_status") if isinstance(provenance, dict) else None
    warnings = analysis.get("warnings") or []
    warning_text = " ".join(str(item) for item in warnings)
    if status == "fixture" or "synthetic weather" in warning_text.lower():
        text += " Weather inputs are synthetic fixtures."
    if "timezone" in warning_text.lower() or "interval" in warning_text.lower():
        text += " Source timezone and interval semantics are assumed."

    warning = None
    actual_backend = backend
    if backend == "llm":
        actual_backend = "template"
        warning = "LLM summaries are not enabled in this slice; returned the computed template summary."

    result_fingerprint = result.get("fingerprint")
    if not isinstance(result_fingerprint, str) or not result_fingerprint:
        # Keep the return contract useful for success fixtures and older stored
        # results that predate result fingerprints.
        result_fingerprint = fingerprint({
            "origin": result.get("origin", FIRST_ORIGIN),
            "turbine_id": result.get("turbine_id"),
            "analysis": analysis,
        })
    return {
        "text": text,
        "backend": actual_backend,
        "forecast_fingerprint": result_fingerprint,
        "warning": warning,
    }
