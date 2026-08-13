# iScan

![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)

**iScan** is an iOS device diagnostics CLI that generates detailed and beautiful HTML reports. It acts as an open-source, CLI-based alternative to tools like 3uTools for macOS and Linux.

## Features

- Scans connected iOS devices over USB.
- Generates detailed HTML diagnostic reports (with dark mode and print support).
- Extracts device info, storage usage, battery health and cycle count.
- Checks components (serial numbers for MLB, cameras, display, biometric).
- Supports English and Russian reports.

> **Note for iOS 17+**: You must run the tunnel first in a separate terminal:
> `sudo pymobiledevice3 remote start-tunnel`

## Installation

Using `uv tool` (recommended):

```bash
uv tool install ./
```

Or using `pipx`:

```bash
pipx install ./
```

## Usage

Generate an HTML report and open it in your browser:
```bash
iscan report --open
```

Show key info in the terminal:
```bash
iscan info
```

List all connected devices:
```bash
iscan list
```

Show version:
```bash
iscan version
```

## Related projects

**iScan** is built to work in pair with **[NetworkUSB](https://github.com/chumafox/NetworkUSB)** — an async usbmuxd network tunnel. NetworkUSB exposes a remotely-connected iPhone to this machine as a local device, so you can run `iscan report` against an iPhone that is physically attached to another Mac (e.g. a client's machine in a store) as if it were plugged into your own:

```
iPhone ── USB ── [client Mac: usbmuxd-agent] ──TCP/TLS── [your Mac: usbmuxd-bridge] ── /tmp/usbmuxd.sock ── iScan
```

See also: [chumafox/NetworkUSB — async usbmuxd tunnel](https://github.com/chumafox/NetworkUSB)
