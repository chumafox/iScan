from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

@dataclass
class DeviceInfo:
    product_type: Optional[str] = None  # iPhone15,2
    product_version: Optional[str] = None  # 17.4
    build_version: Optional[str] = None
    device_name: Optional[str] = None
    serial_number: Optional[str] = None
    udid: Optional[str] = None
    activation_state: Optional[str] = None
    baseband_version: Optional[str] = None
    sales_model: Optional[str] = None  # e.g. 3H480TA/A
    regulatory_model: Optional[str] = None  # e.g. A2399
    sim_status: Optional[str] = None  # e.g. Ready
    device_color: Optional[str] = None  # e.g. Black
    fmi_status: Optional[str] = None  # e.g. Enabled
    apple_id: Optional[str] = None  # e.g. c•••••@me.com
    commercial_name: Optional[str] = None  # e.g. iPhone 12 mini



@dataclass
class Identifiers:
    imei: Optional[str] = None
    imei2: Optional[str] = None
    ecid: Optional[str] = None
    wifi_mac: Optional[str] = None
    bt_mac: Optional[str] = None
    meid: Optional[str] = None

@dataclass
class Battery:
    cycle_count: Optional[int] = None
    design_capacity: Optional[int] = None
    full_charge_capacity: Optional[int] = None
    health_percent: Optional[float] = None
    battery_serial: Optional[str] = None
    is_charging: Optional[bool] = None

@dataclass
class Storage:
    total_capacity: Optional[int] = None  # bytes
    available: Optional[int] = None  # bytes
    used: Optional[int] = None
    used_percent: Optional[float] = None

@dataclass
class Components:
    mlb_serial: Optional[str] = None  # mainboard
    wireless_board_serial: Optional[str] = None  # WiFi/BT board
    display_serial: Optional[str] = None
    rear_camera_serial: Optional[str] = None
    front_camera_serial: Optional[str] = None
    biometric_serial: Optional[str] = None  # Touch/Face ID
    ssd_serial: Optional[str] = None  # SSD Storage
    als_serial: Optional[str] = None  # Ambient Light Sensor
    touch_serial: Optional[str] = None  # Coverglass / Touch Flex

@dataclass
class DiagnosticReport:
    device: DeviceInfo = field(default_factory=DeviceInfo)
    identifiers: Identifiers = field(default_factory=Identifiers)
    battery: Battery = field(default_factory=Battery)
    storage: Storage = field(default_factory=Storage)
    components: Components = field(default_factory=Components)
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    iscan_version: str = "0.1.0"
