# Windows Receiver GUI Design

**Date:** 2026-07-26  
**Status:** Approved  
**Scope:** Replace the Windows CLI as the primary user-facing receiver with a single-window desktop UI.

## Goal

Let a non-technical Windows user configure and run the Mobile Mic Bridge receiver without opening a terminal: pick an output device, set a password, start listening, pair via QR or mDNS, and see connection / level / buffer status.

Success criteria:

1. Double-click a GUI EXE → select device → set password → start → phone pairs (QR or discovery) → live level and connection state → close window to stop and exit.
2. Settings restore on next launch (including password).
3. Existing wire protocol and mobile app require no changes.
4. Existing unit tests keep passing; CI can build a windowed (no-console) Windows EXE.

## Non-goals (v1)

- System tray, minimize-to-tray, autostart
- Hot-swap of output device / port / token while running
- Multi-client, TLS, Opus, or public-internet mode
- Full i18n framework (v1 UI labels are Chinese only)
- Replacing or implementing the placeholder Rust `Cargo.toml` receiver
- Heavy GUI automation tests

## Context

Today `windows_receiver` is a Python package:

- CLI entry: `mobile_mic_receiver.cli:main` / `main.py`
- Core: `MicServer`, `AudioBuffer`, `AudioOutput`, `MdnsAdvertiser`, pairing QR (ASCII in terminal)
- Release: PyInstaller one-file EXE for x64 and ARM64

The GUI fully replaces the CLI for end users. The CLI remains for developers and scripts.

## Approach

**CustomTkinter single window on top of the existing Python receiver.**

Rationale:

- Reuses audio, WebSocket, mDNS, and pairing code
- Fits current PyInstaller release path with `--noconsole`
- Modern enough look without Qt’s weight or pure-tkinter’s dated defaults

Rejected alternatives:

- **PyQt6 / PySide6** — stronger toolkit, heavier deps and packaging
- **Plain tkinter** — zero extra UI dep, weaker look and more manual widgets
- **Flutter Windows / Tauri** — new stack; duplicates or rewrites receiver logic

## Architecture

```text
GUI main thread (CustomTkinter)
  ├── settings.json load/save
  ├── form + QR + meters + start/stop
  └── polls ReceiverController snapshots via after()

ReceiverController (new, background worker thread)
  ├── asyncio MicServer
  ├── AudioBuffer + AudioOutput
  ├── MdnsAdvertiser (optional)
  └── thread-safe status: running, connection, buffer stats, peak level

Existing modules (reused, lightly extended)
  MicServer, AudioBuffer, AudioOutput, discovery, pairing
```

### Threading

| Thread | Responsibility |
| --- | --- |
| UI (main) | CustomTkinter event loop only |
| Worker | `asyncio` server + controller lifecycle |
| sounddevice callback | Pull PCM from `AudioBuffer`; may update a lock-guarded peak sample |

UI must not be touched from audio or asyncio threads. Controller exposes a snapshot (lock or queue); the window uses `widget.after(...)` to poll ~10–20 Hz for meters and coarser for status text.

Closing the window always stops the controller then exits the process (no tray).

## UI layout and interaction

Single ordinary application window:

```text
┌─────────────────────────────────────────────┐
│  Mobile Mic Bridge                          │
│  Status: Idle / Waiting / Connected / Error │
├──────────────────────┬──────────────────────┤
│  Settings            │  Pairing             │
│  Output device [▼] ↻ │  [QR image]          │
│  Port                │  Local IPv4 list     │
│  Password  [•••] 👁  │  Pairing URI copy    │
│  ── Advanced ──────  │                      │
│  Latency ms          │                      │
│  Prebuffer ms        │                      │
│  ☑ mDNS discovery    │                      │
├──────────────────────┴──────────────────────┤
│  Level ████░░░░  Buffer N ms  Underflows N  │
├─────────────────────────────────────────────┤
│           [ Start ]  /  [ Stop ]            │
└─────────────────────────────────────────────┘
```

### Behavior

- **Idle / stopped:** all settings editable; Start enabled when port and buffer values are valid.
- **Running:** device, port, token, latency, prebuffer, and discovery are locked. Stop enabled.
- **Start:** validate inputs → open audio output → start WebSocket server → optional mDNS → show QR for first local IPv4 (or hide QR with a warning if none).
- **Connected:** status shows connected; prefer hello `device` string and remote address when available.
- **Disconnect:** return to Waiting without stopping the server.
- **Level meter:** peak from recent PCM (or silence when not streaming); refresh ~10–20 Hz.
- **Buffer row:** from `AudioBuffer.stats()` — queued duration, underflows, buffering flag.
- **Device list:** enumerated at open; refresh button re-queries `list_output_devices()`.
- **Password:** show/hide toggle; empty token allowed with a non-blocking warning (same spirit as CLI).
- **Close (X):** if running, stop cleanly; then exit.

No tray. No run-in-background after close.

## Settings persistence

- Path: `%APPDATA%\MobileMicBridge\settings.json`, resolved with `Path(os.environ.get('APPDATA', Path.home())) / 'MobileMicBridge' / 'settings.json'` (no extra dependency).
- Fields:
  - `device_name` (string; preferred over index because indices drift)
  - `port` (int, default 8765)
  - `token` (string; user chose full remember including password)
  - `latency_ms` (int, default 400)
  - `prebuffer_ms` (int, default 80)
  - `discovery_enabled` (bool, default true)
  - optional `window_geometry`
- Load on startup; invalid values fall back to defaults with a status warning.
- Save on change (debounced) and on clean shutdown.
- Device restore: match by name; if missing, fall back to default output or first device and warn.

## Module changes

### New

| Module | Role |
| --- | --- |
| `mobile_mic_receiver/settings.py` | Load/save settings dataclass ↔ JSON |
| `mobile_mic_receiver/controller.py` | Start/stop lifecycle, status aggregation, peak tracking |
| `mobile_mic_receiver/gui/` (package) | App window, widgets, main entry |
| GUI entry script | e.g. `gui_main.py` or `mobile_mic_receiver.gui:main` for PyInstaller |

### Existing (minimal extensions)

| Module | Change |
| --- | --- |
| `server.py` | Optional status callbacks: waiting / connected / disconnected / rejected. CLI may keep prints; GUI uses callbacks only. Pass through hello `device` when present. |
| `pairing.py` | Add `make_qr_image(host, port, token)` returning an image (PIL) suitable for Tk; keep `print_pairing_qr` for CLI. |
| `buffer.py` | Keep `stats()`; peak may live in controller on the write path or a small hook—prefer not bloating buffer if controller can observe writes. |
| `audio.py` | Unchanged unless device-open errors need clearer messages. |
| `cli.py` | Unchanged behavior; remains the console entry. |
| `pyproject.toml` | Add `customtkinter` and `Pillow`; keep `qrcode` (image path uses PIL). Add GUI entry script `mobile-mic-receiver-gui`. |

### ReceiverController sketch

Responsibilities:

- `start(config)` / `stop()` — idempotent stop
- Own worker thread running asyncio loop for `MicServer.run()`
- Construct `AudioBuffer` + `AudioOutput` context for the session
- Start/stop `MdnsAdvertiser` per config
- Expose `snapshot()` → running, status enum, client label, `BufferStats`, peak (0.0–1.0), last error, local addresses, pairing URI
- On audio path or buffer write, update peak with simple decay for the meter

Server must become stoppable: today `MicServer.run()` awaits an eternal `Future`. Controller needs a cooperative shutdown (e.g. cancel the serve task / close the server) so Stop and window-close work without killing the process harshly.

## Error handling

| Case | UI behavior |
| --- | --- |
| Invalid port / prebuffer > latency | Inline validation; Start disabled or Start shows error |
| Port in use | Error status; stay stopped |
| Invalid / missing output device | Error status; user refreshes or picks another |
| mDNS failure | Warning only; receiver still runs |
| QR / no IPv4 | Warning; show manual address instructions if any |
| Audio device lost while running | Stop output, error status, allow reconfigure and restart |
| Rejected client (bad token, busy) | Optional transient message; server keeps waiting |

## Testing

- Keep existing pytest for buffer, server, pairing.
- Add:
  - settings round-trip and invalid fallback
  - `make_qr_image` produces a non-empty image
  - MicServer callback sequence (connect / reject / disconnect) with fakes
  - Controller start/stop and snapshot with mocked server/audio where practical
- GUI: manual checklist (start, pair, level, advanced fields, restart persistence, close-while-running). No Selenium-style UI suite in v1.

## Release and docs

- Dependencies: `customtkinter`, Pillow (for QR image), existing `sounddevice` / `websockets` / `zeroconf` / `qrcode`.
- PyInstaller GUI build: windowed entry, `--noconsole`, `--onefile`, collect CustomTkinter assets + sounddevice + zeroconf + qrcode.
- CI `release.yml`: build the GUI EXE for x64 and ARM64 as `mobile-mic-receiver-windows-<arch>.exe` (replaces the console one-file as the published Windows artifact; CLI remains installable from source via `pip install -e .`).
- README (EN + ZH): primary path becomes “download EXE and run”; CLI install remains under Development.
- Console script `mobile-mic-receiver` stays for devs; GUI script is `mobile-mic-receiver-gui`.

## Open implementation notes (resolved in design)

- **Password stored in plain JSON under APPDATA:** accepted for v1 per product choice (full remember). Document that this is local convenience, not a vault.
- **Stop server cleanly:** required; implement cooperative shutdown in `MicServer` or wrapper.
- **Device identity:** store name, not only index.
- **Language:** Chinese UI labels in v1 (aligned with the mobile app’s primary UX copy); no i18n framework.

## Implementation order (high level)

1. Make `MicServer` stoppable + status callbacks; extend pairing image helper; tests.
2. `settings.py` + tests.
3. `ReceiverController` + tests with fakes.
4. CustomTkinter window wired to controller.
5. PyInstaller / CI / README updates.
6. Manual end-to-end on Windows with phone app.
