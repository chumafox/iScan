from iscan.models import Battery


async def collect_async(lockdown) -> Battery:
    bat = Battery()

    # Primary: DiagnosticsService.get_battery() — works on iOS 17.4+/27 without tunnel
    try:
        from pymobiledevice3.services.diagnostics import DiagnosticsService
        diag = DiagnosticsService(lockdown)
        data = await diag.get_battery()

        bat.cycle_count = data.get('CycleCount')
        bat.is_charging = data.get('IsCharging')
        bat.battery_serial = data.get('Serial')

        # MaxCapacity = Battery Health % (same as iOS Settings → Battery → Battery Health)
        max_cap = data.get('MaxCapacity')
        if max_cap is not None:
            bat.health_percent = float(max_cap)

        # Capacity data from BatteryData sub-dict
        battery_data = data.get('BatteryData', {})
        if isinstance(battery_data, dict):
            bat.design_capacity = battery_data.get('DesignCapacity')
            fcc = battery_data.get('FullChargeCapacity')
            # FCC is in raw gas gauge units — only store if design_capacity matches scale
            if bat.design_capacity and fcc and fcc <= bat.design_capacity * 2:
                bat.full_charge_capacity = fcc

        return bat
    except Exception:
        pass

    # Fallback: lockdown domain (works on iOS ≤17.3)
    try:
        v = await lockdown.get_value(domain='com.apple.mobile.battery') or {}
        bat.cycle_count = v.get('CycleCount')
        bat.design_capacity = v.get('DesignCapacity')
        bat.full_charge_capacity = v.get('FullChargeCapacity')
        bat.battery_serial = v.get('BatterySerialNumber') or v.get('BatterySerial')
        bat.is_charging = v.get('IsCharging') or v.get('BatteryIsCharging')
        if bat.design_capacity and bat.full_charge_capacity and bat.design_capacity > 0:
            bat.health_percent = round(bat.full_charge_capacity / bat.design_capacity * 100, 1)
    except Exception:
        pass

    return bat


def collect(lockdown) -> Battery:
    """Sync fallback for tests using fixture."""
    bat = Battery()
    try:
        v = lockdown.get_value(domain='com.apple.mobile.battery') or {}
        bat.cycle_count = v.get('CycleCount')
        bat.design_capacity = v.get('DesignCapacity')
        bat.full_charge_capacity = v.get('FullChargeCapacity')
        bat.battery_serial = v.get('BatterySerialNumber') or v.get('BatterySerial')
        bat.is_charging = v.get('IsCharging') or v.get('BatteryIsCharging')
        if bat.design_capacity and bat.full_charge_capacity and bat.design_capacity > 0:
            bat.health_percent = round(bat.full_charge_capacity / bat.design_capacity * 100, 1)
    except Exception:
        pass
    return bat
