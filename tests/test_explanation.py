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
    assert "Feb 01, 2026 00:00 +05" in summary["text"]
    assert "Feb 01, 2026 09:00 +05" in summary["text"]
    assert "normalized fractions, not MW or MWh" in summary["text"]
    assert "synthetic fixtures" in summary["text"]
    assert "timezone and interval semantics are assumed" in summary["text"]


def test_llm_request_is_labeled_as_template_fallback():
    summary = summarize_forecast(success_result(), backend="llm")

    assert summary["backend"] == "template"
    assert "not configured" in summary["warning"]
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


def test_llm_uses_facts_and_caches_completed_response(monkeypatch):
    import json
    from types import SimpleNamespace
    import explanation
    explanation._CACHE.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-placeholder")
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="completed", output_text="A grounded explanation.")

    monkeypatch.setattr(explanation, "_create_client", lambda: SimpleNamespace(
        responses=SimpleNamespace(create=create), close=lambda: None))
    one = explanation.summarize_forecast(success_result(), backend="llm")
    two = explanation.summarize_forecast(success_result(), backend="llm")
    assert one["backend"] == "llm" and one["warning"] is None
    assert one == two and len(calls) == 1
    assert calls[0]["store"] is False
    context = json.loads(calls[0]["input"])
    assert context["analysis"]["peak_power_norm"] == 0.82
    assert "unit-test-placeholder" not in calls[0]["input"]


def test_llm_failure_preserves_computed_facts_without_exception_details(monkeypatch):
    import explanation
    explanation._CACHE.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-placeholder")

    def fail():
        raise RuntimeError("provider secret request details")

    monkeypatch.setattr(explanation, "_create_client", fail)
    result = explanation.summarize_forecast(success_result(), backend="llm")
    assert result["backend"] == "template" and "0.82" in result["text"]
    assert "RuntimeError" in result["warning"]
    assert "secret request" not in result["warning"]


def test_question_window_is_computed_not_guessed():
    from contracts import expected_hours, FIRST_ORIGIN
    from explanation import answer_question
    result = success_result()
    result["hours"] = [{"valid_at": stamp, "power_norm": index / 24}
                       for index, stamp in enumerate(expected_hours(FIRST_ORIGIN, 24))]
    answer = answer_question(result, "Which six-hour period has the highest average output?", backend="template")
    assert f"{sum(range(18,24))/24/6:.3f}" in answer["text"]
    assert answer["forecast_fingerprint"] == result["fingerprint"]
