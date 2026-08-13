import asyncio
from typing import Optional
from rich.console import Console

console = Console()


async def connect_async(udid: Optional[str] = None):
    """Async connect to iOS device via usbmux."""
    from pymobiledevice3.lockdown import create_using_usbmux
    try:
        return await create_using_usbmux(serial=udid)
    except Exception as e:
        msg = str(e)
        if 'No device' in msg or 'not connected' in msg.lower() or 'Unable to find' in msg:
            raise RuntimeError(
                "No iOS device found.\n"
                "\u2022 Connect your iPhone/iPad via USB\n"
                "\u2022 Tap 'Trust' on the device screen\n"
                "\u2022 For iOS 17+: run: sudo pymobiledevice3 remote start-tunnel"
            )
        raise RuntimeError(f"Connection failed: {msg}")


def connect(udid: Optional[str] = None):
    """Sync wrapper — only for tests/scripts. CLI uses connect_async directly."""
    return asyncio.run(connect_async(udid))


async def list_devices_async() -> list[dict]:
    from pymobiledevice3.usbmux import select_devices_by_connection_type
    from pymobiledevice3.lockdown import create_using_usbmux
    devices = []
    try:
        for device in await select_devices_by_connection_type('USB'):
            try:
                lk = await create_using_usbmux(serial=device.serial)
                info = lk.all_values
                devices.append({
                    'udid': device.serial,
                    'model': info.get('ProductType', 'Unknown'),
                    'name': info.get('DeviceName', ''),
                    'ios': info.get('ProductVersion', ''),
                })
            except Exception:
                devices.append({'udid': device.serial, 'model': 'Unknown', 'name': '', 'ios': ''})
    except Exception:
        pass
    return devices
