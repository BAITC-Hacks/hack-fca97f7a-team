"""UI smoke tests with actual local models and a simulated map component.

Run fixture generation and training first, as documented in README.
Real Leaflet marker interactions are checked separately in browser smoke tests.
"""
import pytest
from streamlit.testing.v1 import AppTest

from contracts import ROOT


@pytest.fixture
def ui(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "fixture")
    monkeypatch.setenv("SUMMARY_BACKEND", "template")
    # AppTest does not execute iframe JavaScript, so simulate only the map event.
    monkeypatch.setattr("streamlit_folium.st_folium", lambda *a, **k: {"last_object_clicked": None})
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=15).run()


def test_ui_forecast_update_and_stale_results(ui):
    assert not ui.exception
    assert ui.button(key="predict").disabled
    ui.selectbox(key="selected_site").select("T2").run()
    ui.selectbox(key="horizon").select(48).run()
    ui.button(key="predict").click().run()
    assert not ui.exception
    result = ui.session_state["result"]
    assert result["status"] == "ok" and len(result["hours"]) == 48
    assert ui.session_state["summary"]["forecast_fingerprint"] == result["fingerprint"]
    ui.button(key="advance").click().run()
    assert not ui.exception
    newer = ui.session_state["result"]
    assert newer["origin"] == "2026-02-01T18:00:00Z"
    assert newer["fingerprint"] != result["fingerprint"]
    assert any("overlapping hours" in item.value for item in ui.caption)
    ui.selectbox(key="horizon").select(24).run()
    assert "result" not in ui.session_state
    ui.button(key="predict").click().run()
    assert len(ui.session_state["result"]["hours"]) == 24
    ui.button(key="advance").click().run()
    assert not ui.exception
    assert "result" not in ui.session_state
    assert any("WEATHER_UNAVAILABLE" in item.value for item in ui.error)


def test_marker_identity_and_background_click(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "fixture")
    event = {"last_object_clicked": {"lat": 0, "lng": 0.03}}
    monkeypatch.setattr("streamlit_folium.st_folium", lambda *a, **k: event)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15).run()
    assert not app.exception
    assert app.selectbox(key="selected_site").value == "T2"
    assert "result" not in app.session_state
    event["last_object_clicked"] = {"lat": 1, "lng": 2}
    app.run()
    assert app.selectbox(key="selected_site").value == "T2"
    assert "result" not in app.session_state


def test_archive_mode_does_not_display_fixture_forecast(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "archive")
    monkeypatch.setattr("streamlit_folium.st_folium", lambda *a, **k: {"last_object_clicked": None})
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15).run()
    assert not app.exception
    assert "result" not in app.session_state
    assert any("Archive mode is unavailable" in item.value for item in app.info)


def test_summary_stub_keeps_real_forecast(ui, monkeypatch):
    monkeypatch.setenv("SUMMARY_BACKEND", "llm")
    ui.selectbox(key="selected_site").select("T1").run()
    ui.button(key="predict").click().run()
    assert not ui.exception
    assert ui.session_state["result"]["status"] == "ok"
    assert ui.session_state["summary"]["backend"] == "template"
    assert "not enabled" in ui.session_state["summary"]["warning"]
