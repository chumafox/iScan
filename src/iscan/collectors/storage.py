"""Storage capacity collector with AFC and lockdown fallbacks."""

from __future__ import annotations

from typing import Any, Mapping

from iscan.collectors.common import as_int, call_maybe_async
from iscan.models import Storage


def _finish(st: Storage) -> Storage:
    if st.total_capacity is not None and st.total_capacity > 0 and st.available is not None:
        # A stale AFC response should not produce negative or >100% usage.
        st.available = max(0, min(st.available, st.total_capacity))
        st.used = st.total_capacity - st.available
        st.used_percent = round(st.used / st.total_capacity * 100, 1)
    return st


def _from_mapping(values: Any) -> Storage:
    st = Storage()
    if not isinstance(values, Mapping):
        return st
    total = values.get("FSTotalBytes", values.get("TotalDataCapacity"))
    available = values.get("FSFreeBytes", values.get("TotalDataAvailable"))
    st.total_capacity = as_int(total)
    st.available = as_int(available)
    return _finish(st)


async def collect_async(lockdown) -> Storage:
    st = Storage()
    try:
        from pymobiledevice3.services.afc import AfcService

        info = await call_maybe_async(AfcService(lockdown).get_device_info)
        st = _from_mapping(info)
    except Exception:
        pass

    if st.total_capacity is None or st.available is None:
        try:
            st = _from_mapping(lockdown.all_values)
        except Exception:
            pass
    return _finish(st)


def collect(lockdown) -> Storage:
    """Synchronous fallback for fixture-based scripts."""

    try:
        return _from_mapping(lockdown.all_values)
    except Exception:
        return Storage()
