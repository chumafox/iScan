from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from iscan.models import DiagnosticReport
from iscan.report.i18n import get_strings

TEMPLATES_DIR = Path(__file__).parent / 'templates'


def _fmt_bytes(b):
    if b is None:
        return None
    gb = b / 1024**3
    return f"{gb:.1f} GB"


def _decode_display_vendor(serial: str) -> str:
    if not serial:
        return ""
    prefix = serial[:3].upper()
    if prefix in ['G9Q', 'G9N', 'G9P', 'G3H', 'GH']:
        return "Samsung"
    if prefix in ['F7C', 'DKH', 'H3', 'H4']:
        return "LG Display"
    if prefix in ['C11', 'FVQ', 'C3F']:
        return "Sharp"
    if prefix in ['DSH', 'DOP', 'BOE', 'F8C']:
        return "BOE"
    return ""


def _decode_battery_vendor(serial: str) -> str:
    if not serial:
        return ""
    prefix = serial[:3].upper()
    if prefix in ['F5D', 'F6D', 'DY9', 'F2D']:
        return "Desay"
    if prefix in ['F7D', 'F8Y', 'F9G', 'C8A', 'C8W']:
        return "Sunwoda"
    if prefix in ['D85', 'D8D', 'D8T']:
        return "ATL"
    return ""


def _decode_biometric_vendor(serial: str) -> str:
    if not serial:
        return ""
    prefix = serial[:3].upper()
    if prefix in ['FWP', 'F0X', 'F7C']:
        return "LG Innotek"
    if prefix.startswith('ME') or prefix == 'PER':
        return "STMicroelectronics"
    return ""


def _get_component_statuses(report: DiagnosticReport) -> dict[str, str]:
    """
    Determine the status of each component (normal, replaced, warning).
    Returns a dict mapping component key to status string.
    """
    statuses = {}
    
    # SSD Upgrade detection (e.g. iPhone 12 mini max capacity was 256GB)
    total_cap = report.storage.total_capacity or 0
    prod_type = report.device.product_type or ""
    
    # 256 GB is approx 274,877,906,944 bytes
    max_factory_bytes = 275 * (1024**3)
    
    if prod_type == "iPhone13,1" and total_cap > max_factory_bytes:
        statuses['ssd'] = 'replaced'  # Storage upgraded (扩容)
    else:
        statuses['ssd'] = 'normal' if report.components.ssd_serial else 'unknown'
        
    # Battery wear or manipulation detection
    health = report.battery.health_percent
    design = report.battery.design_capacity or 0
    fcc = report.battery.full_charge_capacity or 0
    
    is_manipulated = fcc > design * 1.1 and design > 0
    
    if is_manipulated:
        statuses['battery_fcc'] = 'warning'
        statuses['battery'] = 'warning'
    elif health is not None and health < 80:
        statuses['battery_fcc'] = 'normal'
        statuses['battery'] = 'warning'
    else:
        statuses['battery_fcc'] = 'normal'
        statuses['battery'] = 'normal' if report.battery.battery_serial else 'unknown'

        
    # Other components defaults
    statuses['mlb'] = 'normal' if report.components.mlb_serial else 'unknown'
    statuses['wifi'] = 'normal' if report.components.wireless_board_serial else 'unknown'
    statuses['display'] = 'normal' if report.components.display_serial else 'unknown'
    statuses['touch'] = 'normal' if report.components.touch_serial else 'unknown'
    statuses['biometric'] = 'normal' if report.components.biometric_serial else 'unknown'
    statuses['als'] = 'normal' if report.components.als_serial else 'unknown'
    
    # General device info
    statuses['serial'] = 'normal' if report.device.serial_number else 'unknown'
    statuses['udid'] = 'normal' if report.device.udid else 'unknown'
    statuses['sim'] = 'normal' if report.device.sim_status == 'no_restrictions' else 'warning'
    
    return statuses


def render_html(report: DiagnosticReport, lang: str = 'en') -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template('report.html.j2')
    s = get_strings(lang)
    
    # Format storage
    storage_fmt = {
        'total': _fmt_bytes(report.storage.total_capacity),
        'available': _fmt_bytes(report.storage.available),
        'used': _fmt_bytes(report.storage.used),
        'used_percent': report.storage.used_percent,
    }
    
    # Decode vendors
    decoded_vendors = {
        'display': _decode_display_vendor(report.components.display_serial),
        'battery': _decode_battery_vendor(report.battery.battery_serial),
        'biometric': _decode_biometric_vendor(report.components.biometric_serial),
    }
    
    # Get statuses
    statuses = _get_component_statuses(report)
    
    # Battery health color
    health = report.battery.health_percent
    if health is None:
        health_color = '#6b7280'
    elif health >= 90:
        health_color = '#22c55e'
    elif health >= 80:
        health_color = '#f59e0b'
    else:
        health_color = '#ef4444'
    
    return template.render(
        r=report,
        s=s,
        lang=lang,
        storage=storage_fmt,
        health_color=health_color,
        decoded=decoded_vendors,
        status=statuses,
    )
