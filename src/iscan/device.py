"""Device and usbmuxd connection lifecycle."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Optional

from iscan.errors import DeviceConnectionError, classify_connection_error
from iscan.transport import TransportConfig, normalize_usbmux_address, resolve_transport


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _kwargs_for_transport(config: TransportConfig, **kwargs: Any) -> dict[str, Any]:
    result = dict(kwargs)
    if config.address is not None:
        result["usbmux_address"] = config.address
    return result


def _supported_kwargs(function: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Avoid breaking small fake/older pymobiledevice3 factories."""

    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return kwargs
    if any(parameter.kind == parameter.VAR_KEYWORD for parameter in signature.parameters.values()):
        return kwargs
    return {key: value for key, value in kwargs.items() if key in signature.parameters}


async def connect_async(
    udid: Optional[str] = None,
    *,
    transport: Optional[TransportConfig] = None,
    usbmux_address: Optional[str] = None,
    timeout: float = 15.0,
    autopair: bool = True,
    pair_timeout: Optional[float] = None,
):
    """Connect to an iOS device via the selected local or NetworkUSB socket."""

    if timeout <= 0:
        raise ValueError("connection timeout must be positive")
    config = transport or resolve_transport(usbmux_address)
    try:
        from pymobiledevice3.lockdown import create_using_usbmux

        kwargs = _supported_kwargs(
            create_using_usbmux,
            _kwargs_for_transport(
                config,
                serial=udid,
                autopair=autopair,
                pair_timeout=pair_timeout,
            ),
        )

        async def invoke(current_kwargs: dict[str, Any]) -> Any:
            # pymobiledevice3 4.x exposes a synchronous API; newer releases
            # are async.  Keep either one off the event loop when necessary.
            if inspect.iscoroutinefunction(create_using_usbmux):
                return await create_using_usbmux(**current_kwargs)
            return await asyncio.to_thread(create_using_usbmux, **current_kwargs)

        try:
            return await asyncio.wait_for(invoke(kwargs), timeout=timeout)
        except TypeError as exc:
            # Keep compatibility with older pymobiledevice3 versions that did
            # not expose usbmux_address on the lockdown helper.  We only fall
            # back when the unsupported keyword is the actual cause.
            if "usbmux_address" not in str(exc) or "usbmux_address" not in kwargs:
                raise
            kwargs.pop("usbmux_address", None)
            return await asyncio.wait_for(invoke(kwargs), timeout=timeout)
    except asyncio.CancelledError:
        raise
    except DeviceConnectionError:
        raise
    except Exception as exc:
        raise classify_connection_error(exc) from exc


def connect(
    udid: Optional[str] = None,
    *,
    usbmux_address: Optional[str] = None,
    timeout: float = 15.0,
    autopair: bool = True,
):
    """Synchronous wrapper for scripts; the CLI uses :func:`connect_async`."""

    return asyncio.run(
        connect_async(
            udid,
            usbmux_address=usbmux_address,
            timeout=timeout,
            autopair=autopair,
        )
    )


async def close_async(lockdown: Any) -> None:
    """Close a pymobiledevice3 client when the installed version supports it."""

    if lockdown is None:
        return
    for name in ("close", "shutdown"):
        close = getattr(lockdown, name, None)
        if close is None:
            continue
        try:
            if inspect.iscoroutinefunction(close):
                await close()
            else:
                result = await asyncio.to_thread(close)
                await _maybe_await(result)
        except Exception:
            pass
        return


async def _list_devices_raw(config: TransportConfig):
    from pymobiledevice3 import usbmux

    kwargs = {"usbmux_address": config.address} if config.address is not None else {}
    kwargs = _supported_kwargs(usbmux.list_devices, kwargs)

    async def invoke(current_kwargs: dict[str, Any]) -> Any:
        if inspect.iscoroutinefunction(usbmux.list_devices):
            return await usbmux.list_devices(**current_kwargs)
        return await asyncio.to_thread(usbmux.list_devices, **current_kwargs)

    try:
        return await invoke(kwargs)
    except TypeError as exc:
        if "usbmux_address" not in str(exc) or not kwargs:
            raise
        return await invoke({})


async def list_devices_async(
    *,
    transport: Optional[TransportConfig] = None,
    usbmux_address: Optional[str] = None,
    timeout: float = 5.0,
) -> list[dict[str, str]]:
    """List every device visible through the endpoint, including remote ones.

    The old implementation filtered for ``USB``.  That is not a safe
    assumption after NetworkUSB or Wi-Fi pairing: the mux may report a
    different connection type even though it is the correct endpoint.
    """

    config = transport or resolve_transport(usbmux_address)
    try:
        devices = await asyncio.wait_for(_list_devices_raw(config), timeout=timeout)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        raise classify_connection_error(exc) from exc

    result: list[dict[str, str]] = []
    for device in devices or []:
        serial = str(getattr(device, "serial", "") or "")
        if not serial:
            continue
        item = {
            "udid": serial,
            "model": "Unknown",
            "name": "",
            "ios": "",
            "connection_type": str(getattr(device, "connection_type", "") or "Unknown"),
        }
        try:
            lockdown = await connect_async(
                serial,
                transport=config,
                timeout=min(timeout, 5.0),
                autopair=False,
            )
            try:
                values = getattr(lockdown, "all_values", {})
                if isinstance(values, dict):
                    item["model"] = str(values.get("ProductType") or "Unknown")
                    item["name"] = str(values.get("DeviceName") or "")
                    item["ios"] = str(values.get("ProductVersion") or "")
            finally:
                await close_async(lockdown)
        except DeviceConnectionError:
            # Listing should remain useful when a single device is locked or
            # unpaired; the UDID and mux connection type are still valid.
            pass
        except Exception:
            pass
        result.append(item)
    return result


def normalize_address(value: Optional[str]) -> Optional[str]:
    """Public compatibility alias used by small integrations."""

    return normalize_usbmux_address(value)
