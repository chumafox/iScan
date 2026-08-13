import asyncio
from iscan.models import DeviceInfo

# Mapping of ProductType to commercial names
MODEL_NAMES = {
    # iPhone 12 series
    "iPhone13,1": "iPhone 12 mini",
    "iPhone13,2": "iPhone 12",
    "iPhone13,3": "iPhone 12 Pro",
    "iPhone13,4": "iPhone 12 Pro Max",
    # iPhone 13 series
    "iPhone14,2": "iPhone 13 Pro",
    "iPhone14,3": "iPhone 13 Pro Max",
    "iPhone14,4": "iPhone 13 mini",
    "iPhone14,5": "iPhone 13",
    # iPhone SE 3rd Gen
    "iPhone14,6": "iPhone SE (3rd generation)",
    # iPhone 14 series
    "iPhone14,7": "iPhone 14",
    "iPhone14,8": "iPhone 14 Plus",
    "iPhone15,2": "iPhone 14 Pro",
    "iPhone15,3": "iPhone 14 Pro Max",
    # iPhone 15 series
    "iPhone15,4": "iPhone 15",
    "iPhone15,5": "iPhone 15 Plus",
    "iPhone16,1": "iPhone 15 Pro",
    "iPhone16,2": "iPhone 15 Pro Max",
    # iPhone 16 series
    "iPhone17,1": "iPhone 16 Pro",
    "iPhone17,2": "iPhone 16 Pro Max",
    "iPhone17,3": "iPhone 16",
    "iPhone17,4": "iPhone 16 Plus",
}

# Simplified mapping for DeviceColor code to name
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


def _decode_bytes(val) -> str:
    if isinstance(val, bytes):
        try:
            return val.decode('utf-8').strip('\x00').strip()
        except UnicodeDecodeError:
            return "".join(chr(c) if 32 <= c <= 126 else "" for c in val).strip()
    return str(val).strip()


async def collect_async(lockdown) -> DeviceInfo:
    info = DeviceInfo()
    try:
        v = lockdown.all_values
        info.product_type = v.get('ProductType')
        info.product_version = v.get('ProductVersion')
        info.build_version = v.get('BuildVersion')
        info.device_name = v.get('DeviceName')
        info.serial_number = v.get('SerialNumber')
        info.udid = v.get('UniqueDeviceID')
        info.activation_state = v.get('ActivationState')
        info.baseband_version = v.get('BasebandVersion')

        # Model Name
        prod_type = info.product_type
        if prod_type:
            info.commercial_name = MODEL_NAMES.get(prod_type, prod_type)

        # Device Color
        color_code = v.get('DeviceColor')
        if color_code is not None:
            try:
                info.device_color = COLOR_NAMES.get(int(color_code), f"Color Code {color_code}")
            except (ValueError, TypeError):
                info.device_color = str(color_code)

        # Model Number (Sales Model): e.g. 3H480TA/A
        model_num = v.get('ModelNumber')
        region_info = v.get('RegionInfo')
        if model_num and region_info:
            info.sales_model = f"{_decode_bytes(model_num)}{_decode_bytes(region_info)}"
        elif model_num:
            info.sales_model = _decode_bytes(model_num)

        # Carrier Lock / SIM Status
        activation = v.get('ActivationState')
        postponement = v.get('kCTPostponementStatus')
        if postponement:
            postponement_str = _decode_bytes(postponement)
            if postponement_str == 'kCTPostponementStatusActivated' and activation == 'Activated':
                info.sim_status = 'no_restrictions'
            elif postponement_str == 'kCTPostponementStatusDelay':
                info.sim_status = 'locked'
            else:
                info.sim_status = 'unknown'
        else:
            if activation == 'Activated':
                info.sim_status = 'no_restrictions'
            else:
                info.sim_status = 'unknown'
    except Exception:
        pass

    # Find My iPhone & Apple ID (query from options node)
    try:
        from pymobiledevice3.services.diagnostics import DiagnosticsService
        diag = DiagnosticsService(lockdown)
        opts = await diag.ioregistry(name="options")
        if opts and isinstance(opts, dict):
            fmi = opts.get('fm-activation-locked')
            if fmi:
                fmi_str = _decode_bytes(fmi)
                if fmi_str.upper() == 'YES':
                    info.fmi_status = 'enabled'
                else:
                    info.fmi_status = 'disabled'
            
            apple_id = opts.get('fm-account-masked')
            if apple_id:
                info.apple_id = _decode_bytes(apple_id)
    except Exception:
        pass

    # Regulatory Model: e.g. A2399 (query from IORegistry device-tree)
    try:
        from pymobiledevice3.services.diagnostics import DiagnosticsService
        diag = DiagnosticsService(lockdown)
        dt = await diag.ioregistry(name="device-tree")
        if dt and isinstance(dt, dict):
            reg_model = dt.get('regulatory-model-number')
            if reg_model:
                info.regulatory_model = _decode_bytes(reg_model)
    except Exception:
        pass

    return info


def collect(lockdown) -> DeviceInfo:
    """Sync fallback for tests using fixture."""
    info = DeviceInfo()
    try:
        v = lockdown.all_values
        info.product_type = v.get('ProductType')
        info.product_version = v.get('ProductVersion')
        info.build_version = v.get('BuildVersion')
        info.device_name = v.get('DeviceName')
        info.serial_number = v.get('SerialNumber')
        info.udid = v.get('UniqueDeviceID')
        info.activation_state = v.get('ActivationState')
        info.baseband_version = v.get('BasebandVersion')
        
        info.commercial_name = MODEL_NAMES.get(info.product_type, info.product_type)
        info.device_color = "Black"
        info.fmi_status = "disabled"
        
        model_num = v.get('ModelNumber')
        region_info = v.get('RegionInfo')
        if model_num and region_info:
            info.sales_model = f"{model_num}{region_info}"
        elif model_num:
            info.sales_model = model_num
            
        postponement = v.get('kCTPostponementStatus')
        if postponement == 'kCTPostponementStatusActivated' and info.activation_state == 'Activated':
            info.sim_status = 'no_restrictions'
        else:
            info.sim_status = 'unknown'
    except Exception:
        pass
    return info
