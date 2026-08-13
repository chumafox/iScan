"""Typed, user-facing failures and stable exit codes for the CLI."""

from __future__ import annotations

from enum import IntEnum
from typing import Optional


class ExitCode(IntEnum):
    OK = 0
    DEVICE_NOT_FOUND = 2
    NOT_PAIRED = 3
    TRANSPORT_UNAVAILABLE = 4
    REPORT_FAILED = 5


class IscanError(RuntimeError):
    """Base error with a stable CLI exit code and a safe public message."""

    exit_code: ExitCode = ExitCode.REPORT_FAILED

    def __init__(self, message: str, *, detail: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class DeviceConnectionError(IscanError):
    """A device could not be selected or lockdown could not be opened."""

    def __init__(
        self,
        message: str,
        *,
        code: ExitCode = ExitCode.REPORT_FAILED,
        detail: Optional[str] = None,
    ) -> None:
        super().__init__(message, detail=detail)
        self.exit_code = code


class TransportUnavailableError(IscanError):
    exit_code = ExitCode.TRANSPORT_UNAVAILABLE


def classify_connection_error(exc: BaseException) -> DeviceConnectionError:
    """Map pymobiledevice3's version-specific messages to our stable contract."""

    text = str(exc)
    lowered = text.lower()
    identity = f"{lowered} {exc.__class__.__name__.lower()}"
    if any(
        marker in identity
        for marker in (
            "no device",
            "no devices",
            "nodeviceconnected",
            "not connected",
            "unable to find",
            "device not found",
            "list index out of range",
        )
    ):
        return DeviceConnectionError(
            "No iOS device found.",
            code=ExitCode.DEVICE_NOT_FOUND,
            detail=text,
        )
    if any(
        marker in identity
        for marker in (
            "pair",
            "trust",
            "invalid host id",
            "invalidhostid",
            "not paired",
            "notpaired",
            "pairing dialog",
            "validate_pairing",
        )
    ):
        return DeviceConnectionError(
            "The iOS device is not paired with this Mac.",
            code=ExitCode.NOT_PAIRED,
            detail=text,
        )
    if isinstance(exc, (TimeoutError,)) or any(
        marker in identity
        for marker in (
            "connection refused",
            "cannot connect",
            "connect call failed",
            "no such file",
            "broken pipe",
            "socket",
            "usbmux",
            "connectionfailedtousbmuxd",
            "timed out",
        )
    ):
        return DeviceConnectionError(
            "The usbmuxd transport is unavailable.",
            code=ExitCode.TRANSPORT_UNAVAILABLE,
            detail=text,
        )
    return DeviceConnectionError("Could not connect to the iOS device.", detail=text)


def public_error_detail(error: BaseException) -> str:
    """Return a bounded detail suitable for JSON diagnostics, never a secret."""

    text = str(error).strip().replace("\x00", "")
    return text[:240] or error.__class__.__name__
