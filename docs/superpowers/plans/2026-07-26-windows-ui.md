# Windows Receiver GUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a CustomTkinter Windows receiver UI that fully replaces the CLI for end users: configure device/port/token/buffers, start/stop, show QR + status + level, and persist settings.

**Architecture:** Keep core audio/WebSocket/mDNS in existing modules. Add cooperative stop + status events on `MicServer`, a `ReceiverController` that owns a worker thread and exposes thread-safe snapshots, and a CustomTkinter window that polls those snapshots. Settings live in `%APPDATA%\MobileMicBridge\settings.json`.

**Tech Stack:** Python 3.10+, CustomTkinter, Pillow, qrcode, sounddevice, websockets, zeroconf, pytest, PyInstaller.

## Global Constraints

- Wire protocol unchanged (`docs/protocol.md`); mobile app unchanged.
- UI labels Chinese only in v1.
- No system tray; closing the window stops the receiver and exits.
- Settings include password in plain JSON under APPDATA (product choice).
- CLI entry `mobile-mic-receiver` remains; GUI entry is `mobile-mic-receiver-gui`.
- Published Windows EXE is the GUI build (`--noconsole`).
- Work only under `windows_receiver/` plus root docs/CI as listed; do not implement Rust receiver.
- Prefer TDD: failing test → implement → pass → commit per task.

## File Structure

| Path | Responsibility |
| --- | --- |
| `mobile_mic_receiver/server.py` | Stoppable `MicServer` + optional status events |
| `mobile_mic_receiver/pairing.py` | Add PIL QR image helper; keep ASCII CLI QR |
| `mobile_mic_receiver/settings.py` | **New** settings dataclass load/save |
| `mobile_mic_receiver/controller.py` | **New** lifecycle, peak meter, snapshot |
| `mobile_mic_receiver/gui/__init__.py` | **New** package |
| `mobile_mic_receiver/gui/app.py` | **New** CustomTkinter main window |
| `gui_main.py` | **New** PyInstaller / script entry |
| `pyproject.toml` | Deps + GUI script |
| `tests/test_server_events.py` | **New** stop + event tests |
| `tests/test_pairing.py` | Extend QR image test |
| `tests/test_settings.py` | **New** |
| `tests/test_controller.py` | **New** |
| `.github/workflows/release.yml` | GUI PyInstaller flags |
| `README.md`, `README.zh-CN.md` | GUI-first quick start |

---

### Task 1: Stoppable MicServer + status events

**Files:**
- Modify: `windows_receiver/mobile_mic_receiver/server.py`
- Create: `windows_receiver/tests/test_server_events.py`
- Keep existing: `windows_receiver/tests/test_server.py` green

**Interfaces:**
- Produces:
  - `ServerEvent` dataclass: `kind: str`, `message: str = ''`, `device: str = ''`, `remote: str = ''`
  - `kind` values: `'waiting' | 'connected' | 'disconnected' | 'rejected'`
  - `MicServer.__init__(config, buffer, on_event: Callable[[ServerEvent], None] | None = None)`
  - `MicServer.request_stop() -> None` — thread-safe; no-op if not running
  - `async MicServer.run() -> None` — serves until `request_stop()`; emits `waiting` when ready

- [ ] **Step 1: Write the failing tests**

Create `windows_receiver/tests/test_server_events.py`:

```python
import asyncio
import json
from dataclasses import dataclass, field

import pytest

pytest.importorskip('websockets')

from websockets.asyncio.client import connect

from mobile_mic_receiver.buffer import AudioBuffer
from mobile_mic_receiver.server import MicServer, ServerConfig, ServerEvent


@dataclass
class EventLog:
    events: list[ServerEvent] = field(default_factory=list)

    def __call__(self, event: ServerEvent) -> None:
        self.events.append(event)


def _hello(token: str = 'secret', device: str = 'test-phone') -> str:
    return json.dumps(
        {
            'type': 'hello',
            'version': 1,
            'sampleRate': 48000,
            'channels': 1,
            'format': 'pcm_s16le',
            'token': token,
            'device': device,
        }
    )


def test_run_emits_waiting_and_stops_on_request() -> None:
    async def scenario() -> None:
        log = EventLog()
        buffer = AudioBuffer(sample_rate=48000, channels=1)
        server = MicServer(
            ServerConfig(host='127.0.0.1', port=0, token='secret'),
            buffer,
            on_event=log,
        )
        task = asyncio.create_task(server.run())
        for _ in range(50):
            if any(e.kind == 'waiting' for e in log.events):
                break
            await asyncio.sleep(0.02)
        assert any(e.kind == 'waiting' for e in log.events)
        server.request_stop()
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())


def test_connect_disconnect_events_include_device() -> None:
    async def scenario() -> None:
        log = EventLog()
        buffer = AudioBuffer(sample_rate=48000, channels=1, prebuffer_ms=1)
        server = MicServer(
            ServerConfig(host='127.0.0.1', port=0, token='secret'),
            buffer,
            on_event=log,
        )
        task = asyncio.create_task(server.run())
        # Wait until server bound — port 0 needs actual port from server internals.
        # Implementation must expose bound port OR tests use fixed free port.
        # Use fixed port helper:
        await asyncio.sleep(0.05)
        # Prefer: server.bound_port property set after serve starts
        port = server.bound_port
        assert port is not None
        async with connect(f'ws://127.0.0.1:{port}/mic') as ws:
            await ws.send(_hello(device='Pixel'))
            ready = json.loads(await ws.recv())
            assert ready['type'] == 'ready'
            for _ in range(50):
                if any(e.kind == 'connected' for e in log.events):
                    break
                await asyncio.sleep(0.02)
        for _ in range(50):
            if any(e.kind == 'disconnected' for e in log.events):
                break
            await asyncio.sleep(0.02)
        connected = next(e for e in log.events if e.kind == 'connected')
        assert connected.device == 'Pixel'
        assert any(e.kind == 'disconnected' for e in log.events)
        server.request_stop()
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())


def test_rejected_event_on_bad_token() -> None:
    async def scenario() -> None:
        log = EventLog()
        buffer = AudioBuffer(sample_rate=48000, channels=1)
        server = MicServer(
            ServerConfig(host='127.0.0.1', port=0, token='secret'),
            buffer,
            on_event=log,
        )
        task = asyncio.create_task(server.run())
        for _ in range(50):
            if server.bound_port is not None:
                break
            await asyncio.sleep(0.02)
        port = server.bound_port
        assert port is not None
        async with connect(f'ws://127.0.0.1:{port}/mic') as ws:
            await ws.send(_hello(token='wrong'))
            try:
                await ws.recv()
            except Exception:
                pass
        for _ in range(50):
            if any(e.kind == 'rejected' for e in log.events):
                break
            await asyncio.sleep(0.02)
        assert any(e.kind == 'rejected' for e in log.events)
        server.request_stop()
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())
```

Note for implementer: `ServerConfig.port = 0` requires `MicServer.bound_port: int | None` updated when the websocket server starts (read from `websockets` server sockets). If port `0` is awkward with the library, bind an ephemeral port via `socket` first and pass that port into `ServerConfig`.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
cd windows_receiver
python -m pytest tests/test_server_events.py -v
```

Expected: FAIL (import/`ServerEvent`/API missing).

- [ ] **Step 3: Implement server extensions**

Update `server.py`:

```python
from dataclasses import dataclass
from typing import Callable

@dataclass(frozen=True)
class ServerEvent:
    kind: str
    message: str = ''
    device: str = ''
    remote: str = ''


class MicServer:
    def __init__(
        self,
        config: ServerConfig,
        buffer: AudioBuffer,
        on_event: Callable[[ServerEvent], None] | None = None,
    ) -> None:
        self._config = config
        self._buffer = buffer
        self._on_event = on_event or (lambda _event: None)
        self._client_lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self.bound_port: int | None = None

    def _emit(self, kind: str, **kwargs: str) -> None:
        self._on_event(ServerEvent(kind=kind, **kwargs))

    def request_stop(self) -> None:
        loop = self._loop
        stop_event = self._stop_event
        if loop is None or stop_event is None:
            return
        loop.call_soon_threadsafe(stop_event.set)

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        async with serve(
            self.handler,
            self._config.host,
            self._config.port,
            max_size=256 * 1024,
            max_queue=8,
            ping_interval=20,
            ping_timeout=20,
        ) as ws_server:
            # Resolve actual port (supports port 0)
            sockets = getattr(ws_server, 'sockets', None) or []
            if sockets:
                self.bound_port = int(sockets[0].getsockname()[1])
            else:
                self.bound_port = self._config.port
            self._emit('waiting')
            await self._stop_event.wait()
        self.bound_port = None
```

In `handler`, after successful hello:

```python
device = str(hello.get('device', ''))  # keep device from validated hello
# _validate_hello currently returns bool only — change it to return
# tuple[bool, str] (ok, device) OR stash device on validation.
self._emit(
    'connected',
    device=device,
    remote=str(websocket.remote_address),
)
```

On disconnect in `finally`:

```python
self._emit('disconnected')
```

In `_send_error` (or after failed validation / busy / bad path):

```python
self._emit('rejected', message=message)
```

Keep existing `print` calls in CLI-compatible paths **or** leave prints only in `cli.py` by removing server prints and printing from CLI via events later. Minimal change: keep the existing `print` lines so CLI behavior stays obvious; GUI ignores them under `--noconsole`.

Refactor `_validate_hello` to return `tuple[bool, str]` `(ok, device_name)` so connected events can include `device`.

- [ ] **Step 4: Run full server tests**

```powershell
cd windows_receiver
python -m pytest tests/test_server.py tests/test_server_events.py -v
```

Expected: PASS. Fix any existing tests broken by `_validate_hello` signature change.

- [ ] **Step 5: Commit**

```bash
git add windows_receiver/mobile_mic_receiver/server.py windows_receiver/tests/test_server_events.py windows_receiver/tests/test_server.py
git commit -m "feat(receiver): add stoppable server status events"
```

---

### Task 2: Pairing QR image helper

**Files:**
- Modify: `windows_receiver/mobile_mic_receiver/pairing.py`
- Modify: `windows_receiver/tests/test_pairing.py`
- Modify: `windows_receiver/pyproject.toml` (add `Pillow` if not pulled in)

**Interfaces:**
- Consumes: `build_pairing_uri(host, port, token)`
- Produces: `make_qr_image(*, host: str, port: int, token: str, box_size: int = 6) -> Image.Image` (PIL)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pairing.py`:

```python
def test_make_qr_image_is_non_empty() -> None:
    from mobile_mic_receiver.pairing import make_qr_image

    image = make_qr_image(host='192.168.1.20', port=8765, token='secret')
    assert image.size[0] > 0
    assert image.size[1] > 0
    # monochrome QR should not be fully white
    extrema = image.convert('L').getextrema()
    assert extrema[0] < extrema[1]
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
cd windows_receiver
python -m pytest tests/test_pairing.py::test_make_qr_image_is_non_empty -v
```

Expected: FAIL (`make_qr_image` missing).

- [ ] **Step 3: Implement**

In `pairing.py`:

```python
def make_qr_image(
    *, host: str, port: int, token: str, box_size: int = 6
):
    import qrcode
    from PIL import Image

    pairing_uri = build_pairing_uri(host=host, port=port, token=token)
    code = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=2,
    )
    code.add_data(pairing_uri)
    code.make(fit=True)
    image = code.make_image(fill_color='black', back_color='white')
    if not isinstance(image, Image.Image):
        image = image.get_image()
    return image.convert('RGB')
```

Add dependency in `pyproject.toml`:

```toml
dependencies = [
  'sounddevice==0.5.5',
  'websockets==16.1.1',
  'zeroconf==0.150.0',
  'qrcode==8.2',
  'Pillow>=10.0',
]
```

- [ ] **Step 4: Run tests**

```powershell
cd windows_receiver
python -m pip install -e .[test]
python -m pytest tests/test_pairing.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add windows_receiver/mobile_mic_receiver/pairing.py windows_receiver/tests/test_pairing.py windows_receiver/pyproject.toml
git commit -m "feat(receiver): generate pairing QR images for GUI"
```

---

### Task 3: Settings load/save

**Files:**
- Create: `windows_receiver/mobile_mic_receiver/settings.py`
- Create: `windows_receiver/tests/test_settings.py`

**Interfaces:**
- Produces:
  - `@dataclass ReceiverSettings` with fields:
    - `device_name: str = ''`
    - `port: int = 8765`
    - `token: str = ''`
    - `latency_ms: int = 400`
    - `prebuffer_ms: int = 80`
    - `discovery_enabled: bool = True`
    - `window_geometry: str = ''`
  - `default_settings_path() -> Path` → `Path(os.environ.get('APPDATA', str(Path.home()))) / 'MobileMicBridge' / 'settings.json'`
  - `load_settings(path: Path | None = None) -> ReceiverSettings`
  - `save_settings(settings: ReceiverSettings, path: Path | None = None) -> None`
  - Invalid JSON / types / ranges fall back field-by-field to defaults (do not raise for corrupt files)

Validation rules (same spirit as CLI):

- `port` in `1..65535` else default
- `latency_ms > 0` else default
- `prebuffer_ms > 0` else default
- if `prebuffer_ms > latency_ms`, set `prebuffer_ms = min(default prebuffer, latency_ms)` or clamp prebuffer to latency

- [ ] **Step 1: Write failing tests**

`tests/test_settings.py`:

```python
from pathlib import Path

from mobile_mic_receiver.settings import (
    ReceiverSettings,
    load_settings,
    save_settings,
)


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / 'settings.json'
    original = ReceiverSettings(
        device_name='CABLE Input',
        port=9000,
        token='s3cret',
        latency_ms=300,
        prebuffer_ms=60,
        discovery_enabled=False,
        window_geometry='900x600+10+10',
    )
    save_settings(original, path)
    loaded = load_settings(path)
    assert loaded == original


def test_corrupt_file_returns_defaults(tmp_path: Path) -> None:
    path = tmp_path / 'settings.json'
    path.write_text('{not json', encoding='utf-8')
    loaded = load_settings(path)
    assert loaded == ReceiverSettings()


def test_invalid_port_falls_back(tmp_path: Path) -> None:
    path = tmp_path / 'settings.json'
    path.write_text('{"port": 99999, "token": "x"}', encoding='utf-8')
    loaded = load_settings(path)
    assert loaded.port == 8765
    assert loaded.token == 'x'


def test_prebuffer_cannot_exceed_latency(tmp_path: Path) -> None:
    path = tmp_path / 'settings.json'
    path.write_text(
        '{"latency_ms": 50, "prebuffer_ms": 200}', encoding='utf-8'
    )
    loaded = load_settings(path)
    assert loaded.latency_ms == 50
    assert loaded.prebuffer_ms <= loaded.latency_ms
```

- [ ] **Step 2: Run tests — expect FAIL**

```powershell
cd windows_receiver
python -m pytest tests/test_settings.py -v
```

- [ ] **Step 3: Implement `settings.py`**

```python
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class ReceiverSettings:
    device_name: str = ''
    port: int = 8765
    token: str = ''
    latency_ms: int = 400
    prebuffer_ms: int = 80
    discovery_enabled: bool = True
    window_geometry: str = ''


def default_settings_path() -> Path:
    appdata = os.environ.get('APPDATA')
    root = Path(appdata) if appdata else Path.home()
    return root / 'MobileMicBridge' / 'settings.json'


def load_settings(path: Path | None = None) -> ReceiverSettings:
    target = path or default_settings_path()
    defaults = ReceiverSettings()
    try:
        raw = json.loads(target.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return defaults
    if not isinstance(raw, dict):
        return defaults
    return _normalize(raw, defaults)


def save_settings(settings: ReceiverSettings, path: Path | None = None) -> None:
    target = path or default_settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(asdict(settings), indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )


def _normalize(raw: dict, defaults: ReceiverSettings) -> ReceiverSettings:
    port = raw.get('port', defaults.port)
    try:
        port_i = int(port)
    except (TypeError, ValueError):
        port_i = defaults.port
    if not 1 <= port_i <= 65535:
        port_i = defaults.port

    def positive_int(key: str, default: int) -> int:
        try:
            value = int(raw.get(key, default))
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    latency = positive_int('latency_ms', defaults.latency_ms)
    prebuffer = positive_int('prebuffer_ms', defaults.prebuffer_ms)
    if prebuffer > latency:
        prebuffer = min(defaults.prebuffer_ms, latency)

    return ReceiverSettings(
        device_name=str(raw.get('device_name', defaults.device_name) or ''),
        port=port_i,
        token=str(raw.get('token', defaults.token) or ''),
        latency_ms=latency,
        prebuffer_ms=prebuffer,
        discovery_enabled=bool(
            raw.get('discovery_enabled', defaults.discovery_enabled)
        ),
        window_geometry=str(
            raw.get('window_geometry', defaults.window_geometry) or ''
        ),
    )
```

- [ ] **Step 4: Run tests — expect PASS**

```powershell
cd windows_receiver
python -m pytest tests/test_settings.py -v
```

- [ ] **Step 5: Commit**

```bash
git add windows_receiver/mobile_mic_receiver/settings.py windows_receiver/tests/test_settings.py
git commit -m "feat(receiver): persist GUI receiver settings"
```

---

### Task 4: ReceiverController

**Files:**
- Create: `windows_receiver/mobile_mic_receiver/controller.py`
- Create: `windows_receiver/tests/test_controller.py`

**Interfaces:**
- Consumes: `MicServer`, `ServerConfig`, `ServerEvent`, `AudioBuffer`, `AudioOutput`, `MdnsAdvertiser`, `local_ipv4_addresses`, `build_pairing_uri`, `make_qr_image` (image optional at controller layer)
- Produces:
  - `@dataclass(frozen=True) ControllerConfig`:
    - `device: int | str | None`
    - `host: str = '0.0.0.0'`
    - `port: int = 8765`
    - `token: str = ''`
    - `latency_ms: int = 400`
    - `prebuffer_ms: int = 80`
    - `discovery_enabled: bool = True`
  - `@dataclass(frozen=True) ControllerSnapshot`:
    - `running: bool`
    - `status: str`  # `stopped|starting|waiting|connected|error`
    - `client_label: str`
    - `last_error: str`
    - `warning: str`
    - `peak: float`  # 0.0..1.0
    - `queued_ms: float`
    - `underflows: int`
    - `buffering: bool`
    - `local_addresses: tuple[str, ...]`
    - `pairing_uri: str`
    - `bound_port: int | None`
  - `class ReceiverController`:
    - `start(config: ControllerConfig) -> None` — raises `RuntimeError` if already running; starts worker thread
    - `stop() -> None` — idempotent
    - `snapshot() -> ControllerSnapshot` — thread-safe
    - `is_running() -> bool`

Peak tracking: on each binary write path, compute max abs int16 / 32768 and store under lock with exponential decay when reading snapshot (e.g. `peak = max(new, peak * 0.85)`).

Implementation approach for observing writes without forking server logic: wrap buffer:

```python
class _PeakBuffer:
    def __init__(self, inner: AudioBuffer, peak_holder: list[float], lock):
        self._inner = inner
        ...
    def write(self, data: bytes) -> None:
        # update peak from data
        self._inner.write(data)
    def read(self, frames: int) -> bytes:
        return self._inner.read(frames)
    def clear(self) -> None:
        self._inner.clear()
    def stats(self):
        return self._inner.stats()
```

Worker thread outline:

```python
def _thread_main(self, config: ControllerConfig) -> None:
    try:
        buffer = AudioBuffer(...)
        peak_buffer = _PeakBuffer(buffer, ...)
        advertiser = MdnsAdvertiser(port=config.port)
        # start advertiser if enabled (catch warn)
        with AudioOutput(peak_buffer, device=config.device, ...):
            server = MicServer(ServerConfig(...), peak_buffer, on_event=self._on_event)
            self._server = server
            asyncio.run(server.run())
    except Exception as exc:
        self._set_error(str(exc))
    finally:
        advertiser.close()
        self._mark_stopped()
```

`stop()` calls `self._server.request_stop()` and joins thread with timeout (e.g. 3s).

- [ ] **Step 1: Write failing tests**

`tests/test_controller.py` — use real server on localhost but **mock AudioOutput** so CI machines without special devices still pass:

```python
import time
from unittest.mock import patch

from mobile_mic_receiver.controller import ControllerConfig, ReceiverController


class DummyAudio:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None


def test_start_stop_reaches_waiting() -> None:
    controller = ReceiverController()
    with patch('mobile_mic_receiver.controller.AudioOutput', DummyAudio), patch(
        'mobile_mic_receiver.controller.MdnsAdvertiser'
    ) as adv:
        adv.return_value.start.return_value = None
        adv.return_value.close.return_value = None
        controller.start(
            ControllerConfig(device=None, host='127.0.0.1', port=18765, token='t')
        )
        deadline = time.time() + 3
        while time.time() < deadline:
            snap = controller.snapshot()
            if snap.status in {'waiting', 'connected'}:
                break
            time.sleep(0.05)
        assert controller.snapshot().running is True
        assert controller.snapshot().status == 'waiting'
        controller.stop()
        assert controller.snapshot().running is False
        assert controller.snapshot().status == 'stopped'


def test_stop_is_idempotent() -> None:
    controller = ReceiverController()
    controller.stop()
    controller.stop()
```

Pick a high fixed test port (`18765`) to avoid clashing with a running receiver; if bind fails, test should fail clearly.

- [ ] **Step 2: Run tests — expect FAIL**

```powershell
cd windows_receiver
python -m pytest tests/test_controller.py -v
```

- [ ] **Step 3: Implement `controller.py`**

Implement full module with:

- locks for snapshot fields
- `_on_event` mapping `ServerEvent` → status/client_label
- `queued_ms` from `stats.queued_bytes / (48000 * 1 * 2) * 1000`
- `local_addresses` from `local_ipv4_addresses()` at start
- `pairing_uri` from first address + port + token (empty string if no address)

- [ ] **Step 4: Run tests — expect PASS**

```powershell
cd windows_receiver
python -m pytest tests/test_controller.py tests/test_server_events.py -v
```

- [ ] **Step 5: Commit**

```bash
git add windows_receiver/mobile_mic_receiver/controller.py windows_receiver/tests/test_controller.py
git commit -m "feat(receiver): add GUI receiver controller"
```

---

### Task 5: CustomTkinter main window

**Files:**
- Create: `windows_receiver/mobile_mic_receiver/gui/__init__.py`
- Create: `windows_receiver/mobile_mic_receiver/gui/app.py`
- Create: `windows_receiver/gui_main.py`
- Modify: `windows_receiver/pyproject.toml` (add `customtkinter`, script entry)

**Interfaces:**
- Consumes: `ReceiverController`, `ControllerConfig`, `ControllerSnapshot`, `ReceiverSettings`, `load_settings`, `save_settings`, `list_output_devices`, `make_qr_image`, `build_pairing_uri`
- Produces: `mobile_mic_receiver.gui.app:run_app() -> None` and `gui_main.py` calling it

**UI requirements (Chinese labels):**

| Control | Label |
| --- | --- |
| Title | Mobile Mic Bridge |
| Status | 状态 |
| Device | 输出设备 |
| Refresh devices | 刷新 |
| Port | 端口 |
| Password | 连接密码 |
| Show password | 显示 |
| Advanced | 高级 |
| Latency | 延迟 (ms) |
| Prebuffer | 预缓冲 (ms) |
| Discovery | 启用 mDNS 自动发现 |
| Level | 电平 |
| Buffer | 缓冲 |
| Underflows | 欠载 |
| Start | 启动接收 |
| Stop | 停止 |
| Pairing | 配对 |
| Addresses | 本机地址 |
| Copy URI | 复制配对链接 |

Behavior:

- Load settings on open; select device by `device_name` if present in list
- Debounced save (500 ms) on field changes while stopped; always save on close
- Running → disable settings inputs; enable Stop
- Poll `controller.snapshot()` every 50 ms for peak/buffer; update status text when changed
- On Start: build `ControllerConfig` from form; resolve device name → index via current device list
- On successful waiting: render QR from `make_qr_image` into a `CTkLabel` / `ImageTk`
- Close protocol: `stop()` then `save_settings` then `destroy`

No automated GUI unit tests in this task — manual checklist in Step 4.

- [ ] **Step 1: Add dependency and empty entry**

`pyproject.toml`:

```toml
dependencies = [
  # existing...
  'Pillow>=10.0',
  'customtkinter>=5.2.0',
]

[project.scripts]
mobile-mic-receiver = 'mobile_mic_receiver.cli:main'
mobile-mic-receiver-gui = 'mobile_mic_receiver.gui.app:run_app'
```

`gui/__init__.py` can be empty or export `run_app`.

`gui_main.py`:

```python
from mobile_mic_receiver.gui.app import run_app

if __name__ == '__main__':
    run_app()
```

- [ ] **Step 2: Implement `gui/app.py`**

Structure:

```python
def run_app() -> None:
    import customtkinter as ctk
    ctk.set_appearance_mode('System')
    ctk.set_default_color_theme('blue')
    app = ReceiverApp()
    app.mainloop()


class ReceiverApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title('Mobile Mic Bridge')
        self.geometry('880x560')
        self._controller = ReceiverController()
        self._settings = load_settings()
        self._build_widgets()
        self._apply_settings(self._settings)
        self.protocol('WM_DELETE_WINDOW', self._on_close)
        self.after(50, self._tick)
```

Implement `_build_widgets`, `_tick`, `_start`, `_stop`, `_refresh_devices`, `_update_qr`, validation before start (`prebuffer <= latency`, port range). On validation failure set status error text and return.

Device combo values: `f'{index}: {name}'` display strings; store parallel list of `(index, name)`.

Peak meter: `CTkProgressBar` set to `snapshot.peak`.

- [ ] **Step 3: Install and smoke-import**

```powershell
cd windows_receiver
python -m pip install -e .[test]
python -c "from mobile_mic_receiver.gui.app import run_app; print('ok')"
```

Expected: prints `ok` (do not block on mainloop in CI).

- [ ] **Step 4: Manual checklist on Windows**

Run:

```powershell
cd windows_receiver
python gui_main.py
```

Verify:

1. Window opens with Chinese labels  
2. Device list populates; 刷新 works  
3. 启动接收 → status 等待连接; QR appears when IPv4 exists  
4. Phone can connect (or at least port listens)  
5. 停止 works; Start again works  
6. Restart app → settings restored including password  
7. Close while running → process exits cleanly  

- [ ] **Step 5: Run full unit suite**

```powershell
cd windows_receiver
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add windows_receiver/mobile_mic_receiver/gui windows_receiver/gui_main.py windows_receiver/pyproject.toml
git commit -m "feat(receiver): add CustomTkinter Windows GUI"
```

---

### Task 6: Release packaging and documentation

**Files:**
- Modify: `.github/workflows/release.yml`
- Modify: `.github/workflows/ci.yml` (if it installs receiver deps / tests — ensure new deps install)
- Modify: `README.md`
- Modify: `README.zh-CN.md`

**Interfaces:**
- Produces: windowed one-file EXE from `gui_main.py` named `mobile-mic-receiver-windows-<arch>.exe`

- [ ] **Step 1: Update release workflow Windows build step**

Replace the PyInstaller command with:

```yaml
- name: Build receiver executable
  run: >
    pyinstaller --onefile --noconsole
    --name mobile-mic-receiver-windows-${{ matrix.arch }}
    --collect-all sounddevice
    --collect-all zeroconf
    --collect-all qrcode
    --collect-all customtkinter
    --collect-all PIL
    gui_main.py
```

Ensure working-directory remains `windows_receiver`. Keep pytest step before build. Install still uses `pip install -e .[test] pyinstaller==...`.

- [ ] **Step 2: Update CI if needed**

If CI installs `windows_receiver` extras, confirm `customtkinter`/`Pillow` install and `pytest` still runs. No GUI launch in CI.

- [ ] **Step 3: Update README.zh-CN.md Quick Start (Windows)**

Primary path:

1. 安装虚拟音频线（如 VB-CABLE）  
2. 下载 release 中的 `mobile-mic-receiver-windows-x64.exe`（或 ARM64）  
3. 双击运行 → 选择输出设备（CABLE Input）→ 设置连接密码 → 启动接收  
4. 手机扫码或自动发现后开始传输  

Keep a short “开发者：命令行安装” section pointing at `pip install -e .` and `mobile-mic-receiver`.

Mirror the same structure in `README.md` (English).

Mention settings path: `%APPDATA%\MobileMicBridge\settings.json` and that the password is stored in plain text locally.

- [ ] **Step 4: Local PyInstaller smoke (optional but recommended on Windows)**

```powershell
cd windows_receiver
python -m pip install pyinstaller==6.21.0
pyinstaller --onefile --noconsole --name mobile-mic-receiver-gui-test --collect-all sounddevice --collect-all zeroconf --collect-all qrcode --collect-all customtkinter --collect-all PIL gui_main.py
.\dist\mobile-mic-receiver-gui-test.exe
```

Expected: window opens without a console.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/release.yml .github/workflows/ci.yml README.md README.zh-CN.md
git commit -m "build: ship windowed Windows GUI receiver EXE"
```

---

## Spec coverage checklist

| Spec requirement | Task |
| --- | --- |
| CustomTkinter single window | 5 |
| Completely replace CLI for end users | 5, 6 |
| Start/stop, device, port, token | 5 |
| Advanced latency/prebuffer/mDNS | 5 |
| Graphical QR + addresses | 2, 5 |
| Level + buffer/underflow meters | 4, 5 |
| Remember all settings including password | 3, 5 |
| Ordinary window; close stops | 5 |
| MicServer events + cooperative stop | 1 |
| Controller worker thread + snapshot | 4 |
| Tests for settings/QR/events/controller | 1–4 |
| PyInstaller --noconsole + CI | 6 |
| README GUI-first | 6 |
| Protocol/mobile unchanged | all (no protocol edits) |
| No tray / no hot-swap | 5 (not implemented) |

## Self-review notes

- No TBD placeholders left in tasks.
- `ServerEvent` / `ControllerSnapshot` / `ReceiverSettings` names are consistent across tasks.
- `bound_port` required for port-0 tests; if websockets version differs, use pre-bound ephemeral port in tests instead — both acceptable.
- Peak buffer wrapper must expose `write`/`read`/`clear`/`stats` used by server and audio.
- GUI has no automated tests by design; manual checklist is mandatory before claiming done.
