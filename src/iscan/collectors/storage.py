from iscan.models import Storage


async def collect_async(lockdown) -> Storage:
    st = Storage()
    try:
        from pymobiledevice3.services.afc import AfcService
        afc = AfcService(lockdown)
        info = await afc.get_device_info()
        total = info.get('FSTotalBytes')
        free = info.get('FSFreeBytes')
        if total:
            st.total_capacity = int(total)
        if free:
            st.available = int(free)
        if st.total_capacity and st.available is not None:
            st.used = st.total_capacity - st.available
            st.used_percent = round(st.used / st.total_capacity * 100, 1)
    except Exception:
        pass
    return st


def collect(lockdown) -> Storage:
    """Sync fallback for tests."""
    st = Storage()
    try:
        v = lockdown.all_values
        total = v.get('TotalDataCapacity')
        avail = v.get('TotalDataAvailable')
        if total:
            st.total_capacity = int(total)
        if avail:
            st.available = int(avail)
        if st.total_capacity and st.available is not None:
            st.used = st.total_capacity - st.available
            st.used_percent = round(st.used / st.total_capacity * 100, 1)
    except Exception:
        pass
    return st
