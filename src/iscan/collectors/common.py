"""Small normalization helpers for inconsistent iOS lockdown dictionaries."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Iterable, Optional


async def maybe_await(value: Any) -> Any:
    """Accept async pymobiledevice3 calls and synchronous test doubles."""

    return await value if inspect.isawaitable(value) else value


async def call_maybe_async(function: Any, *args: Any, **kwargs: Any) -> Any:
    """Call either a sync or async pymobiledevice3 method without blocking."""

    if inspect.iscoroutinefunction(function):
        return await function(*args, **kwargs)
    result = await asyncio.to_thread(function, *args, **kwargs)
    return await maybe_await(result)


def decode_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="replace").strip("\x00").strip() or None
        except Exception:
            return None
    text = str(value).strip()
    return text or None


def first_value(mapping: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None and value != "":
            return value
    return None


def as_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None


def as_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def as_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    text = decode_value(value)
    if text is None:
        return None
    lowered = text.lower()
    if lowered in {"1", "true", "yes", "y", "on", "charging"}:
        return True
    if lowered in {"0", "false", "no", "n", "off", "notcharging"}:
        return False
    return None


def flatten_mapping(value: Any) -> dict[str, Any]:
    """Flatten nested IORegistry responses while preserving leaf names."""

    result: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            result[str(key)] = child
            if isinstance(child, dict):
                result.update(flatten_mapping(child))
            elif isinstance(child, list):
                for item in child:
                    if isinstance(item, dict):
                        result.update(flatten_mapping(item))
    elif isinstance(value, list):
        for item in value:
            result.update(flatten_mapping(item))
    return result


def value_by_normalized_key(mapping: dict[str, Any], keys: Iterable[str]) -> Any:
    def normalize(key: Any) -> str:
        return str(key).lower().replace("_", "-").replace(" ", "-")

    wanted = {normalize(key) for key in keys}
    for key, value in mapping.items():
        normalized = normalize(key)
        if normalized in wanted and value is not None and value != "":
            return value
    return None


def has_data(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, bytes)):
        return bool(value)
    if isinstance(value, dict):
        return any(has_data(item) for item in value.values())
    if hasattr(value, "__dataclass_fields__"):
        return any(has_data(item) for item in vars(value).values())
    return True
