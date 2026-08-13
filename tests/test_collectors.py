from iscan.collectors import device_info, battery, storage

def test_device_info(fake_lockdown):
    info = device_info.collect(fake_lockdown)
    assert info.product_type == 'iPhone16,1'
    assert info.product_version == '17.4.1'
    assert info.serial_number == 'C3XNHF2KMT4P'
    assert info.activation_state == 'Activated'
    assert info.sales_model == 'MU7E3LL/A'
    assert info.sim_status == 'no_restrictions'



def test_battery(fake_lockdown):
    bat = battery.collect(fake_lockdown)
    assert bat.cycle_count == 127
    assert bat.design_capacity == 3274
    assert bat.full_charge_capacity == 3120
    assert bat.health_percent is not None
    assert 90 <= bat.health_percent <= 100  # 3120/3274 ≈ 95.3%
    assert bat.battery_serial == 'F9RNXBT0ABCD'
    assert bat.is_charging is False

def test_storage(fake_lockdown):
    st = storage.collect(fake_lockdown)
    assert st.total_capacity == 128_000_000_000
    assert st.available == 45_000_000_000
    assert st.used == 83_000_000_000
    assert st.used_percent is not None

def test_missing_keys_resilience():
    """Collectors must not crash when keys are missing."""
    class EmptyLockdown:
        all_values = {}
        def get_value(self, domain=None, key=None):
            return {}
    
    lk = EmptyLockdown()
    info = device_info.collect(lk)
    assert info.serial_number is None
    
    bat = battery.collect(lk)
    assert bat.health_percent is None
    
    st = storage.collect(lk)
    assert st.total_capacity is None
