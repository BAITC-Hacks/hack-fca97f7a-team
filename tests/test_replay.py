from pathlib import Path

from backend.core.contracts import FIRST_ORIGIN, expected_hours
from scripts.replay import run_replay


def result(request):
    return {**request, "status": "ok", "fingerprint": "sha256:example", "model_id": "test-model",
            "run_id": "test-run", "model_input": {"sha256": "input"},
            "train_last_interval_start": "2026-01-31T17:00:00Z",
            "weather_provenance": {"provenance_status": "verified", "initialized_at": FIRST_ORIGIN,
                                   "available_at": FIRST_ORIGIN},
            "hours": [{"valid_at": stamp, "lead_hour": i, "power_norm": .3}
                      for i, stamp in enumerate(expected_hours(request["origin"], 48), 1)]}


def test_full_replay_has_2688_rows_and_march_spillover(tmp_path):
    report = run_replay(tmp_path, forecast=result)
    assert report["full_february_replay"] and report["actual_rows"] == 2688
    assert report["completed_runs"] == 56 and report["march_spillover_rows"] == 48
    content = (tmp_path / 'forecast.csv').read_text()
    assert len(content.splitlines()) == 2689 and 'baseline' not in content


def test_partial_replay_reports_every_missing_run_and_removes_stale_complete_file(tmp_path):
    (tmp_path / 'forecast.csv').write_text('old complete result')
    report = run_replay(tmp_path, forecast=lambda request: {"status": "error", "code": "WEATHER_UNAVAILABLE",
                                                          "message": "Нет свидетельства"})
    assert report["status"] == "incomplete" and len(report["failures"]) == 56
    assert not report["full_february_replay"] and not (tmp_path / 'forecast.csv').exists()
    assert report["actual_rows"] == 0


def test_duplicate_hour_and_unverified_archive_fail_closed(tmp_path):
    def bad(request):
        output = result(request)
        if request['turbine_id'] == 'T1':
            output['hours'][1]['valid_at'] = output['hours'][0]['valid_at']
        else:
            output['weather_provenance']['provenance_status'] = 'live'
        return output
    report = run_replay(tmp_path, days=1, forecast=bad)
    assert report['actual_rows'] == 0 and len(report['failures']) == 2
    assert all(item['code'] == 'REPLAY_INVALID' for item in report['failures'])


def documented_result(request):
    output = result(request)
    output['weather_provenance'] = {
        'provenance_status': 'provider_documented',
        'initialized_at': '2026-01-30T00:00:00Z',
        'available_at': None,
        'assumed_available_by': '2026-01-31T00:00:00Z',
        'availability_verified': False,
        'availability_basis': 'provider_documented_conservative_24h',
    }
    return output


def test_documented_replay_complete_but_never_certified(tmp_path):
    (tmp_path / 'forecast.csv').write_text('stale verified output')
    report = run_replay(tmp_path, weather_source='provider-documented', forecast=documented_result)
    assert report['status'] == 'ok' and report['complete_forecast_coverage']
    assert report['actual_rows'] == 2688 and report['completed_runs'] == 56
    assert report['daily_rows'] == 1344
    import csv
    daily = list(csv.DictReader((tmp_path / report['daily_output_file']).open()))
    assert len({(row['turbine_id'], row['valid_at']) for row in daily}) == 1344
    assert min(row['valid_at'] for row in daily) == '2026-01-31T19:00:00Z'
    assert max(row['valid_at'] for row in daily) == '2026-02-28T18:00:00Z'
    assert not report['historical_availability_verified'] and not report['full_february_replay']
    assert report['output_file'] == 'documented_forecast.csv'
    assert not (tmp_path / 'forecast.csv').exists()
    assert 'provider_documented' in (tmp_path / report['output_file']).read_text()


def test_documented_replay_requires_opt_in_and_rejects_fake_verification(tmp_path):
    strict = run_replay(tmp_path, days=1, forecast=documented_result)
    assert strict['actual_rows'] == 0
    def forged(request):
        output = documented_result(request)
        output['weather_provenance']['availability_verified'] = True
        return output
    report = run_replay(tmp_path, days=1, weather_source='provider-documented', forecast=forged)
    assert report['actual_rows'] == 0 and len(report['failures']) == 2
