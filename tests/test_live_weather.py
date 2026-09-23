"""Live weather goes through HTTP normalization, real CSV and fitted models; HTTP is mocked."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import api
from backend.services import agent
from backend.adapters import weather
from backend.core.contracts import expected_hours, iso


@pytest.fixture
def live_http(monkeypatch):
    origin = iso(datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0))
    payload = {'latitude': 43.62, 'longitude': 78.48, 'timezone': 'GMT', 'utc_offset_seconds': 0,
               'hourly_units': {'time': 'iso8601', 'wind_speed_10m': 'm/s', 'temperature_2m': '°C'},
               'hourly': {'time': [s[:-1] for s in expected_hours(origin, 48)],
                          'wind_speed_10m': [6.] * 48, 'temperature_2m': [12.] * 48}}
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, content=json.dumps(payload).encode())
    monkeypatch.setattr(weather.httpx, 'get', get)
    return origin, payload, calls


@pytest.mark.parametrize('site,horizon', [('T1',24), ('T2',48)])
def test_live_api_csv_and_current_server_origin(site, horizon, live_http, provider_model_factory, monkeypatch):
    def load(turbine, *, profile):
        assert profile == 'open_meteo_ecmwf_ifs_10m'
        return provider_model_factory(turbine)
    monkeypatch.setattr(agent, 'load_model', load)
    origin, payload, calls = live_http
    client = TestClient(api.app)
    response = client.post('/api/forecasts', json={'turbine_id': site, 'origin': '2026-01-31T18:00:00Z',
                                                 'horizon_hours': horizon, 'mode': 'live'})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['origin'] == origin and len(result['hours']) == horizon
    assert result['hours'][0]['valid_at'] == iso(datetime.fromisoformat(origin.replace('Z', '+00:00')) + timedelta(hours=1))
    assert result['weather_provenance']['provenance_status'] == 'live'
    assert result['weather_provenance']['initialized_at'] is None
    assert calls[0][0] == weather.LIVE_URL
    assert calls[0][1]['params']['models'] == 'ecmwf_ifs'
    assert result['model_provenance']['forecast_accuracy_verified'] is False
    assert calls[0][1]['params']['latitude'] == next(s for s in weather.SITES if s['turbine_id'] == site)['latitude']
    csv = client.get(f"/api/forecasts/{result['forecast_id']}/download?kind=model-input")
    assert csv.status_code == 200 and len(csv.text.splitlines()) == horizon + 1
    assert all(h['wind_speed_ms'] == 6. for h in result['hours'])


def test_live_rejects_wrong_model_domain(live_http, monkeypatch, provider_model_factory):
    fitted = provider_model_factory('T1')
    fitted.metadata['profile'] = 'measured'
    result = agent.run_forecast({'turbine_id': 'T1', 'origin': live_http[0],
        'horizon_hours': 24, 'mode': 'live'}, model_loader=lambda site: fitted)
    assert result['code'] == 'MODEL_UNAVAILABLE'


def test_live_rejects_wrong_wind_height(live_http, provider_model_factory):
    def wrong(site, origin, horizon, mode):
        bundle = weather.fetch_weather(site, origin, horizon, mode)
        bundle['manifest']['wind_height_m'] = 100
        return bundle
    result = agent.run_forecast({'turbine_id': 'T1', 'origin': live_http[0],
        'horizon_hours': 24, 'mode': 'live'}, weather_tool=wrong,
        model_loader=provider_model_factory)
    assert result['code'] == 'MODEL_UNAVAILABLE'


def test_missing_live_hour_fails_without_fixture_fallback(live_http):
    origin, payload, calls = live_http
    for values in payload['hourly'].values(): values.pop(0)
    with pytest.raises(Exception) as exc:
        weather.fetch_weather(weather.SITES[0], origin, 24, 'live')
    assert exc.value.code == 'DATA_INVALID'


def test_live_provider_failure_is_not_synthetic(live_http, monkeypatch):
    origin, _, _ = live_http
    monkeypatch.setattr(weather.httpx, 'get', lambda *a, **k: httpx.Response(429))
    with pytest.raises(Exception) as exc:
        weather.fetch_weather(weather.SITES[0], origin, 24, 'live')
    assert exc.value.code == 'WEATHER_UNAVAILABLE'
