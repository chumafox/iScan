from __future__ import annotations

import json

from typer.testing import CliRunner

from iscan.cli import app


def test_report_json_progress_is_machine_readable(monkeypatch, tmp_path, fake_lockdown):
    import iscan.device as device

    async def fake_connect(*args, **kwargs):
        return fake_lockdown

    async def fake_close(lockdown):
        return None

    monkeypatch.setattr(device, "connect_async", fake_connect)
    monkeypatch.setattr(device, "close_async", fake_close)

    output = tmp_path / "report.html"
    result = CliRunner().invoke(
        app,
        [
            "report",
            "--json-progress",
            "--output",
            str(output),
            "--timeout",
            "1",
        ],
    )
    assert result.exit_code == 0, result.stdout
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert events[0]["event"] == "start"
    assert any(event.get("event") == "saved" for event in events)
    assert output.exists()
    assert "Report saved:" not in result.stdout
