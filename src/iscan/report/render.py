"""HTML rendering for diagnostic reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from iscan.catalog import FACTORY_MAX_STORAGE_GIB
from iscan.models import DiagnosticReport
from iscan.report.i18n import get_strings

TEMPLATES_DIR = Path(__file__).parent / "templates"
_ENV: Environment | None = None


def _jinja_env() -> Environment:
    global _ENV
    if _ENV is None:
        _ENV = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=select_autoescape(enabled_extensions=("html", "j2", "xml")),
        )
    return _ENV


def _fmt_bytes(value: Any) -> str | None:
    if value is None:
        return None
    try:
        gib = int(value) / 1024**3
    except (TypeError, ValueError, OverflowError):
        return None
    return f"{gib:.1f} GiB"


def _decode_display_vendor(serial: str | None) -> str:
    if not serial:
        return ""
    prefix = serial[:3].upper()
    if prefix in {"G9Q", "G9N", "G9P", "G3H", "GH"}:
        return "Samsung"
    if prefix in {"F7C", "DKH", "H3", "H4"}:
        return "LG Display"
    if prefix in {"C11", "FVQ", "C3F"}:
        return "Sharp"
    if prefix in {"DSH", "DOP", "BOE", "F8C"}:
        return "BOE"
    return ""


def _decode_battery_vendor(serial: str | None) -> str:
    if not serial:
        return ""
    prefix = serial[:3].upper()
    if prefix in {"F5D", "F6D", "DY9", "F2D"}:
        return "Desay"
    if prefix in {"F7D", "F8Y", "F9G", "C8A", "C8W"}:
        return "Sunwoda"
    if prefix in {"D85", "D8D", "D8T"}:
        return "ATL"
    return ""


def _decode_biometric_vendor(serial: str | None) -> str:
    if not serial:
        return ""
    prefix = serial[:3].upper()
    if prefix in {"FWP", "F0X", "F7C"}:
        return "LG Innotek"
    if prefix.startswith("ME") or prefix == "PER":
        return "STMicroelectronics"
    return ""


def _get_component_statuses(report: DiagnosticReport) -> dict[str, str]:
    statuses: dict[str, str] = {}
    health = report.battery.health_percent
    if health is not None and health < 80:
        statuses["battery"] = "warning"
    elif report.battery.battery_serial or health is not None:
        statuses["battery"] = "normal"
    else:
        statuses["battery"] = "unknown"

    design = report.battery.design_capacity or 0
    fcc = report.battery.full_charge_capacity or 0
    statuses["battery_fcc"] = "warning" if design and fcc > design * 1.1 else "normal"

    # Serial presence is evidence that the field was read, not proof that a
    # part is original.  The report intentionally avoids claiming replacement
    # without an Apple service/configuration signal.
    fields = {
        "mlb": report.components.mlb_serial,
        "wifi": report.components.wireless_board_serial,
        "ssd": report.components.ssd_serial,
        "display": report.components.display_serial,
        "touch": report.components.touch_serial,
        "rear_camera": report.components.rear_camera_serial,
        "front_camera": report.components.front_camera_serial,
        "biometric": report.components.biometric_serial,
        "als": report.components.als_serial,
    }
    statuses.update({key: "normal" if value else "unknown" for key, value in fields.items()})

    # A capacity above the documented factory maximum is an anomaly worth
    # flagging, not proof that a board was replaced.  Keep the conservative
    # check that existed in 0.1 for the most common expansion case.
    factory_max_gib = FACTORY_MAX_STORAGE_GIB.get(report.device.product_type or "")
    if factory_max_gib and report.storage.total_capacity:
        if report.storage.total_capacity > factory_max_gib * 1.08 * 1024**3:
            statuses["ssd"] = "replaced"
    statuses["serial"] = "normal" if report.device.serial_number else "unknown"
    statuses["udid"] = "normal" if report.device.udid else "unknown"
    statuses["sim"] = {
        "no_restrictions": "normal",
        "locked": "warning",
    }.get(report.device.sim_status, "unknown")
    return statuses


def _health_color(health: float | None) -> str:
    if health is None:
        return "#6b7280"
    if health >= 90:
        return "#22c55e"
    if health >= 80:
        return "#f59e0b"
    return "#ef4444"


def render_html(report: DiagnosticReport, lang: str = "en") -> str:
    """Render a self-contained, escaped HTML report."""

    template = _jinja_env().get_template("report.html.j2")
    strings = get_strings(lang)
    storage_fmt = {
        "total": _fmt_bytes(report.storage.total_capacity),
        "available": _fmt_bytes(report.storage.available),
        "used": _fmt_bytes(report.storage.used),
        "used_percent": report.storage.used_percent,
    }
    decoded = {
        "display": _decode_display_vendor(report.components.display_serial),
        "battery": _decode_battery_vendor(report.battery.battery_serial),
        "biometric": _decode_biometric_vendor(report.components.biometric_serial),
    }
    return template.render(
        r=report,
        s=strings,
        lang=lang if lang in {"en", "ru"} else "en",
        storage=storage_fmt,
        health_color=_health_color(report.battery.health_percent),
        decoded=decoded,
        status=_get_component_statuses(report),
    )
