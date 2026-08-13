from iscan.collectors import collect_all
from iscan.report.render import render_html
from iscan.models import DiagnosticReport

import asyncio

def test_render_en(fake_lockdown, monkeypatch):
    """HTML renders without errors in English."""
    import iscan.collectors.components as comp_mod
    # patch DiagnosticsService to avoid real device
    from tests.conftest import FakeDiagnosticsService
    try:
        monkeypatch.setattr(
            'pymobiledevice3.services.diagnostics.DiagnosticsService',
            FakeDiagnosticsService,
        )
    except Exception:
        pass
    report = asyncio.run(collect_all(fake_lockdown))
    html = render_html(report, 'en')
    assert '<html' in html.lower()
    assert 'C3XNHF2KMT4P' in html  # serial in report
    assert 'Battery Health' in html
    assert 'N/A' not in html or html.count('N/A') < 30  # most fields filled

def test_render_ru(fake_lockdown, monkeypatch):
    """HTML renders in Russian."""
    from tests.conftest import FakeDiagnosticsService
    try:
        monkeypatch.setattr(
            'pymobiledevice3.services.diagnostics.DiagnosticsService',
            FakeDiagnosticsService,
        )
    except Exception:
        pass
    report = asyncio.run(collect_all(fake_lockdown))
    html = render_html(report, 'ru')
    assert 'Аккумулятор' in html
    assert 'C3XNHF2KMT4P' in html


def test_render_missing_data():
    """Report with all None values renders without crash."""
    report = DiagnosticReport()
    html = render_html(report, 'en')
    assert '<html' in html.lower()
    # All fields should show N/A
    assert 'N/A' in html
