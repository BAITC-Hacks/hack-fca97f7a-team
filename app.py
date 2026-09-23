"""Streamlit presentation for the registered-turbine forecasting demo."""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from agent import run_forecast
from contracts import fingerprint, forecast_csv
from explanation import summarize_forecast
from weather import load_sites


INITIAL_ORIGIN_DATE = date(2026, 1, 31)


def _queue_action(action: str) -> None:
    """Button callbacks run before the page, allowing safe widget updates."""
    if action == "advance":
        current = st.session_state.get("origin_date", INITIAL_ORIGIN_DATE)
        if isinstance(current, date):
            st.session_state["origin_date"] = current + timedelta(days=1)
    st.session_state["_run_action"] = action


def _site_index(sites: list[dict]) -> dict[str, dict]:
    return {str(site["turbine_id"]): site for site in sites}


def _make_map(sites: list[dict], selected_site: str | None) -> folium.Map:
    if sites:
        center = [
            sum(float(site["latitude"]) for site in sites) / len(sites),
            sum(float(site["longitude"]) for site in sites) / len(sites),
        ]
    else:
        center = [48.0, 68.0]
    map_view = folium.Map(location=center, zoom_start=12, control_scale=True)
    if len(sites) > 1:
        map_view.fit_bounds([
            [float(site["latitude"]), float(site["longitude"])] for site in sites
        ], padding=(36, 36))
    for site in sites:
        turbine_id = str(site["turbine_id"])
        coordinate_status = str(site.get("coordinate_status", "configured"))
        label = f"{turbine_id} · {coordinate_status} coordinates"
        folium.Marker(
            location=[float(site["latitude"]), float(site["longitude"])],
            tooltip=label,
            popup=label,
            icon=folium.Icon(color="blue" if turbine_id == selected_site else "green", icon="wind", prefix="fa"),
        ).add_to(map_view)
    return map_view


def _resolve_marker(event: object, sites: list[dict]) -> str | None:
    """Accept a map selection only when it matches a configured marker."""
    if not isinstance(event, dict):
        return None
    try:
        latitude = float(event.get("lat", event.get("latitude")))
        longitude = float(event.get("lng", event.get("longitude")))
    except (TypeError, ValueError):
        return None
    for site in sites:
        if (
            abs(latitude - float(site["latitude"])) <= 1e-5
            and abs(longitude - float(site["longitude"])) <= 1e-5
        ):
            return str(site["turbine_id"])
    return None


def _request_for(site: dict, origin_date: date, horizon: int, mode: str) -> dict:
    timezone_name = str(site.get("timezone") or "Asia/Almaty")
    local_origin = datetime.combine(origin_date, time(23, 0), tzinfo=ZoneInfo(timezone_name))
    origin = local_origin.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {
        "turbine_id": str(site["turbine_id"]),
        "origin": origin,
        "horizon_hours": int(horizon),
        "mode": mode,
    }


def _store_failure(request_key: str, code: str, message: str) -> None:
    st.session_state.pop("result", None)
    st.session_state.pop("summary", None)
    st.session_state["_forecast_error"] = {
        "request_key": request_key,
        "code": code,
        "message": message,
    }


def _run(request: dict, request_key: str) -> None:
    try:
        result = run_forecast(request)
    except Exception as exc:  # A failed run must never leave the old result visible.
        code = getattr(exc, "code", "FORECAST_FAILED")
        _store_failure(request_key, str(code), str(exc))
        return
    if not isinstance(result, dict) or result.get("status") != "ok":
        _store_failure(
            request_key,
            str(result.get("code", "FORECAST_FAILED")) if isinstance(result, dict) else "FORECAST_FAILED",
            str(result.get("message", "Forecast did not complete.")) if isinstance(result, dict) else "Forecast did not complete.",
        )
        return

    site_id = str(result.get("turbine_id", request["turbine_id"]))
    latest = st.session_state.setdefault("_latest_success_by_site", {})
    previous = latest.get(site_id)
    previous_by_site = st.session_state.setdefault("_previous_success_by_site", {})
    if previous and previous.get("fingerprint") != result.get("fingerprint"):
        previous_by_site[site_id] = previous
    latest[site_id] = result

    # Save the forecast before preparing prose so a summary problem cannot
    # discard a valid numeric result.
    st.session_state["result"] = result
    st.session_state["_result_request_key"] = request_key
    st.session_state.pop("_forecast_error", None)
    summary_backend = os.getenv("SUMMARY_BACKEND", "template")
    try:
        summary = summarize_forecast(result, backend=summary_backend)
    except Exception as exc:
        summary = summarize_forecast(result, backend="template")
        summary["warning"] = (
            f"Summary backend {summary_backend!r} failed ({exc}); showing the computed template."
        )
    st.session_state["summary"] = summary


def _render_comparison(result: dict) -> None:
    prior = st.session_state.get("_previous_success_by_site", {}).get(result.get("turbine_id"))
    if not prior or prior.get("fingerprint") == result.get("fingerprint"):
        return
    old_rows = {row["valid_at"]: row for row in prior.get("hours", [])}
    current_rows = {row["valid_at"]: row for row in result.get("hours", [])}
    common = sorted(old_rows.keys() & current_rows.keys())
    if not common:
        return
    comparison = pd.DataFrame([
        {
            "valid_at": valid_at,
            "previous_power_norm": old_rows[valid_at]["power_norm"],
            "current_power_norm": current_rows[valid_at]["power_norm"],
            "change": current_rows[valid_at]["power_norm"] - old_rows[valid_at]["power_norm"],
        }
        for valid_at in common
    ])
    mean_change = comparison["change"].abs().mean()
    changed = int((comparison["change"].abs() > 1e-12).sum())
    st.caption(
        f"Compared with the prior successful {result['turbine_id']} forecast: "
        f"{changed} of {len(common)} overlapping hours changed; mean absolute change "
        f"{mean_change:.3f} normalized power."
    )
    with st.expander("Compare overlapping hours"):
        st.dataframe(comparison, hide_index=True, use_container_width=True)


def _render_result(result: dict, summary: dict) -> None:
    st.subheader(f"{result['turbine_id']} forecast")
    status = result.get("weather_provenance", {}).get("provenance_status", "unknown")
    st.caption(
        f"Origin {result['origin']} UTC · {result['horizon_hours']} hours · "
        f"normalized power [0, 1] · weather provenance: {status}"
    )

    hours = result.get("hours", [])
    frame = pd.DataFrame(hours)
    if frame.empty:
        st.error("The successful result contains no hourly predictions.")
        return
    chart = frame.set_index("valid_at")[["power_norm"]].rename(
        columns={"power_norm": "Forecast"}
    )
    st.markdown("**Hourly normalized power**")
    st.line_chart(chart, height=260)
    st.markdown("**Hourly weather and output**")
    display_columns = [
        column for column in (
            "valid_at", "lead_hour", "wind_speed_ms", "temperature_c", "power_norm"
        ) if column in frame.columns
    ]
    st.dataframe(frame[display_columns], hide_index=True, use_container_width=True)

    st.markdown("**Computed analysis**")
    st.write(summary["text"])
    if summary.get("warning"):
        st.info(summary["warning"])
    st.caption(f"Summary backend: {summary['backend']} · forecast {summary['forecast_fingerprint']}")
    _render_comparison(result)

    try:
        csv_text = forecast_csv(result)
        st.download_button(
            "Download forecast CSV",
            data=csv_text,
            file_name=f"{result['turbine_id'].lower()}-forecast.csv",
            mime="text/csv",
            key="download_forecast",
        )
    except (KeyError, TypeError, ValueError) as exc:
        st.warning(f"CSV export is unavailable: {exc}")

    with st.expander("Weather provenance and executed steps"):
        st.markdown("**Weather provenance**")
        st.json(result.get("weather_provenance", {}))
        st.markdown("**Executed trace**")
        st.json(result.get("trace", []))
        st.markdown("**Model and training cutoff**")
        st.json({
            "model_id": result.get("model_id"),
            "train_last_interval_start": result.get("train_last_interval_start"),
            "run_id": result.get("run_id"),
            "cache_hit": result.get("cache_hit"),
        })


def main() -> None:
    st.set_page_config(page_title="Wind power forecast", page_icon="🌬️", layout="wide")
    st.title("Wind power forecast")
    st.caption(
        "Historical replay · forecast origins use 23:00 local time · source timezone and "
        "ten-minute interval interpretation are assumed · model cutoff: 2026-01-31 18:00 UTC"
    )

    mode = os.getenv("DATA_MODE", "fixture")
    if mode not in ("fixture", "archive"):
        st.error("DATA_MODE must be fixture or archive.")
        return
    if mode == "fixture":
        st.info("Demo mode uses synthetic weather and fictional fixture coordinates. Forecast values are normalized power, not MW or MWh.")

    try:
        sites = load_sites(mode=mode)
    except Exception as exc:
        st.error(f"Could not load the registered turbine map: {exc}")
        return
    if not isinstance(sites, list):
        st.error("The site registry did not return a list of registered turbines.")
        return
    sites = [site for site in sites if isinstance(site, dict) and site.get("turbine_id") in ("T1", "T2")]
    site_by_id = _site_index(sites)
    if not site_by_id:
        if mode == "archive":
            st.info("Archive mode is unavailable: verified site coordinates and an as-issued weather source are not configured. Set DATA_MODE=fixture for the local demo.")
            return
        st.error("No registered turbine sites are available.")
        return

    st.session_state.setdefault("selected_site", None)
    st.session_state.setdefault("origin_date", INITIAL_ORIGIN_DATE)
    st.session_state.setdefault("horizon", 48)

    map_col, control_col = st.columns([1.45, 1])
    with map_col:
        st.markdown("**Select a registered turbine**")
        map_result = st_folium(
            _make_map(sites, st.session_state.get("selected_site")),
            height=360,
            use_container_width=True,
            key="turbine_map",
            returned_objects=["last_object_clicked"],
        )
        marker_event = map_result.get("last_object_clicked") if isinstance(map_result, dict) else None
        marker_id = _resolve_marker(marker_event, sites)
        if marker_id:
            event_signature = fingerprint(marker_event)
            if event_signature != st.session_state.get("_last_map_selection_event"):
                st.session_state["_last_map_selection_event"] = event_signature
                st.session_state["selected_site"] = marker_id

    with control_col:
        st.markdown("**Forecast controls**")
        options = [None, "T1", "T2"]
        st.selectbox(
            "Turbine",
            options=options,
            key="selected_site",
            format_func=lambda value: "Choose a turbine" if value is None else value,
        )
        st.date_input("Forecast origin date", key="origin_date", min_value=date(2026, 1, 31))
        st.caption("Origin time: 23:00 in the selected turbine's local timezone.")
        st.selectbox("Horizon", options=[24, 48], key="horizon", format_func=lambda value: f"{value} hours")

        selected = st.session_state.get("selected_site")
        site = site_by_id.get(selected) if selected else None
        if selected and not site:
            st.warning(f"{selected} is not present in the active site registry.")
        if site:
            st.caption(
                f"{selected} · {float(site['latitude']):.4f}, {float(site['longitude']):.4f} · "
                f"{site.get('coordinate_status', 'configured')} coordinates"
            )
        else:
            st.caption("Choose a turbine marker or use the selector. Background map clicks are ignored.")

        button_col_a, button_col_b = st.columns(2)
        with button_col_a:
            st.button(
                "Predict generation",
                key="predict",
                disabled=site is None,
                on_click=_queue_action,
                args=("predict",),
                use_container_width=True,
            )
        with button_col_b:
            st.button(
                "Advance one day",
                key="advance",
                disabled=site is None,
                on_click=_queue_action,
                args=("advance",),
                use_container_width=True,
            )

    active_request = _request_for(site, st.session_state["origin_date"], st.session_state["horizon"], mode) if site else None
    active_key = fingerprint(active_request) if active_request else None
    if st.session_state.get("_result_request_key") != active_key:
        # Keep a successful run only in the same-site comparison cache. The
        # visible result and summary are removed as soon as an input changes.
        old_result = st.session_state.get("result")
        if old_result and old_result.get("status") == "ok":
            prior_latest = st.session_state.setdefault("_latest_success_by_site", {}).get(old_result.get("turbine_id"))
            if prior_latest is None:
                st.session_state["_latest_success_by_site"][old_result.get("turbine_id")] = old_result
        st.session_state.pop("result", None)
        st.session_state.pop("summary", None)
        st.session_state.pop("_result_request_key", None)

    action = st.session_state.pop("_run_action", None)
    if action and active_request and active_key:
        _run(active_request, active_key)
    elif action:
        st.warning("Choose a registered turbine before running a forecast.")

    error = st.session_state.get("_forecast_error")
    if error and error.get("request_key") == active_key:
        st.error(f"{error['code']}: {error['message']}")
    result = st.session_state.get("result")
    summary = st.session_state.get("summary")
    if result and summary and st.session_state.get("_result_request_key") == active_key:
        _render_result(result, summary)
    elif not error or error.get("request_key") != active_key:
        st.caption("Forecasts are calculated only after you select a turbine and choose an action.")


if __name__ == "__main__":
    main()
