from iscan.models import DiagnosticReport, Identifiers
from iscan.collectors import device_info, battery, storage, components


async def collect_all(lockdown) -> DiagnosticReport:
    """
    Collect full diagnostics from connected iOS device.

    Args:
        lockdown: pymobiledevice3 LockdownClient instance.
    """
    report = DiagnosticReport()
    report.device = await device_info.collect_async(lockdown)
    report.identifiers = _collect_identifiers(lockdown)
    report.battery = await battery.collect_async(lockdown)
    report.storage = await storage.collect_async(lockdown)
    report.components = await components._collect_async(lockdown)

    return report


def _collect_identifiers(lockdown) -> Identifiers:
    ids = Identifiers()
    try:
        v = lockdown.all_values
        ids.imei = v.get('InternationalMobileEquipmentIdentity')
        ids.imei2 = v.get('InternationalMobileEquipmentIdentity2')
        ecid = v.get('UniqueChipID')
        ids.ecid = str(ecid) if ecid else None
        ids.wifi_mac = v.get('WiFiAddress') or v.get('EthernetAddress')
        ids.bt_mac = v.get('BluetoothAddress')
        ids.meid = v.get('MobileEquipmentIdentifier')
    except Exception:
        pass
    return ids
