from __future__ import annotations

from iscan.errors import ExitCode, classify_connection_error


def test_classify_no_device():
    error = classify_connection_error(RuntimeError("No device found"))
    assert error.exit_code == ExitCode.DEVICE_NOT_FOUND


def test_classify_not_paired():
    error = classify_connection_error(RuntimeError("Device is not paired"))
    assert error.exit_code == ExitCode.NOT_PAIRED


def test_classify_transport():
    error = classify_connection_error(ConnectionRefusedError("Connection refused to usbmuxd"))
    assert error.exit_code == ExitCode.TRANSPORT_UNAVAILABLE


def test_classify_does_not_treat_generic_index_error_as_missing_device():
    error = classify_connection_error(IndexError("list index out of range"))
    assert error.exit_code == ExitCode.REPORT_FAILED


def test_classify_does_not_treat_ssl_socket_as_transport():
    error = classify_connection_error(RuntimeError("SSLSocket handshake failed during pairing dialog"))
    assert error.exit_code == ExitCode.NOT_PAIRED
