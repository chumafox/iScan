from __future__ import annotations

import asyncio
import json
import os
import socket
import tempfile

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
    sock_dir = tempfile.mkdtemp(dir="/tmp", prefix="isock_")
    socket_path = os.path.join(sock_dir, "bridge.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(socket_path)
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
        assert config.address == socket_path
        assert config.networkusb_agent == "100.64.0.7:8721"
        assert config.networkusb_fingerprint == "AA:BB"
        assert config.networkusb_version == "0.2.0"
    finally:
        server.close()
        import shutil
        shutil.rmtree(sock_dir, ignore_errors=True)


def test_socket_privacy_warning_for_world_accessible_unix_socket():
    from iscan.transport import TransportConfig, socket_privacy_warning

    sock_dir = tempfile.mkdtemp(dir="/tmp", prefix="ipriv_")
    path = os.path.join(sock_dir, "open.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    try:
        os.chmod(path, 0o777)
        warning = socket_privacy_warning(TransportConfig(address=path, kind="unix", source="cli"))
        assert warning is not None
        assert "0777" in warning or "0o777" in warning
        os.chmod(path, 0o700)
        assert socket_privacy_warning(TransportConfig(address=path, kind="unix", source="cli")) is None
        assert socket_privacy_warning(TransportConfig(kind="system")) is None
    finally:
        server.close()
        import shutil

        shutil.rmtree(sock_dir, ignore_errors=True)


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
        sock_dir = tempfile.mkdtemp(dir="/tmp", prefix="iprobe_")
        path = os.path.join(sock_dir, "probe.sock")

        async def handle(reader, writer):
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_unix_server(handle, path=path)
        try:
            result = await probe_transport(
                TransportConfig(address=path, source="test", kind="unix")
            )
            assert result.ok is True
            assert result.kind == "unix"
        finally:
            server.close()
            await server.wait_closed()
            import shutil
            shutil.rmtree(sock_dir, ignore_errors=True)

    asyncio.run(scenario())

