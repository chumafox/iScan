"""Component serial collection across lockdown, IORegistry and MobileGestalt."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from iscan.collectors.common import (
    decode_value,
    call_maybe_async,
    first_value,
    flatten_mapping,
    value_by_normalized_key,
)
from iscan.models import Components


def _decode_bytes(value: Any) -> str:
    return decode_value(value) or ""


def _serial(value: Any) -> str | None:
    decoded = decode_value(value)
    if not decoded:
        return None
    # Panel and coverglass values may contain a second firmware blob after '+'.
    return decoded.split("+", 1)[0].strip() or None


def _set_if_missing(component: Components, field: str, values: Mapping[str, Any], keys: tuple[str, ...]) -> None:
    if getattr(component, field) is not None:
        return
    value = value_by_normalized_key(dict(values), keys)
    if value is not None:
        setattr(component, field, _serial(value))


def _populate_from_values(component: Components, values: Mapping[str, Any]) -> None:
    v = dict(values)
    component.mlb_serial = _serial(
        first_value(v, ("MLBSerialNumber", "MainboardSerialNumber", "mlb-serial-number"))
    )
    component.wireless_board_serial = _serial(
        first_value(v, ("WirelessBoardSerialNumber", "WiFiBoardSerialNumber"))
    )
    component.display_serial = _serial(
        first_value(v, ("CoverboardSerialNumber", "DisplaySerialNumber", "RawPanelSerialNumber"))
    )
    component.rear_camera_serial = _serial(
        first_value(v, ("RearFacingCameraModuleSerialNumber", "RearCameraSerialNumber"))
    )
    component.front_camera_serial = _serial(
        first_value(v, ("FrontFacingCameraModuleSerialNumber", "FrontCameraSerialNumber"))
    )
    component.biometric_serial = _serial(
        first_value(v, ("MesaSerialNumber", "BiometricSerialNumber", "RosalineSerialNumber"))
    )
    component.ssd_serial = _serial(first_value(v, ("SSDSerialNumber", "StorageSerialNumber")))
    component.als_serial = _serial(first_value(v, ("ALSSerialNumber", "AmbientLightSensorSerialNumber")))
    component.touch_serial = _serial(
        first_value(v, ("TouchSerialNumber", "CoverglassSerialNumber"))
    )


def _populate_from_ioregistry(component: Components, raw: Any, *, name: str) -> None:
    flattened = flatten_mapping(raw)
    if not flattened:
        return

    _set_if_missing(
        component,
        "display_serial",
        flattened,
        ("raw-panel-serial-number", "coverboard-serial-number", "display-serial-number"),
    )
    _set_if_missing(
        component,
        "touch_serial",
        flattened,
        ("coverglass-serial-number", "touch-serial-number"),
    )
    _set_if_missing(
        component,
        "biometric_serial",
        flattened,
        ("rosaline-serial-num", "mesa-serial-number", "biometric-serial-number"),
    )
    _set_if_missing(
        component,
        "als_serial",
        flattened,
        ("ambient-light-sensor-serial-num", "als-serial-number"),
    )
    _set_if_missing(
        component,
        "mlb_serial",
        flattened,
        ("mlb-serial-number", "mainboard-serial-number"),
    )
    _set_if_missing(
        component,
        "ssd_serial",
        flattened,
        ("serial-number", "ssd-serial-number"),
    )

    camera_keys = {
        "rear": (
            "rear-facing-camera-module-serial-number",
            "rear-camera-serial-number",
            "rear-facing-camera-serial-num",
        ),
        "front": (
            "front-facing-camera-module-serial-number",
            "front-camera-serial-number",
            "front-facing-camera-serial-num",
        ),
    }
    if name in {"product", "camera", "cameras"}:
        _set_if_missing(component, "rear_camera_serial", flattened, camera_keys["rear"])
        _set_if_missing(component, "front_camera_serial", flattened, camera_keys["front"])


def _apply_gestalt(component: Components, values: Mapping[str, Any]) -> None:
    mapping = {
        "mlb_serial": ("MainboardSerialNumber", "MLBSerialNumber"),
        "display_serial": ("CoverboardSerialNumber", "RawPanelSerialNumber"),
        "rear_camera_serial": ("RearFacingCameraModuleSerialNumber",),
        "front_camera_serial": ("FrontFacingCameraModuleSerialNumber",),
        "biometric_serial": ("MesaSerialNumber", "RosalineSerialNumber"),
        "wireless_board_serial": ("WirelessBoardSerialNumber",),
    }
    for field, keys in mapping.items():
        if getattr(component, field) is None:
            setattr(component, field, _serial(first_value(dict(values), keys)))


async def collect_async(lockdown) -> Components:
    component = Components()
    try:
        values = lockdown.all_values
        if isinstance(values, Mapping):
            _populate_from_values(component, values)
    except Exception:
        pass

    try:
        from pymobiledevice3.services.diagnostics import DiagnosticsService

        diagnostics = DiagnosticsService(lockdown)
        # Keep these requests independent: a missing optional IORegistry node
        # must not hide the display or battery data.
        for name in ("product", "AppleANS3CGv2Controller", "device-tree"):
            try:
                raw = await call_maybe_async(diagnostics.ioregistry, name=name)
                _populate_from_ioregistry(component, raw, name=name)
            except Exception:
                continue
    except Exception:
        diagnostics = None

    # MobileGestalt is deprecated on newer iOS, but remains the best fallback
    # for camera/board serials on older devices.
    try:
        if diagnostics is None:
            from pymobiledevice3.services.diagnostics import DiagnosticsService

            diagnostics = DiagnosticsService(lockdown)
        gestalt_keys = [
            "MainboardSerialNumber",
            "MLBSerialNumber",
            "CoverboardSerialNumber",
            "RawPanelSerialNumber",
            "RearFacingCameraModuleSerialNumber",
            "FrontFacingCameraModuleSerialNumber",
            "MesaSerialNumber",
            "WirelessBoardSerialNumber",
        ]
        gestalt = await call_maybe_async(diagnostics.mobilegestalt, gestalt_keys)
        if isinstance(gestalt, Mapping):
            _apply_gestalt(component, gestalt)
    except Exception:
        pass

    return component


def collect(lockdown) -> Components:
    """Synchronous lockdown-only fallback for scripts and tests."""

    component = Components()
    try:
        values = lockdown.all_values
        if isinstance(values, Mapping):
            _populate_from_values(component, values)
    except Exception:
        pass
    return component
