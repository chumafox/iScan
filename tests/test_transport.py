from __future__ import annotations

import asyncio
import json
import os
import socket

from iscan.transport import (
    address_kind,
    normalize_usbmux_address,
    resolve_transport,
)


def test_transport_address_dialects():
    assert normalize_usbmux_address("/tmp/usbmuxd.sock") == "/tmp/usbmuxd.sock"
    assert normalize_usbmux_address("unix:/tmp/usbmuxd.sock") == "/tmp/usbmuxd.sock"
    assert normalize_usbmux_address("unix:///tmp/usbmuxd.sock") == "/tmp/usbmuxd.sock"
    assert normalize_usbmux_address("tcp://127.0.0.1:8721") == "127.0.0.1:8721"
    assert address_kind("127.0.0.1:8721") == "tcp"


def test_transport_precedence_and_legacy_env():
    config = resolve_transport(
        environ={
            "USBMUXD_SOCKET_ADDRESS": "unix:/tmp/first.sock",
            "PYMOBILEDEVICE3_USBMUX": "/tmp/second.sock",
        }
    )
    assert config.address == "/tmp/first.sock"
    assert config.source == "env:USBMUXD_SOCKET_ADDRESS"

    config = resolve_transport(
        environ={"PYMOBILEDEVICE3_USBMUX": "unix:/tmp/second.sock"}
    )
    assert config.address == "/tmp/second.sock"
    assert config.source == "env:PYMOBILEDEVICE3_USBMUX"


def test_active_networkusb_metadata_is_used_only_for_a_live_socket(tmp_path, monkeypatch):
    socket_path = tmp_path / "bridge.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    try:
        active = tmp_path / "active.json"
        active.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "socket": f"unix:{socket_path}",
                    "agent_host": "100.64.0.7",
                    "agent_port": 8721,
                    "fingerprint": "AA:BB",
                    "version": "0.2.0",
                }
            ),
            encoding="utf-8",
        )
        config = resolve_transport(environ={}, active_file=active)
        assert config.source == "networkusb-active"
        assert config.address == str(socket_path)
        assert config.networkusb_agent == "100.64.0.7:8721"
        assert config.networkusb_fingerprint == "AA:BB"
        assert config.networkusb_version == "0.2.0"
    finally:
        server.close()


def test_active_metadata_ignores_stale_socket(tmp_path):
    active = tmp_path / "active.json"
    active.write_text(
        json.dumps({"pid": os.getpid(), "socket": str(tmp_path / "gone.sock")}),
        encoding="utf-8",
    )
    config = resolve_transport(environ={}, active_file=active)
    assert config.source == "system"


def test_probe_unix_endpoint(tmp_path):
    from iscan.transport import TransportConfig, probe_transport

    async def scenario():
        path = tmp_path / "probe.sock"

        async def handle(reader, writer):
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_unix_server(handle, path=str(path))
        try:
            result = await probe_transport(
                TransportConfig(address=str(path), source="test", kind="unix")
            )
            assert result.ok is True
            assert result.kind == "unix"
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(scenario())
