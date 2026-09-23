from explanation import summarize_forecast


def success_result():
    return {
        "status": "ok",
        "turbine_id": "T1",
        "origin": "2026-01-31T18:00:00Z",
        "timezone": "Asia/Almaty",
        "fingerprint": "sha256:forecast-123",
        "weather_provenance": {"provenance_status": "fixture"},
        "analysis": {
            "peak_power_norm": 0.82,
            "peak_at": "2026-01-31T19:00:00Z",
            "min_power_norm": 0.07,
            "min_at": "2026-02-01T04:00:00Z",
            "warnings": ["Timezone and interval semantics assumed"],
        },
    }


def test_template_summary_uses_analysis_and_local_timezone():
    summary = summarize_forecast(success_result())

    assert summary["backend"] == "template"
    assert summary["forecast_fingerprint"] == "sha256:forecast-123"
    assert summary["warning"] is None
    assert "0.82 normalized power" in summary["text"]
    assert "0.07" in summary["text"]
    assert "Feb 1, 2026 00:00 +05" in summary["text"]
    assert "Feb 1, 2026 09:00 +05" in summary["text"]
    assert "normalized fractions, not MW or MWh" in summary["text"]
    assert "synthetic fixtures" in summary["text"]
    assert "timezone and interval semantics are assumed" in summary["text"]


def test_llm_request_is_labeled_as_template_fallback():
    summary = summarize_forecast(success_result(), backend="llm")

    assert summary["backend"] == "template"
    assert "not enabled" in summary["warning"]
    assert "0.82 normalized power" in summary["text"]


def test_summary_rejects_failed_results_and_unknown_backends():
    try:
        summarize_forecast({"status": "error"})
    except ValueError as exc:
        assert "successful forecast" in str(exc)
    else:
        raise AssertionError("failed forecast must not be summarized")

    try:
        summarize_forecast(success_result(), backend="anything")
    except ValueError as exc:
        assert "backend must" in str(exc)
    else:
        raise AssertionError("unknown backend must be rejected")
