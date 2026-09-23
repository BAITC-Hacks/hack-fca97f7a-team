"""Historical Forecast training cache is retrospective and fully verified offline."""
import hashlib
import json
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from scripts.fetch_training_weather import fetch_training_weather, load_training_weather


def _payload(start: date, end: date, *, wind=6.0):
    first = datetime.combine(start, datetime.min.time(), timezone.utc)
    count = ((end - start).days + 1) * 24
    return {"latitude": 43.620384, "longitude": 78.47891,
            "timezone": "GMT", "utc_offset_seconds": 0,
            "hourly_units": {"time": "iso8601", "wind_speed_10m": "m/s",
                             "temperature_2m": "°C"},
            "hourly": {"time": [(first + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00")
                                for i in range(count)],
                       "wind_speed_10m": [wind] * count,
                       "temperature_2m": [-4.0] * count}}


class FakeClient:
    def __init__(self, mutate=None):
        self.calls = []
        self.mutate = mutate

    def get(self, url, *, params, timeout, follow_redirects):
        self.calls.append((url, dict(params)))
        data = _payload(date.fromisoformat(params["start_date"]),
                        date.fromisoformat(params["end_date"]))
        if self.mutate:
            self.mutate(data)
        return httpx.Response(200, content=json.dumps(data).encode(),
                              request=httpx.Request("GET", url))


def test_fetch_cutoff_and_verified_offline_reuse(tmp_path):
    client = FakeClient()
    result = fetch_training_weather(date(2026, 1, 31), date(2026, 1, 31), tmp_path,
                                    client=client)
    assert result["row_count"] == 36  # 18 completed hours per turbine
    assert result["excluded_uncompleted_hours"] == 12
    assert result["availability_at_origin"] == "UNVERIFIED"
    assert result["not_runtime_archive_evidence"] is True
    assert len(client.calls) == 2
    assert all(p["models"] == "ecmwf_ifs" and p["wind_speed_unit"] == "ms"
               and p["timezone"] == "UTC" for _, p in client.calls)
    frame, loaded = load_training_weather(tmp_path)
    assert len(frame) == 36
    assert str(frame.timestamp.dtype).endswith(", UTC]")
    assert frame.timestamp.max().isoformat() == "2026-01-31T17:00:00+00:00"
    assert loaded["csv_sha256"] == hashlib.sha256((tmp_path / "training_weather.csv").read_bytes()).hexdigest()
    offline = FakeClient()
    replay = fetch_training_weather(date(2026, 1, 31), date(2026, 1, 31), tmp_path,
                                    cache_only=True, client=offline)
    assert not offline.calls and replay["csv_sha256"] == result["csv_sha256"]


@pytest.mark.parametrize("mutate", [
    lambda d: d["hourly_units"].update(wind_speed_10m="km/h"),
    lambda d: d.update(utc_offset_seconds=21600),
    lambda d: d.update(latitude=0),
    lambda d: d["hourly"]["time"].__setitem__(1, d["hourly"]["time"][0]),
    lambda d: d["hourly"]["wind_speed_10m"].pop(),
    lambda d: d["hourly"]["wind_speed_10m"].__setitem__(1, None),
    lambda d: d["hourly"]["wind_speed_10m"].__setitem__(1, -1),
    lambda d: d["hourly"]["wind_speed_10m"].__setitem__(1, float("inf")),
])
def test_invalid_response_not_cached(tmp_path, mutate):
    with pytest.raises(ValueError):
        fetch_training_weather(date(2026, 1, 1), date(2026, 1, 1), tmp_path,
                               client=FakeClient(mutate))
    assert not list((tmp_path / "requests").glob("*.json"))


def test_missing_cache_never_calls_network(tmp_path):
    client = FakeClient()
    with pytest.raises(FileNotFoundError):
        fetch_training_weather(date(2026, 1, 1), date(2026, 1, 1), tmp_path,
                               cache_only=True, client=client)
    assert client.calls == []


def test_loader_rejects_tampered_manifest_and_csv(tmp_path):
    fetch_training_weather(date(2026, 1, 1), date(2026, 1, 1), tmp_path,
                           client=FakeClient())
    csv_path = tmp_path / "training_weather.csv"
    original = csv_path.read_bytes()
    csv_path.write_bytes(original.replace(b",6.0,", b",7.0,", 1))
    with pytest.raises(ValueError, match="checksum"):
        load_training_weather(tmp_path)
    csv_path.write_bytes(original)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["requests"][0]["request"]["params"]["latitude"] = 0
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="identity"):
        load_training_weather(tmp_path)


def test_loader_rejects_corrupt_raw_and_unverified_kind(tmp_path):
    manifest = fetch_training_weather(date(2026, 1, 1), date(2026, 1, 1), tmp_path,
                                      client=FakeClient())
    path = tmp_path / "raw" / f"{manifest['requests'][0]['raw_sha256']}.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="checksum"):
        load_training_weather(tmp_path)


def test_cache_reuse_rejects_forged_provenance(tmp_path):
    fetch_training_weather(date(2026, 1, 1), date(2026, 1, 1), tmp_path,
                           client=FakeClient())
    index_path = next((tmp_path / "requests").glob("*.json"))
    index = json.loads(index_path.read_text())
    index["availability_at_origin"] = "verified"
    index_path.write_text(json.dumps(index))
    with pytest.raises(ValueError, match="cache index"):
        fetch_training_weather(date(2026, 1, 1), date(2026, 1, 1), tmp_path,
                               cache_only=True, client=FakeClient())
