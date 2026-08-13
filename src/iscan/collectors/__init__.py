"""Orchestrate fail-soft, time-bounded diagnostic collection."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from time import monotonic
from typing import Any, Awaitable, Callable, Optional

from iscan.collectors import battery, components, device_info, storage
from iscan.collectors.common import decode_value, has_data
from iscan.errors import public_error_detail
from iscan.models import (
    DiagnosticIssue,
    DiagnosticReport,
    Identifiers,
    TransportInfo,
)
from iscan.transport import TransportConfig, display_address

ProgressCallback = Callable[[dict[str, Any]], Any]


def _collect_identifiers(lockdown) -> Identifiers:
    ids = Identifiers()
    try:
        values = lockdown.all_values
        if not isinstance(values, Mapping):
            return ids
        ids.imei = decode_value(values.get("InternationalMobileEquipmentIdentity"))
        ids.imei2 = decode_value(values.get("InternationalMobileEquipmentIdentity2"))
        ecid = values.get("UniqueChipID")
        ids.ecid = str(ecid) if ecid is not None else None
        ids.wifi_mac = decode_value(values.get("WiFiAddress") or values.get("EthernetAddress"))
        ids.bt_mac = decode_value(values.get("BluetoothAddress"))
        ids.meid = decode_value(values.get("MobileEquipmentIdentifier"))
    except Exception:
        pass
    return ids


def _field_count(value: Any) -> int:
    if value is None:
        return 0
    if is_dataclass(value):
        return sum(_field_count(getattr(value, item.name)) for item in fields(value))
    if isinstance(value, dict):
        return sum(_field_count(item) for item in value.values())
    if isinstance(value, (str, bytes)):
        return 1 if value else 0
    return 1


async def _emit(callback: Optional[ProgressCallback], event: dict[str, Any]) -> None:
    if callback is None:
        return
    result = callback(event)
    if inspect.isawaitable(result):
        await result


def _transport_info(value: Optional[TransportConfig | TransportInfo]) -> TransportInfo:
    if isinstance(value, TransportInfo):
        return value
    if isinstance(value, TransportConfig):
        return TransportInfo(
            address=value.address or display_address(value),
            kind=value.kind,
            source=value.source,
            is_remote=value.is_remote,
            networkusb_agent=value.networkusb_agent,
            networkusb_fingerprint=value.networkusb_fingerprint,
            networkusb_version=value.networkusb_version,
        )
    return TransportInfo()


async def _run_collector(
    name: str,
    factory: Callable[[], Awaitable[Any]],
    empty_factory: Callable[[], Any],
    report: DiagnosticReport,
    *,
    timeout: float,
    progress: Optional[ProgressCallback],
) -> Any:
    await _emit(progress, {"event": "service", "name": name, "state": "start"})
    started = monotonic()
    status = "ok"
    error: Optional[str] = None
    try:
        value = await asyncio.wait_for(factory(), timeout=timeout)
        if not has_data(value):
            status = "unavailable"
            error = "collector returned no data"
    except asyncio.TimeoutError:
        value = empty_factory()
        status = "timeout"
        error = f"collector exceeded {timeout:.1f}s timeout"
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        value = empty_factory()
        status = "error"
        error = public_error_detail(exc)

    duration_ms = round((monotonic() - started) * 1000, 1)
    record: dict[str, Any] = {
        "status": status,
        "duration_ms": duration_ms,
        "fields": _field_count(value),
    }
    if error:
        record["error"] = error
        report.issues.append(
            DiagnosticIssue(
                collector=name,
                code="collector_timeout" if status == "timeout" else "collector_unavailable",
                message=error,
            )
        )
    report.collection[name] = record
    await _emit(
        progress,
        {
            "event": "service",
            "name": name,
            "state": "complete",
            "ok": status == "ok",
            "status": status,
            "duration_ms": duration_ms,
        },
    )
    return value


async def collect_all(
    lockdown,
    *,
    timeout: float = 8.0,
    transport: Optional[TransportConfig | TransportInfo] = None,
    progress: Optional[ProgressCallback] = None,
) -> DiagnosticReport:
    """Collect all report sections concurrently, independently and fail-soft.

    NetworkUSB is a byte tunnel: a slow service must not make the entire CLI
    wait forever.  Every optional service therefore has its own timeout and a
    missing battery/IORegistry response still produces a useful device report.
    """

    if timeout <= 0:
        raise ValueError("collector timeout must be positive")
    report = DiagnosticReport(transport=_transport_info(transport))
    await _emit(progress, {"event": "collect", "state": "start"})

    started = monotonic()
    try:
        report.identifiers = _collect_identifiers(lockdown)
    except Exception as exc:
        report.identifiers = Identifiers()
        report.issues.append(
            DiagnosticIssue(
                collector="identifiers",
                code="collector_unavailable",
                message=public_error_detail(exc),
            )
        )
    report.collection["identifiers"] = {
        "status": "ok" if has_data(report.identifiers) else "unavailable",
        "duration_ms": round((monotonic() - started) * 1000, 1),
        "fields": _field_count(report.identifiers),
    }

    from iscan.models import Battery, Components, DeviceInfo, Storage

    jobs = (
        ("device_info", lambda: device_info.collect_async(lockdown), DeviceInfo),
        ("battery", lambda: battery.collect_async(lockdown), Battery),
        ("storage", lambda: storage.collect_async(lockdown), Storage),
        ("components", lambda: components._collect_async(lockdown), Components),
    )

    lockdown_lock = asyncio.Lock()

    async def _locked_factory(factory_fn):
        async with lockdown_lock:
            return await factory_fn()

    tasks = [
        asyncio.create_task(
            _run_collector(
                name,
                lambda fn=factory: _locked_factory(fn),
                empty_factory,
                report,
                timeout=timeout,
                progress=progress,
            ),
            name=f"iscan-collector-{name}",
        )
        for name, factory, empty_factory in jobs
    ]
    values = await asyncio.gather(*tasks)
    report.device, report.battery, report.storage, report.components = values

    await _emit(
        progress,
        {
            "event": "collect",
            "state": "complete",
            "ok": not any(issue.severity == "error" for issue in report.issues),
            "partial": report.is_partial,
        },
    )
    return report


__all__ = ["collect_all"]
