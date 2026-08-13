# iScan

![Version](https://img.shields.io/badge/version-0.2.1-blue.svg)

**iScan** is a cross-platform iOS diagnostics CLI that generates a self-contained HTML report. It is designed to work with a local `usbmuxd` socket and with [NetworkUSB](https://github.com/chumafox/NetworkUSB), which exposes an iPhone attached to another Mac as a local socket.

## What changed in 0.2

- NetworkUSB is a first-class transport: explicit socket selection, environment compatibility and optional active-endpoint discovery.
- `iscan doctor` checks the socket, device visibility and lockdown/pairing instead of failing deep inside a report.
- `iscan pair --wait` makes the remote “Trust This Computer?” step explicit.
- `report --json-progress` emits a stable JSON-lines contract for NetworkUSB's menu-bar client.
- Collectors run independently with per-service timeouts. A missing battery or IORegistry service no longer destroys the whole report.
- Reports record transport provenance and collection status, escape device-controlled values, contain no machine-local image paths and are written atomically.
- Collectors run one lockdown service at a time. A slow first service no longer starves battery/storage/components of their timeout.
- `report --json` writes a sidecar next to the HTML for supervisors that should not parse markup.
- `list` no longer assumes every device must be labelled `USB`; this matters for remote and Wi-Fi mux connections.

## Installation

Using `uv` (recommended):

```bash
uv tool install ./
```

Or using `pipx`:

```bash
pipx install ./
```

## Usage

Generate and open an HTML report:

```bash
iscan report --open
```

Show key information in the terminal:

```bash
iscan info
iscan list
iscan --version
```

Check the complete transport path before running a report:

```bash
iscan doctor
iscan doctor --json
```

Complete pairing/Trust on the Mac that runs iScan. The iPhone user will see the Trust prompt at the physical device:

```bash
iscan pair --wait 120
```

## NetworkUSB integration

Start `usbmuxd-bridge` on the Mac running iScan and point iScan at the socket it creates:

```bash
usbmuxd-bridge --agent-host 100.x.y.z --socket-path "$HOME/Library/Application Support/networkusb/usbmuxd.sock"

# Canonical pymobiledevice3 form: a bare UNIX path, not unix:/path.
export USBMUXD_SOCKET_ADDRESS="$HOME/Library/Application Support/networkusb/usbmuxd.sock"
iscan doctor
iscan report --open
```

For compatibility, iScan also accepts `unix:/path`, `unix:///path`, `tcp:host:port` and `host:port` through `--usbmux-address`/`--socket-path`. The normalized bare path is passed to `pymobiledevice3`; both `USBMUXD_SOCKET_ADDRESS` and `PYMOBILEDEVICE3_USBMUX` are exported for subprocesses. CLI options take precedence over environment variables.

If NetworkUSB writes `~/.cache/networkusb/active.json`, iScan may discover it when no address option or environment variable is set. The file is only a hint: stale entries and non-socket paths are ignored, and it must never contain a token.

```bash
iscan report --usbmux-address /tmp/usbmuxd.sock --json-progress
iscan report --json   # HTML + .json sidecar
```

The machine-readable output is one JSON object per line and is safe for a supervisor to consume without parsing human text:

```json
{"event":"start","command":"report","transport":{"kind":"unix"}}
{"event":"connected","name":"iPhone"}
{"event":"service","name":"battery","state":"complete","ok":true}
{"event":"saved","path":"/absolute/path/iscan_report.html","partial":false}
```

`report --json-progress` keeps JSON on stdout and avoids Rich/progress text. Human-readable output continues to include the stable line `Report saved: <absolute path>` for older NetworkUSB menu-bar builds.

### Pairing model

NetworkUSB is a transparent usbmuxd tunnel. Pair records and the HostID belong to the Mac running iScan, not to the Mac physically holding the iPhone. Therefore:

1. Start the NetworkUSB agent and bridge.
2. Run `iscan doctor` on the master.
3. At the first `iscan pair --wait`, ask the store operator to tap **Trust** on the iPhone.
4. Run reports from the master thereafter.

Do not copy pair records from the agent: that is a different host identity.

### Exit codes

| Code | Meaning |
|---:|---|
| 0 | Report was written successfully |
| 2 | No device was visible |
| 3 | Device is not paired / Trust was not completed |
| 4 | usbmuxd or NetworkUSB transport is unavailable |
| 5 | Report collection or writing failed |

## Data and privacy

Reports contain identifiers such as UDID, serial number and IMEI because they are diagnostic data. Keep generated HTML files private. iScan does not put tokens in reports or progress events, and it never claims that a component is original merely because a serial number was readable.

## Related project

**[NetworkUSB](https://github.com/chumafox/NetworkUSB)** is the async TCP/TLS usbmuxd tunnel used for remote devices:

```text
iPhone ── USB ── [shop Mac: usbmuxd-agent] ── TCP/TLS ── [master Mac: usbmuxd-bridge] ── UNIX ── iScan
```

The cross-project audit and the remaining NetworkUSB-side hardening items are documented in [`AUDIT.md`](AUDIT.md). iScan implements the transport, timeout and CLI portions of that contract; NetworkUSB must keep its local socket private/stable and pass the same canonical path to its supervisor.
