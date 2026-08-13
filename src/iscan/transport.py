"""Transport discovery and compatibility helpers for usbmuxd.

NetworkUSB exposes a remote usbmuxd as a local UNIX socket.  The two projects
must agree on one small but important detail: ``pymobiledevice3`` expects a
bare UNIX path (``/tmp/usbmuxd.sock``), while some libusbmuxd documentation
uses ``unix:/tmp/usbmuxd.sock``.  This module accepts both spellings and keeps
that compatibility concern out of the collectors and CLI commands.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Optional


USBMUX_ENV_VARS = ("USBMUXD_SOCKET_ADDRESS", "PYMOBILEDEVICE3_USBMUX")
ACTIVE_METADATA_ENV = "NETWORKUSB_ACTIVE_FILE"
DEFAULT_ACTIVE_METADATA = Path.home() / ".cache" / "networkusb" / "active.json"


class TransportAddressError(ValueError):
    """Raised when a usbmuxd address cannot be interpreted safely."""


@dataclass(frozen=True)
class TransportConfig:
    """Resolved usbmuxd transport plus optional NetworkUSB provenance.

    ``address=None`` intentionally means "let pymobiledevice3 use the native
    platform socket".  It is different from an invalid or missing socket and
    is therefore preserved rather than replaced with a guessed path.
    """

    address: Optional[str] = None
    source: str = "system"
    kind: str = "system"
    metadata_path: Optional[str] = None
    networkusb_agent: Optional[str] = None
    networkusb_fingerprint: Optional[str] = None
    networkusb_version: Optional[str] = None

    @property
    def is_remote(self) -> bool:
        return bool(self.networkusb_agent or self.kind == "tcp")

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["is_remote"] = self.is_remote
        return data


@dataclass(frozen=True)
class TransportProbe:
    """Result of checking whether a resolved usbmuxd endpoint is reachable."""

    ok: bool
    address: Optional[str]
    kind: str
    detail: str
    latency_ms: Optional[float] = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _strip_unix_prefix(value: str) -> str:
    lowered = value.lower()
    if lowered.startswith("unix://"):
        # ``unix:///tmp/socket`` -> ``/tmp/socket``.
        return value[7:]
    if lowered.startswith("unix:"):
        return value[5:]
    if lowered.startswith("file://"):
        return value[7:]
    return value


def normalize_usbmux_address(value: Optional[str]) -> Optional[str]:
    """Normalize the address dialects seen in libusbmuxd/NetworkUSB docs.

    Accepted values:

    * ``/path/to/usbmuxd.sock`` (canonical UNIX form)
    * ``unix:/path`` and ``unix:///path``
    * ``host:port`` (pymobiledevice3 TCP form)
    * ``tcp:host:port`` and ``tcp://host:port``

    The returned value is deliberately still a string because that is the
    public API accepted by pymobiledevice3.  IPv6 is accepted in bracketed
    form and left untouched; older pymobiledevice3 releases may not support it
    and will report a useful connection error instead of silently using the
    wrong transport.
    """

    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None

    value = _strip_unix_prefix(value)
    lowered = value.lower()
    if lowered.startswith("tcp://"):
        value = value[6:]
    elif lowered.startswith("tcp:"):
        value = value[4:]
    value = value.strip()
    if not value:
        raise TransportAddressError("usbmuxd address is empty")

    # A UNIX path must be absolute after normalization.  Relative paths are
    # ambiguous when a LaunchAgent and a shell have different working dirs.
    if "/" in value and ":" not in value and not value.startswith("/"):
        value = str(Path(value).expanduser().resolve())
    if value.startswith("~"):
        value = str(Path(value).expanduser())

    if value.startswith("["):
        closing = value.find("]")
        if closing < 0 or closing + 1 >= len(value) or value[closing + 1] != ":":
            raise TransportAddressError("IPv6 usbmuxd address must look like [host]:port")
        port = value[closing + 2 :]
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            raise TransportAddressError("TCP usbmuxd port must be between 1 and 65535")
        return value

    if ":" in value and not value.startswith("/"):
        host, separator, port = value.rpartition(":")
        if not separator or not host or not port.isdigit():
            raise TransportAddressError(
                "TCP usbmuxd address must look like host:port; use unix:/path for a socket"
            )
        if not 1 <= int(port) <= 65535:
            raise TransportAddressError("TCP usbmuxd port must be between 1 and 65535")
        return f"{host}:{int(port)}"

    if not value.startswith("/"):
        raise TransportAddressError(
            "UNIX usbmuxd address must be an absolute path (or use host:port for TCP)"
        )
    return value


def address_kind(address: Optional[str]) -> str:
    """Return ``system``, ``unix`` or ``tcp`` for a normalized address."""

    if address is None:
        return "system"
    if address.startswith("["):
        return "tcp"
    if address.startswith("/"):
        return "unix"
    return "tcp" if ":" in address else "unix"


def _metadata_path(path: Optional[Path | str] = None) -> Path:
    if path is not None:
        return Path(path).expanduser()
    configured = os.getenv(ACTIVE_METADATA_ENV)
    return Path(configured).expanduser() if configured else DEFAULT_ACTIVE_METADATA


def _read_active_metadata(path: Path) -> Optional[dict[str, Any]]:
    """Read NetworkUSB's optional active endpoint file without trusting it.

    The file is only a discovery hint.  It never contains credentials and is
    used only when the endpoint itself is reachable.  Invalid or stale JSON is
    treated as absent so a broken status file cannot prevent local USB use.
    """

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(raw, dict):
        return None

    pid = raw.get("pid")
    if pid is not None:
        try:
            os.kill(int(pid), 0)
        except (OSError, TypeError, ValueError):
            return None

    candidate = (
        raw.get("address")
        or raw.get("socket")
        or raw.get("socket_path")
        or raw.get("usbmuxd_socket")
    )
    if not candidate:
        return None
    try:
        address = normalize_usbmux_address(str(candidate))
    except TransportAddressError:
        return None
    if address and address_kind(address) == "unix":
        try:
            if not stat.S_ISSOCK(os.stat(address).st_mode):
                return None
        except OSError:
            return None
    raw["address"] = address
    return raw


def resolve_transport(
    address: Optional[str] = None,
    *,
    environ: Optional[Mapping[str, str]] = None,
    active_file: Optional[Path | str] = None,
) -> TransportConfig:
    """Resolve a CLI address, environment, NetworkUSB metadata, or system.

    Explicit CLI input always wins.  For compatibility with both releases of
    NetworkUSB, ``USBMUXD_SOCKET_ADDRESS`` is preferred and
    ``PYMOBILEDEVICE3_USBMUX`` is accepted as a fallback.  Automatic metadata
    discovery is intentionally last so a stale bridge cannot override a
    user's local environment.
    """

    env = os.environ if environ is None else environ
    if address is not None:
        normalized = normalize_usbmux_address(address)
        return TransportConfig(
            address=normalized,
            source="cli",
            kind=address_kind(normalized),
        )

    for name in USBMUX_ENV_VARS:
        value = env.get(name)
        if value:
            normalized = normalize_usbmux_address(value)
            return TransportConfig(
                address=normalized,
                source=f"env:{name}",
                kind=address_kind(normalized),
            )

    metadata_path = _metadata_path(active_file)
    metadata = _read_active_metadata(metadata_path)
    if metadata:
        normalized = metadata.get("address")
        return TransportConfig(
            address=normalized,
            source="networkusb-active",
            kind=address_kind(normalized),
            metadata_path=str(metadata_path),
            networkusb_agent=_agent_label(metadata),
            networkusb_fingerprint=_optional_text(
                metadata.get("fingerprint") or metadata.get("tls_fingerprint")
            ),
            networkusb_version=_optional_text(
                metadata.get("networkusb_version") or metadata.get("version")
            ),
        )

    return TransportConfig()


def _optional_text(value: Any) -> Optional[str]:
    return str(value).strip() if value is not None and str(value).strip() else None


def _agent_label(metadata: Mapping[str, Any]) -> Optional[str]:
    host = _optional_text(metadata.get("agent_host") or metadata.get("host"))
    port = metadata.get("agent_port") or metadata.get("port")
    if host and port:
        return f"{host}:{port}"
    return host


def apply_environment(config: TransportConfig) -> None:
    """Expose the resolved address to both supported pymobiledevice3 env vars."""

    if config.address:
        os.environ["USBMUXD_SOCKET_ADDRESS"] = config.address
        # Some older/newer CLI paths use this name.  Setting both makes the
        # subprocess contract with NetworkUSB deterministic as well.
        os.environ["PYMOBILEDEVICE3_USBMUX"] = config.address


def _system_address() -> Optional[str]:
    try:
        from pymobiledevice3.osu.os_utils import get_os_utils

        address, family = get_os_utils().usbmux_address
        if family == socket.AF_UNIX:
            return str(address)
    except Exception:
        pass
    return None


def display_address(config: TransportConfig) -> str:
    if config.address:
        return config.address
    return _system_address() or "system default usbmuxd"


def describe_transport(config: TransportConfig) -> dict[str, Any]:
    """Return a JSON-safe, non-secret transport description."""

    data = config.as_dict()
    data["display_address"] = display_address(config)
    if config.kind == "unix" or (config.kind == "system" and _system_address()):
        path = config.address or _system_address()
        if path:
            try:
                mode = os.stat(path).st_mode
                data.update(
                    {
                        "path_exists": True,
                        "is_socket": stat.S_ISSOCK(mode),
                        "mode": oct(stat.S_IMODE(mode)),
                    }
                )
            except OSError:
                data.update({"path_exists": False, "is_socket": False})
    return data


async def probe_transport(
    config: TransportConfig, *, timeout: float = 3.0
) -> TransportProbe:
    """Open and close the endpoint, proving that the bridge is reachable."""

    address = config.address or _system_address()
    kind = address_kind(address)
    if not address:
        return TransportProbe(False, None, kind, "system usbmuxd path is unavailable")

    started = asyncio.get_running_loop().time()
    try:
        if kind == "unix":
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(address), timeout=timeout
            )
        else:
            host, port = _split_tcp(address)
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=timeout
            )
        del reader
        writer.close()
        close = getattr(writer, "wait_closed", None)
        if close is not None:
            await asyncio.wait_for(close(), timeout=timeout)
    except asyncio.TimeoutError:
        return TransportProbe(False, address, kind, "connection timed out")
    except (OSError, ValueError) as exc:
        return TransportProbe(False, address, kind, _safe_error_detail(exc))

    elapsed = (asyncio.get_running_loop().time() - started) * 1000
    return TransportProbe(True, address, kind, "endpoint accepted a connection", round(elapsed, 1))


def _split_tcp(address: str) -> tuple[str, int]:
    if address.startswith("["):
        host, _, port = address[1:].partition("]:")
    else:
        host, _, port = address.rpartition(":")
    if not host or not port.isdigit():
        raise TransportAddressError("invalid TCP usbmuxd address")
    return host, int(port)


def _safe_error_detail(exc: BaseException) -> str:
    text = str(exc).strip()
    return text[:240] or exc.__class__.__name__


def endpoint_is_socket(address: Optional[str]) -> bool:
    """Small synchronous helper used by tests and diagnostics."""

    if not address:
        address = _system_address()
    if not address or address_kind(address) != "unix":
        return False
    try:
        return stat.S_ISSOCK(os.stat(address).st_mode)
    except OSError:
        return False
