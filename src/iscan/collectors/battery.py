"""Battery diagnostics with compatibility fallbacks across iOS releases."""

from __future__ import annotations

from typing import Any, Mapping

from iscan.collectors.common import as_bool, as_float, as_int, call_maybe_async, decode_value, first_value
from iscan.models import Battery


def _capacity(value: Any) -> int | None:
    parsed = as_int(value)
    return parsed if parsed is not None and parsed > 0 else None


def _populate(battery: Battery, values: Mapping[str, Any]) -> Battery:
    v = dict(values)
    nested = v.get("BatteryData")
    battery_data = nested if isinstance(nested, Mapping) else {}

    battery.cycle_count = as_int(first_value(v, ("CycleCount", "CycleCountTotal")))
    battery.is_charging = as_bool(
        first_value(v, ("IsCharging", "BatteryIsCharging", "Charging"))
    )
    serial = first_value(v, ("Serial", "BatterySerialNumber", "BatterySerial"))
    battery.battery_serial = decode_value(serial)

    battery.design_capacity = _capacity(
        first_value(
            v,
            ("DesignCapacity", "NominalChargeCapacity", "AppleRawDesignCapacity"),
        )
        or first_value(
            dict(battery_data),
            ("DesignCapacity", "NominalChargeCapacity", "AppleRawDesignCapacity"),
        )
    )
    battery.full_charge_capacity = _capacity(
        first_value(
            v,
            (
                "FullChargeCapacity",
                "AppleRawMaxCapacity",
                "RawMaxCapacity",
                "MaxCapacityRaw",
            ),
        )
        or first_value(
            dict(battery_data),
            (
                "FullChargeCapacity",
                "AppleRawMaxCapacity",
                "RawMaxCapacity",
                "MaxCapacityRaw",
            ),
        )
    )

    health = as_float(first_value(v, ("MaxCapacity", "BatteryHealth")))
    # A few devices expose MaxCapacity as a fraction rather than a percent.
    if health is not None and 0 < health <= 1:
        health *= 100
    if health is not None and 0 <= health <= 100:
        battery.health_percent = round(health, 1)
    elif (
        battery.design_capacity
        and battery.full_charge_capacity
        and battery.design_capacity > 0
    ):
        # Do not calculate a nonsensical value when one iOS version reports raw
        # gas-gauge units with a different scale.
        ratio = battery.full_charge_capacity / battery.design_capacity
        if 0 < ratio <= 1.5:
            battery.health_percent = round(min(ratio * 100, 100), 1)

    # If the raw maximum capacity is already in gauge units, retain it only
    # when it is close enough to the design scale to be useful.  Otherwise the
    # percentage remains valid while the ambiguous mAh field is omitted.
    if (
        battery.design_capacity
        and battery.full_charge_capacity
        and battery.full_charge_capacity > battery.design_capacity * 2
    ):
        battery.full_charge_capacity = None
    return battery


def _from_mapping(values: Any) -> Battery:
    battery = Battery()
    if isinstance(values, Mapping):
        _populate(battery, values)
    return battery


async def collect_async(lockdown) -> Battery:
    battery = Battery()

    # Primary source: DiagnosticsService / IOPMPowerSource.  It is available
    # on modern iOS and works through NetworkUSB without a separate DVT tunnel.
    try:
        from pymobiledevice3.services.diagnostics import DiagnosticsService

        data = await call_maybe_async(DiagnosticsService(lockdown).get_battery)
        if isinstance(data, Mapping):
            _populate(battery, data)
    except Exception:
        pass

    # Fallback: the lockdown battery domain used by older iOS releases.
    if battery.health_percent is None or battery.cycle_count is None:
        try:
            values = await call_maybe_async(
                lockdown.get_value, domain="com.apple.mobile.battery"
            )
            fallback = _from_mapping(values)
            for name, value in vars(fallback).items():
                if getattr(battery, name) is None and value is not None:
                    setattr(battery, name, value)
        except Exception:
            pass

    return battery


def collect(lockdown) -> Battery:
    """Synchronous fallback for scripts and tests."""

    try:
        return _from_mapping(lockdown.get_value(domain="com.apple.mobile.battery"))
    except Exception:
        return Battery()
