import json

import pytest

from scripts.package_replay import package_replay


def test_package_rejects_incomplete_or_misleading_replay(tmp_path):
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    destination = tmp_path / "bundle"
    (report_dir / "report.json").write_text(json.dumps({"status": "incomplete",
                                                        "weather_source": "provider-documented"}))
    with pytest.raises(ValueError, match="incomplete"):
        package_replay(report_dir, destination)
    assert not destination.exists()
    (report_dir / "report.json").write_text(json.dumps({"status": "ok", "mode": "archive",
                                                        "weather_source": "provider-documented",
                                                        "full_february_replay": True,
                                                        "historical_availability_verified": True}))
    with pytest.raises(ValueError, match="verified availability"):
        package_replay(report_dir, destination)
    assert not destination.exists()
