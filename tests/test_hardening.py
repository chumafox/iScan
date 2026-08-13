from __future__ import annotations

import asyncio

from iscan.collectors import collect_all
from iscan.models import DeviceInfo, DiagnosticReport, TransportInfo
from iscan.report.render import render_html


def test_report_escapes_device_controlled_values_and_has_no_local_assets():
    report = DiagnosticReport(
        device=DeviceInfo(
            commercial_name="iPhone <script>alert(1)</script>",
            device_name='Store "A" & demo',
        ),
        transport=TransportInfo(
            address="/tmp/usbmuxd.sock",
            kind="unix",
            source="cli",
        ),
    )
    html = render_html(report, "en")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "file:///Users/" not in html
    assert "Content-Security-Policy" in html


def test_collection_timeout_creates_partial_report(monkeypatch, fake_lockdown):
    from iscan.collectors import battery

    async def slow(_lockdown):
        await asyncio.sleep(0.05)
        return battery.Battery()

    monkeypatch.setattr(battery, "collect_async", slow)
    report = asyncio.run(collect_all(fake_lockdown, timeout=0.01))
    assert report.collection["battery"]["status"] == "timeout"
    assert report.is_partial is True
    assert any(issue.collector == "battery" for issue in report.issues)


def test_progress_events_are_json_lines(capsys):
    from iscan.cli import Progress

    Progress(json_mode=True).emit({"event": "saved", "path": "/tmp/report.html"})
    output = capsys.readouterr().out.strip()
    assert output == '{"event":"saved","path":"/tmp/report.html"}'
