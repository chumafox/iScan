import asyncio
import os
from iscan.models import Components

# Enable userspace tunnel in case it is needed for IORegistry calls
os.environ["PYMOBILEDEVICE3_USERSPACE"] = "1"


def _decode_bytes(val) -> str:
    if isinstance(val, bytes):
        try:
            return val.decode('utf-8').strip('\x00').strip()
        except UnicodeDecodeError:
            return "".join(chr(c) if 32 <= c <= 126 else "" for c in val).strip()
    return str(val).strip()


async def _collect_async(lockdown) -> Components:
    comp = Components()

    # 1. Try to read from lockdown all_values (always available, fast)
    try:
        v = lockdown.all_values
        comp.mlb_serial = v.get('MLBSerialNumber') or v.get('MainboardSerialNumber')
        comp.wireless_board_serial = v.get('WirelessBoardSerialNumber')
    except Exception:
        pass

    # 2. Query IORegistry for product node (contains Display, FaceID, ALS, Touch)
    try:
        from pymobiledevice3.services.diagnostics import DiagnosticsService
        diag = DiagnosticsService(lockdown)
        prod = await diag.ioregistry(name="product")
        if prod and isinstance(prod, dict):
            # Parse display raw serial: G9Q0373HH6ELQHJAX+A1000... -> G9Q0373HH6ELQHJAX
            raw_panel = prod.get('raw-panel-serial-number')
            if raw_panel:
                decoded_panel = _decode_bytes(raw_panel)
                comp.display_serial = decoded_panel.split('+')[0] if '+' in decoded_panel else decoded_panel
            
            # Parse biometric (FaceID TrueDepth rosaline serial)
            rosaline = prod.get('rosaline-serial-num')
            if rosaline:
                comp.biometric_serial = _decode_bytes(rosaline)
                
            # Parse touch flex / coverglass serial
            coverglass = prod.get('coverglass-serial-number')
            if coverglass:
                decoded_cg = _decode_bytes(coverglass)
                comp.touch_serial = decoded_cg.split('+')[0] if '+' in decoded_cg else decoded_cg

            # Parse Ambient Light Sensor
            als = prod.get('ambient-light-sensor-serial-num')
            if als:
                comp.als_serial = _decode_bytes(als)
    except Exception:
        pass

    # 3. Query IORegistry for SSD Serial (AppleANS3CGv2Controller)
    try:
        from pymobiledevice3.services.diagnostics import DiagnosticsService
        diag = DiagnosticsService(lockdown)
        ssd = await diag.ioregistry(name="AppleANS3CGv2Controller")
        if ssd and isinstance(ssd, dict):
            ssd_sn = ssd.get('Serial Number')
            if ssd_sn:
                comp.ssd_serial = _decode_bytes(ssd_sn)
    except Exception:
        pass

    # 4. Fallback for MLB from device-tree node if still missing
    if not comp.mlb_serial:
        try:
            from pymobiledevice3.services.diagnostics import DiagnosticsService
            diag = DiagnosticsService(lockdown)
            dt = await diag.ioregistry(name="device-tree")
            if dt and isinstance(dt, dict):
                mlb = dt.get('mlb-serial-number')
                if mlb:
                    comp.mlb_serial = _decode_bytes(mlb)
        except Exception:
            pass

    return comp


def collect(lockdown) -> Components:
    """Sync fallback for tests using fixture."""
    comp = Components()
    try:
        v = lockdown.all_values
        comp.mlb_serial = v.get('MLBSerialNumber') or v.get('MainboardSerialNumber')
        comp.wireless_board_serial = v.get('WirelessBoardSerialNumber')
    except Exception:
        pass
    return comp
