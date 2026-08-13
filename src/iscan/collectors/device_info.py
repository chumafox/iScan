"""Collect general lockdown/device information."""

from __future__ import annotations

from typing import Any, Mapping

from iscan.catalog import commercial_name
from iscan.collectors.common import call_maybe_async, decode_value, first_value
from iscan.models import DeviceInfo

COLOR_NAMES = {
    1: "Black",
    2: "White",
    3: "Blue",
    4: "Green",
    5: "Red",
    6: "Purple",
    7: "Gold",
    8: "Silver",
    9: "Space Gray",
    10: "Rose Gold",
    11: "Midnight",
    12: "Starlight",
    13: "Sierra Blue",
    14: "Alpine Green",
    15: "Deep Purple",
    16: "Space Black",
    17: "Natural Titanium",
    18: "Blue Titanium",
    19: "White Titanium",
    20: "Black Titanium",
}


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _decode_bytes(value: Any) -> str:
    """Backward-compatible helper retained for integrations importing it."""

    return decode_value(value) or ""


def _sim_status(values: Mapping[str, Any], activation: str | None) -> str | None:
    # kCTPostponementStatus is the closest carrier-lock signal exposed by
    # lockdown.  SIMStatus itself means that a SIM is present, not that the
    # phone is carrier-unlocked, so it is only used as a conservative fallback.
    postponement = decode_value(values.get("kCTPostponementStatus"))
    if postponement == "kCTPostponementStatusActivated" and activation == "Activated":
        return "no_restrictions"
    if postponement == "kCTPostponementStatusDelay":
        return "locked"

    lock_value = first_value(
        dict(values),
        ("SIMLockStatus", "CarrierLockStatus", "SIMLock", "CarrierLock"),
    )
    lock_text = (decode_value(lock_value) or "").lower()
    if any(token in lock_text for token in ("unlocked", "no_restrictions", "no restrictions")):
        return "no_restrictions"
    if "lock" in lock_text:
        return "locked"
    if activation != "Activated":
        return "unknown"
    return "unknown"


def _populate_from_values(info: DeviceInfo, values: Mapping[str, Any]) -> None:
    v = dict(values)
    info.product_type = decode_value(v.get("ProductType"))
    info.product_version = decode_value(v.get("ProductVersion"))
    info.build_version = decode_value(v.get("BuildVersion"))
    info.device_name = decode_value(v.get("DeviceName"))
    info.serial_number = decode_value(v.get("SerialNumber"))
    info.udid = decode_value(v.get("UniqueDeviceID"))
    info.activation_state = decode_value(v.get("ActivationState"))
    info.baseband_version = decode_value(v.get("BasebandVersion"))
    info.commercial_name = commercial_name(info.product_type)

    color = v.get("DeviceColor")
    if color is not None:
        try:
            info.device_color = COLOR_NAMES.get(int(color), decode_value(color))
        except (TypeError, ValueError):
            info.device_color = decode_value(color)

    model_num = decode_value(v.get("ModelNumber"))
    region_info = decode_value(v.get("RegionInfo"))
    if model_num and region_info and not model_num.endswith(region_info):
        info.sales_model = f"{model_num}{region_info}"
    else:
        info.sales_model = model_num

    info.sim_status = _sim_status(v, info.activation_state)

    # Some iOS versions expose FMI in lockdown rather than IORegistry.
    fmi = first_value(
        v,
        ("FMiPAccount", "FindMyiPhone", "FindMyDevice", "ActivationLock"),
    )
    if fmi is not None:
        text = (decode_value(fmi) or "").lower()
        if text in {"yes", "true", "1", "enabled", "locked"}:
            info.fmi_status = "enabled"
        elif text in {"no", "false", "0", "disabled", "unlocked"}:
            info.fmi_status = "disabled"


def _apply_options(info: DeviceInfo, options: Mapping[str, Any]) -> None:
    fmi = first_value(dict(options), ("fm-activation-locked", "activation-locked"))
    if fmi is not None:
        text = (decode_value(fmi) or "").lower()
        info.fmi_status = "enabled" if text in {"yes", "true", "1"} else "disabled"
    apple_id = first_value(dict(options), ("fm-account-masked", "fm-account"))
    if apple_id is not None:
        info.apple_id = decode_value(apple_id)


async def collect_async(lockdown) -> DeviceInfo:
    info = DeviceInfo()
    try:
        _populate_from_values(info, _as_mapping(lockdown.all_values))
    except Exception:
        # A lockdown object can expose all_values lazily; the optional registry
        # queries below may still provide useful data.
        pass

    try:
        from pymobiledevice3.services.diagnostics import DiagnosticsService

        diag = DiagnosticsService(lockdown)
        options = await call_maybe_async(diag.ioregistry, name="options")
        if isinstance(options, Mapping):
            _apply_options(info, options)
    except Exception:
        pass

    try:
        from pymobiledevice3.services.diagnostics import DiagnosticsService

        diag = DiagnosticsService(lockdown)
        device_tree = await call_maybe_async(diag.ioregistry, name="device-tree")
        if isinstance(device_tree, Mapping):
            regulatory = first_value(
                dict(device_tree),
                ("regulatory-model-number", "RegulatoryModelNumber"),
            )
            if regulatory is not None:
                info.regulatory_model = decode_value(regulatory)
    except Exception:
        pass

    # A few releases put the regulatory number in lockdown, so prefer that
    # value when the IORegistry query was unavailable.
    if info.regulatory_model is None:
        try:
            values = _as_mapping(lockdown.all_values)
            info.regulatory_model = decode_value(
                first_value(values, ("RegulatoryModelNumber", "RegulatoryModel"))
            )
        except Exception:
            pass
    return info


def collect(lockdown) -> DeviceInfo:
    """Synchronous collector used by lightweight scripts and fixture tests."""

    info = DeviceInfo()
    try:
        _populate_from_values(info, _as_mapping(lockdown.all_values))
    except Exception:
        pass
    return info
