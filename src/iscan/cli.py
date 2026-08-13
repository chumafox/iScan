import asyncio
import typer
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich import box

app = typer.Typer(
    name="iscan",
    help="iOS device diagnostics CLI — generates detailed HTML reports",
    add_completion=False,
)
console = Console()


@app.command()
def report(
    lang: str = typer.Option('auto', '--lang', '-l', help='Report language: en, ru, auto'),
    output: Optional[Path] = typer.Option(None, '--output', '-o', help='Output file path'),
    udid: Optional[str] = typer.Option(None, '--udid', help='Device UDID'),
    open_browser: bool = typer.Option(False, '--open', help='Open report in browser'),
):
    """Collect device diagnostics and generate an HTML report."""
    asyncio.run(_report_async(lang, output, udid, open_browser))


async def _report_async(lang, output, udid, open_browser):
    from iscan import device as dev
    from iscan.collectors import collect_all
    from iscan.report.render import render_html
    from iscan.report.i18n import detect_lang
    from datetime import datetime

    if lang == 'auto':
        lang = detect_lang()

    with console.status('[bold cyan]Connecting to device...[/bold cyan]'):
        try:
            lockdown = await dev.connect_async(udid)
        except RuntimeError as e:
            console.print(f'[bold red]Error:[/bold red] {e}')
            raise typer.Exit(1)

    console.print('[green]✓[/green] Connected:', lockdown.all_values.get('DeviceName', 'Unknown'))

    with console.status('[bold cyan]Collecting diagnostics...[/bold cyan]'):
        diagnostic = await collect_all(lockdown)

    console.print('[green]✓[/green] Data collected')

    html = render_html(diagnostic, lang)

    if output is None:
        serial = diagnostic.device.serial_number or 'unknown'
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        output = Path(f'iscan_report_{serial}_{ts}.html')

    output.write_text(html, encoding='utf-8')
    console.print(f'[bold green]✓[/bold green] Report saved: [cyan]{output}[/cyan]')

    if open_browser:
        import webbrowser
        webbrowser.open(output.resolve().as_uri())


@app.command()
def info(
    udid: Optional[str] = typer.Option(None, '--udid', help='Device UDID'),
):
    """Show key device info in the terminal (no HTML)."""
    asyncio.run(_info_async(udid))


async def _info_async(udid):
    from iscan import device as dev
    from iscan.collectors import collect_all

    with console.status('[bold cyan]Connecting...[/bold cyan]'):
        try:
            lockdown = await dev.connect_async(udid)
        except RuntimeError as e:
            console.print(f'[bold red]Error:[/bold red] {e}')
            raise typer.Exit(1)

    with console.status('[bold cyan]Reading device info...[/bold cyan]'):
        d = await collect_all(lockdown)

    def v(val):
        return str(val) if val is not None else '[dim]N/A[/dim]'

    t = Table(title='[bold]Device Info[/bold]', box=box.ROUNDED, show_header=True)
    t.add_column('Field', style='cyan', min_width=25)
    t.add_column('Value', style='white')

    t.add_row('Device Name', v(d.device.device_name))
    t.add_row('Model (Commercial)', v(d.device.commercial_name))
    t.add_row('Model (Sales)', v(d.device.sales_model))
    t.add_row('Model (Regulatory)', v(d.device.regulatory_model))
    t.add_row('Device Color', v(d.device.device_color))
    t.add_row('Device Type', v(d.device.product_type))
    t.add_row('iOS Version', v(d.device.product_version))
    t.add_row('Serial Number', v(d.device.serial_number))
    t.add_row('UDID', v(d.device.udid))
    t.add_row('IMEI', v(d.identifiers.imei))
    t.add_row('ECID', v(d.identifiers.ecid))
    t.add_row('Wi-Fi MAC', v(d.identifiers.wifi_mac))
    sim_val = d.device.sim_status
    if sim_val == 'no_restrictions':
        sim_display = 'No SIM restrictions'
    elif sim_val == 'locked':
        sim_display = 'SIM Locked'
    elif sim_val == 'unknown':
        sim_display = 'Unknown'
    else:
        sim_display = str(sim_val) if sim_val else 'N/A'
    t.add_row('SIM Lock', sim_display)
    
    fmi_val = d.device.fmi_status
    if fmi_val == 'enabled':
        fmi_display = 'Enabled'
    elif fmi_val == 'disabled':
        fmi_display = 'Disabled'
    else:
        fmi_display = 'Unknown'
    if d.device.apple_id:
        fmi_display += f" ({d.device.apple_id})"
    t.add_row('iCloud Lock', fmi_display)
    t.add_row('Activation State', v(d.device.activation_state))




    health = f'{d.battery.health_percent:.0f}%' if d.battery.health_percent is not None else 'N/A'
    charging = ''
    if d.battery.is_charging is True:
        charging = ' ⚡ charging'
    elif d.battery.is_charging is False:
        charging = ''
    t.add_row('Battery Health', health + charging)
    t.add_row('Battery Cycles', v(d.battery.cycle_count))
    t.add_row('Battery Serial', v(d.battery.battery_serial))

    if d.storage.total_capacity:
        storage_str = f"{d.storage.used / 1024**3:.1f} / {d.storage.total_capacity / 1024**3:.0f} GB ({d.storage.used_percent}%)"
    else:
        storage_str = 'N/A'
    t.add_row('Storage Used', storage_str)

    t.add_row('Mainboard (MLB)', v(d.components.mlb_serial))
    t.add_row('WiFi/BT Board', v(d.components.wireless_board_serial))
    t.add_row('SSD Storage', v(d.components.ssd_serial))
    t.add_row('Display Module', v(d.components.display_serial))
    t.add_row('Touch Screen', v(d.components.touch_serial))
    t.add_row('Face/Touch ID', v(d.components.biometric_serial))
    t.add_row('Light Sensor (ALS)', v(d.components.als_serial))

    console.print(t)


@app.command(name='list')
def list_devices():
    """List all connected iOS devices."""
    asyncio.run(_list_async())


async def _list_async():
    from iscan import device as dev

    with console.status('[bold cyan]Scanning for devices...[/bold cyan]'):
        devices = await dev.list_devices_async()

    if not devices:
        console.print('[yellow]No devices found.[/yellow] Connect an iOS device via USB and trust this computer.')
        return

    t = Table(title='Connected Devices', box=box.ROUNDED)
    t.add_column('UDID', style='dim', min_width=40)
    t.add_column('Name')
    t.add_column('Model', style='cyan')
    t.add_column('iOS', style='green')

    for d in devices:
        t.add_row(d['udid'], d['name'], d['model'], d['ios'])

    console.print(t)


@app.command()
def version():
    """Show iScan version."""
    from iscan import __version__
    console.print(f'[bold]iScan[/bold] v{__version__}')
