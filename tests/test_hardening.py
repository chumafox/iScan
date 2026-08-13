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


def test_slow_first_collector_does_not_starve_later_ones(monkeypatch, fake_lockdown):
    """A timed-out service must not consume the timeout budget of siblings.

    The old gather()+Lock design counted lock-wait against every collector, so
    a slow device_info made battery/storage/components time out without running.
    """
    from iscan.collectors import battery as battery_mod
    from iscan.collectors import device_info
    from iscan.models import Battery

    async def slow(_lockdown):
        await asyncio.sleep(0.08)
        return device_info.collect(_lockdown)

    async def instant(_lockdown):
        return battery_mod.collect(_lockdown)

    monkeypatch.setattr(device_info, "collect_async", slow)
    monkeypatch.setattr(battery_mod, "collect_async", instant)
    report = asyncio.run(collect_all(fake_lockdown, timeout=0.02))
    assert report.collection["device_info"]["status"] == "timeout"
    assert report.collection["battery"]["status"] != "timeout"
    assert isinstance(report.battery, Battery)
    assert report.battery.cycle_count == 127


def test_progress_events_are_json_lines(capsys):
    from iscan.cli import Progress

    Progress(json_mode=True).emit({"event": "saved", "path": "/tmp/report.html"})
    output = capsys.readouterr().out.strip()
    assert output == '{"event":"saved","path":"/tmp/report.html"}'
