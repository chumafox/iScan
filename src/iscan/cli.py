"""Command-line interface for iScan and its NetworkUSB transport."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import webbrowser
from dataclasses import asdict, is_dataclass
from pathlib import Path
from time import monotonic
from typing import Any, Optional

import typer
from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from iscan.errors import (
    DeviceConnectionError,
    ExitCode,
    IscanError,
    TransportUnavailableError,
    public_error_detail,
)
from iscan.transport import (
    TransportAddressError,
    TransportConfig,
    describe_transport,
    display_address,
    probe_transport,
    resolve_transport,
)

app = typer.Typer(
    name="iscan",
    help="iOS device diagnostics CLI — generates detailed HTML reports",
    add_completion=False,
)
console = Console()


class Progress:
    """Human output and JSON-lines output share one event contract."""

    def __init__(self, json_mode: bool = False) -> None:
        self.json_mode = json_mode

    def emit(self, event: dict[str, Any]) -> None:
        if self.json_mode:
            print(json.dumps(event, ensure_ascii=False, separators=(",", ":")), flush=True)
            return
        if event.get("event") == "connected":
            console.print("[green]✓[/] Connected:", Text(str(event.get("name", "Unknown"))))
        elif event.get("event") == "service" and event.get("state") == "complete":
            mark = "✓" if event.get("ok") else "!"
            console.print(f"[{('green' if event.get('ok') else 'yellow')}]{mark}[/] {event.get('name')}")

    def info(self, message: str) -> None:
        if not self.json_mode:
            console.print(message)

    def error(self, message: str, *, code: ExitCode, detail: Optional[str] = None) -> None:
        if self.json_mode:
            payload: dict[str, Any] = {"event": "error", "code": code.name.lower(), "message": message}
            if detail:
                payload["detail"] = detail
            self.emit(payload)
        else:
            console.print("[bold red]Error:[/]", Text(message))
            if detail:
                console.print(Text(detail, style="dim"))


def _transport_option_help() -> str:
    return (
        "usbmuxd address: bare UNIX path (/tmp/usbmuxd.sock), unix:/path, "
        "or host:port; otherwise env/NetworkUSB active metadata is used"
    )


def _resolve_cli_transport(address: Optional[str]) -> TransportConfig:
    try:
        return resolve_transport(address)
    except TransportAddressError as exc:
        raise TransportUnavailableError(
            f"Invalid usbmuxd address: {exc}", detail=str(exc)
        ) from exc


def _safe_filename(value: Optional[str]) -> str:
    value = value or "unknown"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return safe[:120] or "unknown"


def _write_text_atomic(path: Path, content: str) -> None:
    """Write a complete report before replacing the destination."""

    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _report_payload(report: Any) -> dict[str, Any]:
    return asdict(report) if is_dataclass(report) else dict(report)


def _exit_from_error(error: BaseException, default: ExitCode = ExitCode.REPORT_FAILED) -> ExitCode:
    code = getattr(error, "exit_code", default)
    try:
        return ExitCode(int(code))
    except (TypeError, ValueError):
        return default


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version_flag: Optional[bool] = typer.Option(
        None,
        "--version",
        "-V",
        help="Show iScan version and exit",
        is_eager=True,
    ),
) -> None:
    if version_flag:
        from iscan import __version__

        console.print(f"iScan v{__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@app.command()
def report(
    lang: str = typer.Option("auto", "--lang", "-l", help="Report language: en, ru, auto"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output HTML path"),
    udid: Optional[str] = typer.Option(None, "--udid", help="Device UDID"),
    open_browser: bool = typer.Option(False, "--open", help="Open report in browser"),
    usbmux_address: Optional[str] = typer.Option(
        None,
        "--usbmux-address",
        "--socket-path",
        help=_transport_option_help(),
    ),
    timeout: float = typer.Option(8.0, "--timeout", min=0.5, help="Seconds per diagnostic service"),
    pair_timeout: Optional[float] = typer.Option(
        None, "--pair-timeout", min=1.0, help="Seconds to wait for Trust/pairing"
    ),
    json_progress: bool = typer.Option(
        False, "--json-progress", help="Emit one machine-readable JSON event per line"
    ),
):
    """Collect diagnostics and generate an HTML report."""

    asyncio.run(
        _report_async(
            lang,
            output,
            udid,
            open_browser,
            usbmux_address=usbmux_address,
            timeout=timeout,
            pair_timeout=pair_timeout,
            json_progress=json_progress,
        )
    )


async def _report_async(
    lang: str,
    output: Optional[Path],
    udid: Optional[str],
    open_browser: bool,
    *,
    usbmux_address: Optional[str] = None,
    timeout: float = 8.0,
    pair_timeout: Optional[float] = None,
    json_progress: bool = False,
) -> Optional[Path]:
    from datetime import datetime, timezone

    from iscan import __version__, device as dev
    from iscan.collectors import collect_all
    from iscan.report.i18n import detect_lang
    from iscan.report.render import render_html
    from iscan.transport import apply_environment

    progress = Progress(json_progress)
    try:
        config = _resolve_cli_transport(usbmux_address)
    except IscanError as exc:
        code = _exit_from_error(exc, ExitCode.TRANSPORT_UNAVAILABLE)
        progress.error(exc.message, code=code, detail=exc.detail)
        raise typer.Exit(int(code))

    apply_environment(config)
    progress.emit(
        {
            "event": "start",
            "command": "report",
            "transport": describe_transport(config),
            "udid": udid,
        }
    )
    if lang == "auto":
        lang = detect_lang()
    if lang not in {"en", "ru"}:
        progress.error(f"Unsupported language: {lang}", code=ExitCode.REPORT_FAILED)
        raise typer.Exit(int(ExitCode.REPORT_FAILED))

    lockdown = None
    try:
        progress.info(f"[bold cyan]Connecting via {display_address(config)}…[/]")
        lockdown = await dev.connect_async(
            udid,
            transport=config,
            timeout=max(timeout, 10.0),
            pair_timeout=pair_timeout,
        )
        values = getattr(lockdown, "all_values", {})
        device_name = values.get("DeviceName", "Unknown") if isinstance(values, dict) else "Unknown"
        progress.emit({"event": "connected", "name": device_name})

        diagnostic = await collect_all(
            lockdown,
            timeout=timeout,
            transport=config,
            progress=progress.emit,
        )
        diagnostic.iscan_version = __version__
    except (DeviceConnectionError, IscanError) as exc:
        code = _exit_from_error(exc)
        progress.error(getattr(exc, "message", str(exc)), code=code, detail=getattr(exc, "detail", None))
        raise typer.Exit(int(code))
    except Exception as exc:
        code = ExitCode.REPORT_FAILED
        progress.error("Diagnostic collection failed.", code=code, detail=public_error_detail(exc))
        raise typer.Exit(int(code))
    finally:
        if lockdown is not None:
            await dev.close_async(lockdown)

    if output is None:
        serial = _safe_filename(diagnostic.device.serial_number)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output = Path(f"iscan_report_{serial}_{timestamp}.html")
    else:
        output = output.expanduser()

    try:
        html = render_html(diagnostic, lang)
        _write_text_atomic(output, html)
    except Exception as exc:
        code = ExitCode.REPORT_FAILED
        progress.error("Could not write the HTML report.", code=code, detail=public_error_detail(exc))
        raise typer.Exit(int(code))

    absolute = output.resolve()
    progress.emit({"event": "saved", "path": str(absolute), "partial": diagnostic.is_partial})
    if not json_progress:
        console.print(f"[bold green]✓[/] Report saved: [cyan]{absolute}[/]")
    if open_browser:
        webbrowser.open(absolute.as_uri())
    return absolute


@app.command()
def info(
    udid: Optional[str] = typer.Option(None, "--udid", help="Device UDID"),
    usbmux_address: Optional[str] = typer.Option(None, "--usbmux-address", "--socket-path", help=_transport_option_help()),
    timeout: float = typer.Option(8.0, "--timeout", min=0.5),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
):
    """Show key device info in the terminal (without HTML)."""

    asyncio.run(_info_async(udid, usbmux_address=usbmux_address, timeout=timeout, json_output=json_output))


async def _info_async(
    udid: Optional[str],
    *,
    usbmux_address: Optional[str] = None,
    timeout: float = 8.0,
    json_output: bool = False,
) -> None:
    from iscan import device as dev
    from iscan.collectors import collect_all

    try:
        config = _resolve_cli_transport(usbmux_address)
        lockdown = await dev.connect_async(udid, transport=config, timeout=max(timeout, 10.0))
    except (DeviceConnectionError, IscanError) as exc:
        code = _exit_from_error(exc)
        Progress(json_output).error(getattr(exc, "message", str(exc)), code=code, detail=getattr(exc, "detail", None))
        raise typer.Exit(int(code))

    try:
        d = await collect_all(lockdown, timeout=timeout, transport=config)
    finally:
        await dev.close_async(lockdown)

    if json_output:
        print(json.dumps(_report_payload(d), ensure_ascii=False, default=_json_default))
        return

    def value(value: Any) -> Text:
        return Text(str(value) if value is not None else "N/A", style="white" if value is not None else "dim")

    table = Table(title="Device Info", box=box.ROUNDED, show_header=True)
    table.add_column("Field", style="cyan", min_width=25)
    table.add_column("Value")
    rows = [
        ("Device Name", d.device.device_name),
        ("Model (Commercial)", d.device.commercial_name),
        ("Model (Sales)", d.device.sales_model),
        ("Model (Regulatory)", d.device.regulatory_model),
        ("Device Color", d.device.device_color),
        ("Device Type", d.device.product_type),
        ("iOS Version", d.device.product_version),
        ("Serial Number", d.device.serial_number),
        ("UDID", d.device.udid),
        ("IMEI", d.identifiers.imei),
        ("ECID", d.identifiers.ecid),
        ("Wi-Fi MAC", d.identifiers.wifi_mac),
        ("Bluetooth MAC", d.identifiers.bt_mac),
        ("SIM Lock", d.device.sim_status),
        ("iCloud Lock", d.device.fmi_status),
        ("Activation State", d.device.activation_state),
        ("Battery Health", f"{d.battery.health_percent:.0f}%" if d.battery.health_percent is not None else None),
        ("Battery Cycles", d.battery.cycle_count),
        ("Storage Used", _storage_summary(d)),
        ("Transport", display_address(config)),
    ]
    for label, item in rows:
        table.add_row(label, value(item))
    console.print(table)


def _storage_summary(report: Any) -> Optional[str]:
    if report.storage.used is None or report.storage.total_capacity is None:
        return None
    used = report.storage.used / 1024**3
    total = report.storage.total_capacity / 1024**3
    percent = report.storage.used_percent
    return f"{used:.1f} / {total:.1f} GiB ({percent}%)" if percent is not None else f"{used:.1f} / {total:.1f} GiB"


@app.command(name="list")
def list_devices(
    usbmux_address: Optional[str] = typer.Option(None, "--usbmux-address", "--socket-path", help=_transport_option_help()),
    timeout: float = typer.Option(5.0, "--timeout", min=0.5),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
):
    """List every device visible through the selected usbmuxd endpoint."""

    asyncio.run(_list_async(usbmux_address=usbmux_address, timeout=timeout, json_output=json_output))


async def _list_async(
    *, usbmux_address: Optional[str] = None, timeout: float = 5.0, json_output: bool = False
) -> None:
    from iscan import device as dev

    try:
        config = _resolve_cli_transport(usbmux_address)
        devices = await dev.list_devices_async(transport=config, timeout=timeout)
    except (DeviceConnectionError, IscanError) as exc:
        code = _exit_from_error(exc)
        Progress(json_output).error(getattr(exc, "message", str(exc)), code=code, detail=getattr(exc, "detail", None))
        raise typer.Exit(int(code))

    if json_output:
        print(json.dumps({"transport": describe_transport(config), "devices": devices}, ensure_ascii=False))
        return
    if not devices:
        console.print("[yellow]No devices found.[/] Connect an iOS device and tap Trust.")
        return

    table = Table(title="Connected Devices", box=box.ROUNDED)
    table.add_column("UDID", style="dim", min_width=36)
    table.add_column("Name")
    table.add_column("Model", style="cyan")
    table.add_column("iOS", style="green")
    table.add_column("Connection", style="magenta")
    for item in devices:
        table.add_row(
            item["udid"], item["name"], item["model"], item["ios"], item["connection_type"]
        )
    console.print(table)


@app.command()
def doctor(
    udid: Optional[str] = typer.Option(None, "--udid", help="Check a specific device"),
    usbmux_address: Optional[str] = typer.Option(None, "--usbmux-address", "--socket-path", help=_transport_option_help()),
    timeout: float = typer.Option(5.0, "--timeout", min=0.5),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable checks"),
):
    """Diagnose the usbmuxd/NetworkUSB endpoint, device visibility and pairing."""

    asyncio.run(_doctor_async(udid, usbmux_address=usbmux_address, timeout=timeout, json_output=json_output))


async def _doctor_async(
    udid: Optional[str],
    *,
    usbmux_address: Optional[str] = None,
    timeout: float = 5.0,
    json_output: bool = False,
) -> None:
    from iscan import device as dev

    try:
        config = _resolve_cli_transport(usbmux_address)
    except IscanError as exc:
        code = _exit_from_error(exc, ExitCode.TRANSPORT_UNAVAILABLE)
        Progress(json_output).error(exc.message, code=code, detail=exc.detail)
        raise typer.Exit(int(code))

    checks: list[dict[str, Any]] = []
    probe = await probe_transport(config, timeout=timeout)
    checks.append({"name": "transport", "ok": probe.ok, **probe.as_dict()})
    devices: list[dict[str, str]] = []
    failure_code = ExitCode.OK
    if probe.ok:
        try:
            devices = await dev.list_devices_async(transport=config, timeout=timeout)
            checks.append({"name": "device_list", "ok": bool(devices), "count": len(devices)})
            if not devices:
                failure_code = ExitCode.DEVICE_NOT_FOUND
            else:
                selected = udid or devices[0]["udid"]
                try:
                    lockdown = await dev.connect_async(
                        selected, transport=config, timeout=max(timeout, 10.0), autopair=False
                    )
                    await dev.close_async(lockdown)
                    checks.append({"name": "lockdown", "ok": True, "udid": selected})
                except DeviceConnectionError as exc:
                    failure_code = _exit_from_error(exc)
                    checks.append(
                        {
                            "name": "lockdown",
                            "ok": False,
                            "udid": selected,
                            "code": failure_code.name.lower(),
                            "detail": exc.message,
                        }
                    )
        except DeviceConnectionError as exc:
            failure_code = _exit_from_error(exc, ExitCode.TRANSPORT_UNAVAILABLE)
            checks.append({"name": "device_list", "ok": False, "detail": exc.message})
    else:
        failure_code = ExitCode.TRANSPORT_UNAVAILABLE

    payload = {
        "ok": failure_code == ExitCode.OK,
        "exit_code": int(failure_code),
        "transport": describe_transport(config),
        "checks": checks,
        "devices": devices,
    }
    if json_output:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        table = Table(title="iScan doctor", box=box.ROUNDED)
        table.add_column("Check", style="cyan")
        table.add_column("Result")
        for check in checks:
            table.add_row(check["name"], "OK" if check.get("ok") else str(check.get("detail", "failed")))
        console.print(table)
        if failure_code:
            console.print(f"[yellow]Exit code: {int(failure_code)} ({failure_code.name.lower()})[/]")
    if failure_code:
        raise typer.Exit(int(failure_code))


@app.command()
def pair(
    udid: Optional[str] = typer.Option(None, "--udid", help="Device UDID"),
    usbmux_address: Optional[str] = typer.Option(None, "--usbmux-address", "--socket-path", help=_transport_option_help()),
    wait: float = typer.Option(60.0, "--wait", min=1.0, help="Seconds to wait for the device"),
    pair_timeout: float = typer.Option(45.0, "--pair-timeout", min=1.0, help="Seconds for the Trust dialog"),
    json_progress: bool = typer.Option(False, "--json-progress", help="Emit JSON-lines progress"),
):
    """Wait for a device and explicitly complete the Trust/pairing flow."""

    asyncio.run(
        _pair_async(
            udid,
            usbmux_address=usbmux_address,
            wait=wait,
            pair_timeout=pair_timeout,
            json_progress=json_progress,
        )
    )


async def _pair_async(
    udid: Optional[str],
    *,
    usbmux_address: Optional[str] = None,
    wait: float = 60.0,
    pair_timeout: float = 45.0,
    json_progress: bool = False,
) -> None:
    from iscan import device as dev

    progress = Progress(json_progress)
    try:
        config = _resolve_cli_transport(usbmux_address)
    except IscanError as exc:
        code = _exit_from_error(exc, ExitCode.TRANSPORT_UNAVAILABLE)
        progress.error(exc.message, code=code, detail=exc.detail)
        raise typer.Exit(int(code))

    deadline = monotonic() + wait
    selected: Optional[str] = udid
    while selected is None and monotonic() < deadline:
        try:
            devices = await dev.list_devices_async(transport=config, timeout=min(5.0, wait))
        except DeviceConnectionError as exc:
            code = _exit_from_error(exc, ExitCode.TRANSPORT_UNAVAILABLE)
            progress.error(exc.message, code=code, detail=exc.detail)
            raise typer.Exit(int(code))
        if devices:
            selected = devices[0]["udid"]
            break
        progress.emit({"event": "waiting", "message": "No device visible yet"})
        await asyncio.sleep(min(1.0, max(0.1, deadline - monotonic())))

    if selected is None:
        code = ExitCode.DEVICE_NOT_FOUND
        progress.error("No iOS device became visible before the timeout.", code=code)
        raise typer.Exit(int(code))

    progress.emit({"event": "pairing", "udid": selected})
    lockdown = None
    try:
        progress.info("[bold cyan]If prompted, tap Trust on the iPhone…[/]")
        lockdown = await dev.connect_async(
            selected,
            transport=config,
            timeout=max(pair_timeout, 10.0),
            autopair=True,
            pair_timeout=pair_timeout,
        )
    except DeviceConnectionError as exc:
        code = _exit_from_error(exc)
        if code == ExitCode.REPORT_FAILED:
            code = ExitCode.NOT_PAIRED
        progress.error(exc.message, code=code, detail=exc.detail)
        raise typer.Exit(int(code))
    finally:
        if lockdown is not None:
            await dev.close_async(lockdown)
    progress.emit({"event": "paired", "udid": selected})
    progress.info("[green]✓ Device paired with this Mac.[/]")


@app.command()
def version() -> None:
    """Show iScan version."""

    from iscan import __version__

    console.print(f"iScan v{__version__}")
