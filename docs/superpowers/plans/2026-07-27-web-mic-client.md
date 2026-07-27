# Web Mic Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a receiver-hosted browser microphone: same-port HTTP static page, HTTP QR pairing, PCM stream over existing `/mic`, with browser AEC/NS/AGC enabled by default.

**Architecture:** Extend the Windows Python receiver so `websockets` `process_request` serves a whitelist of static files from `mobile_mic_receiver/web_assets/` on port 8765 while `/mic` WebSocket stays unchanged. Pairing defaults to `http://host:port/?token=...`. The phone page uses `getUserMedia` + AudioWorklet (ScriptProcessor fallback), resamples to 48 kHz mono `pcm_s16le`, and speaks protocol v1.

**Tech Stack:** Python 3.10+, websockets 16.x, qrcode, Pillow, CustomTkinter, pytest, vanilla JS (AudioWorklet), PyInstaller.

## Global Constraints

- Wire protocol frame schema unchanged (`docs/protocol.md`); only document HTTP pairing URI and `web-*` device strings.
- Flutter app unchanged.
- One active `/mic` client at a time (existing lock).
- No second listen port; HTTP and WS share `8765`.
- Token never written to `localStorage` / cookies on the web page.
- Default QR mode is `web`; App QR remains available.
- v1 noise control = browser constraints only (no RNNoise).
- Background capture is best-effort; page must state that clearly.
- Prefer TDD on Python: failing test → implement → pass → commit per task.
- Work under `windows_receiver/`, root docs, and release workflow only.

## File Structure

| Path | Responsibility |
| --- | --- |
| `windows_receiver/mobile_mic_receiver/pairing.py` | Add `build_web_pairing_uri`; QR helpers accept `mode` |
| `windows_receiver/mobile_mic_receiver/static_http.py` | **New** path whitelist, load assets, build HTTP `Response` |
| `windows_receiver/mobile_mic_receiver/server.py` | Hook `process_request` for static GET; keep `/mic` WS |
| `windows_receiver/mobile_mic_receiver/web_assets/index.html` | **New** page shell |
| `windows_receiver/mobile_mic_receiver/web_assets/styles.css` | **New** mobile-friendly styles |
| `windows_receiver/mobile_mic_receiver/web_assets/app.js` | **New** mic session, WS, gain, toggles, resample/PCM |
| `windows_receiver/mobile_mic_receiver/web_assets/worklet.js` | **New** AudioWorklet capture processor |
| `windows_receiver/mobile_mic_receiver/controller.py` | Expose web + app pairing URIs; default snapshot URI is web |
| `windows_receiver/mobile_mic_receiver/cli.py` | `--qr-mode web\|app\|both` |
| `windows_receiver/mobile_mic_receiver/gui/app.py` | Default web QR; Web/App segmented control |
| `windows_receiver/pyproject.toml` | package-data for `web_assets/*` |
| `.github/workflows/release.yml` | PyInstaller `--add-data` for web assets |
| `windows_receiver/tests/test_pairing.py` | Web URI + QR mode tests |
| `windows_receiver/tests/test_static_http.py` | **New** |
| `windows_receiver/tests/test_server_http.py` | **New** same-port HTTP + WS |
| `windows_receiver/tests/test_controller.py` | Assert web pairing URI in snapshot |
| `docs/protocol.md`, `README.md`, `README.zh-CN.md` | Document web path |

---

### Task 1: Web pairing URI and QR mode

**Files:**
- Modify: `windows_receiver/mobile_mic_receiver/pairing.py`
- Modify: `windows_receiver/tests/test_pairing.py`

**Interfaces:**
- Produces:
  - `build_web_pairing_uri(*, host: str, port: int, token: str) -> str`
  - `build_pairing_uri(...)` unchanged (`mobilemic://...`)
  - `make_qr_image(*, host, port, token, box_size=6, mode: str = 'web')`
  - `print_pairing_qr(*, host, port, token, mode: str = 'web')` — `mode` in `web|app|both`
- Consumes: existing `qrcode` / Pillow usage

- [ ] **Step 1: Write the failing tests**

Append to `windows_receiver/tests/test_pairing.py`:

```python
from urllib.parse import parse_qs, urlparse

from mobile_mic_receiver.pairing import build_pairing_uri, build_web_pairing_uri


def test_web_pairing_uri_with_token() -> None:
    uri = urlparse(
        build_web_pairing_uri(host='192.168.1.20', port=8765, token='a b')
    )
    assert uri.scheme == 'http'
    assert uri.hostname == '192.168.1.20'
    assert uri.port == 8765
    assert uri.path in {'', '/'}
    assert parse_qs(uri.query) == {'token': ['a b']}


def test_web_pairing_uri_omits_empty_token() -> None:
    uri = build_web_pairing_uri(host='10.0.0.2', port=9000, token='')
    assert uri == 'http://10.0.0.2:9000/'
    assert 'token' not in uri


def test_app_pairing_uri_still_works() -> None:
    uri = urlparse(
        build_pairing_uri(host='192.168.1.20', port=8765, token='secret')
    )
    assert uri.scheme == 'mobilemic'


def test_make_qr_image_web_mode_non_empty() -> None:
    from mobile_mic_receiver.pairing import make_qr_image

    image = make_qr_image(
        host='192.168.1.20', port=8765, token='secret', mode='web'
    )
    assert image.size[0] > 0
    extrema = image.convert('L').getextrema()
    assert extrema[0] < extrema[1]
```

Keep existing `test_pairing_uri_contains_connection_details` and `test_make_qr_image_is_non_empty` (default mode becomes web; image still non-empty).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd windows_receiver && python -m pytest tests/test_pairing.py -v`

Expected: FAIL — `build_web_pairing_uri` not defined / unexpected kwargs.

- [ ] **Step 3: Implement pairing helpers**

Update `windows_receiver/mobile_mic_receiver/pairing.py` to:

```python
from __future__ import annotations

import sys
from urllib.parse import urlencode


def build_pairing_uri(*, host: str, port: int, token: str) -> str:
    parameters = {'host': host, 'port': str(port)}
    if token:
        parameters['token'] = token
    return f'mobilemic://connect?{urlencode(parameters)}'


def build_web_pairing_uri(*, host: str, port: int, token: str) -> str:
    base = f'http://{host}:{port}/'
    if not token:
        return base
    return f'{base}?{urlencode({"token": token})}'


def _pairing_data(*, host: str, port: int, token: str, mode: str) -> str:
    if mode == 'app':
        return build_pairing_uri(host=host, port=port, token=token)
    if mode == 'web':
        return build_web_pairing_uri(host=host, port=port, token=token)
    raise ValueError(f'unsupported pairing mode: {mode}')


def make_qr_image(
    *,
    host: str,
    port: int,
    token: str,
    box_size: int = 6,
    mode: str = 'web',
):
    import qrcode
    from PIL import Image

    pairing_uri = _pairing_data(host=host, port=port, token=token, mode=mode)
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


def print_pairing_qr(
    *, host: str, port: int, token: str, mode: str = 'web'
) -> None:
    import qrcode

    modes = ['web', 'app'] if mode == 'both' else [mode]
    for item in modes:
        pairing_uri = _pairing_data(
            host=host, port=port, token=token, mode=item
        )
        code = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=1,
            border=4,
        )
        code.add_data(pairing_uri)
        code.make(fit=True)
        label = (
            'Scan this QR code in the phone browser:'
            if item == 'web'
            else 'Scan this QR code in the mobile app:'
        )
        print(label)
        code.print_ascii(out=sys.stdout, tty=False, invert=True)
        print(f'Pairing URI: {pairing_uri}')
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd windows_receiver && python -m pytest tests/test_pairing.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add windows_receiver/mobile_mic_receiver/pairing.py windows_receiver/tests/test_pairing.py
git commit -m "feat(receiver): add HTTP web pairing URI and QR mode"
```

---

### Task 2: Static HTTP asset helper

**Files:**
- Create: `windows_receiver/mobile_mic_receiver/static_http.py`
- Create: `windows_receiver/mobile_mic_receiver/web_assets/index.html` (minimal placeholder OK)
- Create: `windows_receiver/mobile_mic_receiver/web_assets/styles.css`
- Create: `windows_receiver/mobile_mic_receiver/web_assets/app.js`
- Create: `windows_receiver/mobile_mic_receiver/web_assets/worklet.js`
- Create: `windows_receiver/tests/test_static_http.py`
- Modify: `windows_receiver/pyproject.toml` (package-data)

**Interfaces:**
- Produces:
  - `STATIC_ROUTES: dict[str, tuple[str, str]]` mapping URL path → `(filename, content_type)`
  - `resolve_static(path: str) -> tuple[str, str] | None` — strips query; maps `/` → index
  - `load_asset(filename: str) -> bytes`
  - `build_static_response(path: str, method: str) -> Response | None`  
    - `None` means “not a static route” (caller continues WebSocket handshake)  
    - For known route + GET/HEAD → `200` Response (HEAD body empty)  
    - For known route + other method → `405`  
    - Unknown path is `None` only when path looks like WS upgrade path handling is separate; **this helper returns a 404 Response for non-whitelisted non-empty paths that are not `/mic`** — actually keep helper pure: return `None` if path not in whitelist; return 405/200 for whitelist. Server decides 404 for other HTTP.
  - Simpler contract used by server:
    - `handle_http(path: str, method: str) -> Response | None`  
      - If path is static whitelist → Response (200/405)  
      - Else → `None` (server may 404 or continue handshake)

- [ ] **Step 1: Create minimal asset files**

`web_assets/index.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Mobile Mic Bridge</title>
    <link rel="stylesheet" href="/styles.css" />
  </head>
  <body>
    <main>
      <h1>Mobile Mic Bridge</h1>
      <p id="status">占位页面 — Task 4 替换完整客户端</p>
    </main>
    <script src="/app.js"></script>
  </body>
</html>
```

`web_assets/styles.css`:

```css
body { font-family: system-ui, sans-serif; margin: 1rem; }
```

`web_assets/app.js`:

```js
console.log('mobile-mic-bridge web client placeholder');
```

`web_assets/worklet.js`:

```js
// Placeholder; replaced in Task 4.
```

- [ ] **Step 2: Write the failing tests**

Create `windows_receiver/tests/test_static_http.py`:

```python
from mobile_mic_receiver.static_http import handle_http, resolve_static


def test_resolve_root_and_index() -> None:
    assert resolve_static('/') == ('index.html', 'text/html; charset=utf-8')
    assert resolve_static('/index.html') == (
        'index.html',
        'text/html; charset=utf-8',
    )


def test_resolve_strips_query() -> None:
    assert resolve_static('/app.js?token=x') == (
        'app.js',
        'application/javascript; charset=utf-8',
    )


def test_resolve_unknown_is_none() -> None:
    assert resolve_static('/secret') is None
    assert resolve_static('/../pairing.py') is None
    assert resolve_static('/mic') is None


def test_handle_get_index_ok() -> None:
    response = handle_http('/', 'GET')
    assert response is not None
    assert response.status_code == 200
    assert b'Mobile Mic Bridge' in bytes(response.body)
    assert 'text/html' in response.headers['Content-Type']


def test_handle_head_has_empty_body() -> None:
    response = handle_http('/styles.css', 'HEAD')
    assert response is not None
    assert response.status_code == 200
    assert bytes(response.body) == b''


def test_handle_post_method_not_allowed() -> None:
    response = handle_http('/app.js', 'POST')
    assert response is not None
    assert response.status_code == 405


def test_handle_unknown_returns_none() -> None:
    assert handle_http('/nope', 'GET') is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd windows_receiver && python -m pytest tests/test_static_http.py -v`

Expected: FAIL — module missing.

- [ ] **Step 4: Implement `static_http.py` and package-data**

`windows_receiver/mobile_mic_receiver/static_http.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

from websockets.datastructures import Headers
from websockets.http11 import Response

STATIC_ROUTES: dict[str, tuple[str, str]] = {
    '/': ('index.html', 'text/html; charset=utf-8'),
    '/index.html': ('index.html', 'text/html; charset=utf-8'),
    '/app.js': ('app.js', 'application/javascript; charset=utf-8'),
    '/styles.css': ('styles.css', 'text/css; charset=utf-8'),
    '/worklet.js': ('worklet.js', 'application/javascript; charset=utf-8'),
}


def resolve_static(path: str) -> tuple[str, str] | None:
    raw = path.split('?', 1)[0]
    if raw != '/' and raw.endswith('/'):
        raw = raw.rstrip('/')
    return STATIC_ROUTES.get(raw)


def asset_root() -> Path:
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / 'mobile_mic_receiver' / 'web_assets'
    return Path(__file__).resolve().parent / 'web_assets'


def load_asset(filename: str) -> bytes:
    if '/' in filename or '\\' in filename or '..' in filename:
        raise FileNotFoundError(filename)
    path = asset_root() / filename
    return path.read_bytes()


def handle_http(path: str, method: str) -> Response | None:
    resolved = resolve_static(path)
    if resolved is None:
        return None
    filename, content_type = resolved
    upper = method.upper()
    if upper not in {'GET', 'HEAD'}:
        return Response(
            405,
            'Method Not Allowed',
            Headers(
                [
                    ('Content-Type', 'text/plain; charset=utf-8'),
                    ('Allow', 'GET, HEAD'),
                    ('Connection', 'close'),
                ]
            ),
            b'Method Not Allowed',
        )
    try:
        body = load_asset(filename)
    except OSError:
        return Response(
            404,
            'Not Found',
            Headers(
                [
                    ('Content-Type', 'text/plain; charset=utf-8'),
                    ('Connection', 'close'),
                ]
            ),
            b'Not Found',
        )
    if upper == 'HEAD':
        body = b''
    return Response(
        200,
        'OK',
        Headers(
            [
                ('Content-Type', content_type),
                ('Content-Length', str(len(body) if upper == 'GET' else 0)),
                ('Cache-Control', 'no-cache'),
                ('Connection', 'close'),
            ]
        ),
        body,
    )
```

For HEAD, set `Content-Length` to the real file size (optional improvement). Minimal acceptable: `Content-Length: 0` with empty body for HEAD. Prefer:

```python
    data = load_asset(filename)
    body = b'' if upper == 'HEAD' else data
    return Response(
        200,
        'OK',
        Headers(
            [
                ('Content-Type', content_type),
                ('Content-Length', str(len(data))),
                ('Cache-Control', 'no-cache'),
                ('Connection', 'close'),
            ]
        ),
        body,
    )
```

Update `windows_receiver/pyproject.toml` — add after packages.find:

```toml
[tool.setuptools.package-data]
mobile_mic_receiver = ['web_assets/*']
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd windows_receiver && python -m pytest tests/test_static_http.py -v`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add windows_receiver/mobile_mic_receiver/static_http.py \
  windows_receiver/mobile_mic_receiver/web_assets \
  windows_receiver/tests/test_static_http.py \
  windows_receiver/pyproject.toml
git commit -m "feat(receiver): serve whitelist static assets helper"
```

---

### Task 3: Same-port HTTP via MicServer.process_request

**Files:**
- Modify: `windows_receiver/mobile_mic_receiver/server.py`
- Create: `windows_receiver/tests/test_server_http.py`
- Keep green: `tests/test_server.py`, `tests/test_server_events.py`

**Interfaces:**
- Consumes: `static_http.handle_http(path, method) -> Response | None`
- Produces: `MicServer` passes `process_request=self._process_request` into `serve(...)`
  - Signature: `async def _process_request(self, connection, request) -> Response | None`
  - If `request.path` (query-stripped) is `/mic` → return `None` (continue WS handshake)
  - Else if static handler returns Response → return it
  - Else → return `404` Response with plain body `Not Found`

- [ ] **Step 1: Write the failing integration tests**

Create `windows_receiver/tests/test_server_http.py`:

```python
import asyncio
import json
from urllib.request import urlopen, Request

import pytest

pytest.importorskip('websockets')

from websockets.asyncio.client import connect

from mobile_mic_receiver.buffer import AudioBuffer
from mobile_mic_receiver.server import MicServer, ServerConfig


def _hello(token: str = 'secret') -> str:
    return json.dumps(
        {
            'type': 'hello',
            'version': 1,
            'sampleRate': 48000,
            'channels': 1,
            'format': 'pcm_s16le',
            'token': token,
            'device': 'web-other',
        }
    )


async def _start_server(token: str = 'secret') -> tuple[MicServer, asyncio.Task, int]:
    buffer = AudioBuffer(sample_rate=48000, channels=1, prebuffer_ms=1)
    server = MicServer(
        ServerConfig(host='127.0.0.1', port=0, token=token),
        buffer,
    )
    task = asyncio.create_task(server.run())
    for _ in range(100):
        if server.bound_port is not None:
            break
        await asyncio.sleep(0.02)
    assert server.bound_port is not None
    return server, task, server.bound_port


def test_http_get_index_and_websocket_mic() -> None:
    async def scenario() -> None:
        server, task, port = await _start_server()
        try:
            # Blocking urlopen in thread to avoid blocking event loop hard.
            def fetch() -> bytes:
                with urlopen(f'http://127.0.0.1:{port}/', timeout=2) as resp:
                    assert resp.status == 200
                    return resp.read()

            body = await asyncio.to_thread(fetch)
            assert b'Mobile Mic Bridge' in body

            async with connect(f'ws://127.0.0.1:{port}/mic') as ws:
                await ws.send(_hello())
                ready = json.loads(await ws.recv())
                assert ready['type'] == 'ready'
                await ws.send(b'\x01\x00')
        finally:
            server.request_stop()
            await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())


def test_http_unknown_path_is_404() -> None:
    async def scenario() -> None:
        server, task, port = await _start_server()
        try:
            def fetch_status() -> int:
                try:
                    urlopen(f'http://127.0.0.1:{port}/nope', timeout=2)
                    return 200
                except Exception as exc:  # urllib HTTPError
                    return getattr(exc, 'code', 0)

            status = await asyncio.to_thread(fetch_status)
            assert status == 404
        finally:
            server.request_stop()
            await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd windows_receiver && python -m pytest tests/test_server_http.py -v`

Expected: FAIL — HTTP GET not handled / connection errors.

- [ ] **Step 3: Wire `process_request` into `MicServer.run`**

In `server.py`:

1. Import:

```python
from websockets.datastructures import Headers
from websockets.http11 import Request, Response

from .static_http import handle_http
```

2. Add method:

```python
    async def _process_request(
        self, connection: ServerConnection, request: Request
    ) -> Response | None:
        path = request.path.split('?', 1)[0]
        if path == '/mic':
            return None
        static = handle_http(request.path, request.method)
        if static is not None:
            return static
        return Response(
            404,
            'Not Found',
            Headers(
                [
                    ('Content-Type', 'text/plain; charset=utf-8'),
                    ('Connection', 'close'),
                ]
            ),
            b'Not Found',
        )
```

3. Pass into `serve(...)`:

```python
            async with serve(
                self.handler,
                self._config.host,
                self._config.port,
                max_size=256 * 1024,
                max_queue=8,
                ping_interval=20,
                ping_timeout=20,
                process_request=self._process_request,
            ) as ws_server:
```

Note: existing unit tests that call `serve(server.handler, ...)` directly without `process_request` still only exercise the handler; full stack tests use `server.run()`.

- [ ] **Step 4: Run HTTP + full suite subset**

Run:

```bash
cd windows_receiver
python -m pytest tests/test_server_http.py tests/test_server.py tests/test_server_events.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add windows_receiver/mobile_mic_receiver/server.py windows_receiver/tests/test_server_http.py
git commit -m "feat(receiver): serve web assets on same port as /mic"
```

---

### Task 4: Full web mic client (HTML/CSS/JS/Worklet)

**Files:**
- Replace: `windows_receiver/mobile_mic_receiver/web_assets/index.html`
- Replace: `windows_receiver/mobile_mic_receiver/web_assets/styles.css`
- Replace: `windows_receiver/mobile_mic_receiver/web_assets/app.js`
- Replace: `windows_receiver/mobile_mic_receiver/web_assets/worklet.js`
- Modify: `windows_receiver/tests/test_static_http.py` if body assertions need richer markers

**Interfaces:**
- Page URL: `http://host:port/?token=...`
- WS URL: `ws://` + `location.host` + `/mic`
- Hello JSON: `{type:'hello', version:1, sampleRate:48000, channels:1, format:'pcm_s16le', token, device}`
- Control: `{type:'pause'|'resume'}`
- Binary: little-endian int16 mono @ 48 kHz, ~20 ms frames
- Token from query only in memory

- [ ] **Step 1: Implement `worklet.js`**

```js
class CaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel && channel.length) {
      // Copy because the underlying buffer is reused.
      this.port.postMessage(channel.slice(0));
    }
    return true;
  }
}

registerProcessor('capture-processor', CaptureProcessor);
```

- [ ] **Step 2: Implement `index.html`**

```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
    <meta name="color-scheme" content="light dark" />
    <title>Mobile Mic Bridge</title>
    <link rel="stylesheet" href="/styles.css" />
  </head>
  <body>
    <main class="card">
      <h1>Mobile Mic Bridge</h1>
      <p class="hint">
        建议佩戴耳机，并尽量保持本页在前台。浏览器降噪/回声消除默认开启，但不能保证锁屏后继续录音。
      </p>
      <p id="status" class="status">状态：空闲</p>
      <p id="error" class="error" hidden></p>
      <p id="bg-warn" class="warn" hidden>页面已进入后台，传输可能被系统中断。</p>

      <div class="row">
        <button id="btn-start" type="button">开始传输</button>
        <button id="btn-pause" type="button" disabled>暂停</button>
        <button id="btn-stop" type="button" disabled>停止</button>
      </div>

      <label class="block">
        发送音量 <span id="gain-label">100%</span>
        <input id="gain" type="range" min="0" max="200" value="100" />
      </label>

      <fieldset>
        <legend>音频处理</legend>
        <label><input id="echo" type="checkbox" checked /> 回声消除</label>
        <label><input id="noise" type="checkbox" checked /> 噪音抑制</label>
        <label><input id="agc" type="checkbox" checked /> 自动增益</label>
      </fieldset>

      <label class="block">
        输入电平
        <progress id="level" max="1" value="0"></progress>
      </label>
    </main>
    <script src="/app.js"></script>
  </body>
</html>
```

- [ ] **Step 3: Implement `styles.css`**

```css
:root {
  color-scheme: light dark;
  --bg: #0f1419;
  --card: #1a2332;
  --text: #e7eef8;
  --muted: #9db0c7;
  --accent: #3b82f6;
  --danger: #f87171;
  --warn: #fbbf24;
  font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
}

@media (prefers-color-scheme: light) {
  :root {
    --bg: #f4f7fb;
    --card: #ffffff;
    --text: #0f172a;
    --muted: #475569;
  }
}

body {
  margin: 0;
  min-height: 100vh;
  background: var(--bg);
  color: var(--text);
  display: flex;
  justify-content: center;
  padding: 1rem;
  box-sizing: border-box;
}

.card {
  width: min(28rem, 100%);
  background: var(--card);
  border-radius: 1rem;
  padding: 1.25rem;
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.15);
}

h1 {
  font-size: 1.25rem;
  margin: 0 0 0.75rem;
}

.hint,
.status {
  color: var(--muted);
  font-size: 0.9rem;
  line-height: 1.4;
}

.error {
  color: var(--danger);
  font-size: 0.9rem;
}

.warn {
  color: var(--warn);
  font-size: 0.9rem;
}

.row {
  display: flex;
  gap: 0.5rem;
  margin: 1rem 0;
  flex-wrap: wrap;
}

button {
  flex: 1;
  min-width: 5.5rem;
  border: 0;
  border-radius: 0.6rem;
  padding: 0.7rem 0.8rem;
  background: var(--accent);
  color: white;
  font-weight: 600;
}

button:disabled {
  opacity: 0.45;
}

.block,
fieldset {
  display: grid;
  gap: 0.4rem;
  margin: 0.9rem 0;
  border: 0;
  padding: 0;
}

fieldset label {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  color: var(--muted);
}

input[type='range'],
progress {
  width: 100%;
}
```

- [ ] **Step 4: Implement `app.js`**

Implement a single-file client with these pieces (keep names so later debugging is easy):

```js
(() => {
  const TARGET_RATE = 48000;
  const FRAME_SAMPLES = 960; // 20 ms @ 48 kHz
  const MAX_QUEUE_FRAMES = 8;

  const els = {
    status: document.getElementById('status'),
    error: document.getElementById('error'),
    bgWarn: document.getElementById('bg-warn'),
    start: document.getElementById('btn-start'),
    pause: document.getElementById('btn-pause'),
    stop: document.getElementById('btn-stop'),
    gain: document.getElementById('gain'),
    gainLabel: document.getElementById('gain-label'),
    echo: document.getElementById('echo'),
    noise: document.getElementById('noise'),
    agc: document.getElementById('agc'),
    level: document.getElementById('level'),
  };

  let state = 'idle';
  let sessionId = 0;
  let token = new URLSearchParams(location.search).get('token') || '';
  let gain = 1.0;
  let ws = null;
  let audioContext = null;
  let mediaStream = null;
  let workletNode = null;
  let sourceNode = null;
  let scriptNode = null;
  let wakeLock = null;
  let sendQueue = [];
  let pcmCarry = new Float32Array(0);
  let userPaused = false;

  function setStatus(text) {
    els.status.textContent = `状态：${text}`;
  }

  function setError(message) {
    if (!message) {
      els.error.hidden = true;
      els.error.textContent = '';
      return;
    }
    els.error.hidden = false;
    els.error.textContent = message;
  }

  function setButtons() {
    els.start.disabled = state === 'streaming' || state === 'connecting' || state === 'requesting_mic';
    els.pause.disabled = state !== 'streaming' && state !== 'paused';
    els.pause.textContent = state === 'paused' ? '继续' : '暂停';
    els.stop.disabled = state === 'idle';
  }

  function deviceLabel() {
    const ua = navigator.userAgent || '';
    if (/Android/i.test(ua)) return 'web-android';
    if (/iPhone|iPad|iPod/i.test(ua)) return 'web-ios';
    return 'web-other';
  }

  function audioConstraints() {
    return {
      audio: {
        channelCount: 1,
        echoCancellation: !!els.echo.checked,
        noiseSuppression: !!els.noise.checked,
        autoGainControl: !!els.agc.checked,
      },
      video: false,
    };
  }

  function resampleLinear(input, fromRate, toRate) {
    if (fromRate === toRate) return input;
    const ratio = fromRate / toRate;
    const outLength = Math.floor(input.length / ratio);
    const out = new Float32Array(outLength);
    for (let i = 0; i < outLength; i++) {
      const src = i * ratio;
      const i0 = Math.floor(src);
      const i1 = Math.min(i0 + 1, input.length - 1);
      const frac = src - i0;
      out[i] = input[i0] * (1 - frac) + input[i1] * frac;
    }
    return out;
  }

  function floatToPcm16(floatSamples, gainValue) {
    const buffer = new ArrayBuffer(floatSamples.length * 2);
    const view = new DataView(buffer);
    for (let i = 0; i < floatSamples.length; i++) {
      let s = floatSamples[i] * gainValue;
      if (s > 1) s = 1;
      if (s < -1) s = -1;
      view.setInt16(i * 2, (s * 32767) | 0, true);
    }
    return buffer;
  }

  function peakOf(floatSamples) {
    let peak = 0;
    for (let i = 0; i < floatSamples.length; i++) {
      const a = Math.abs(floatSamples[i]);
      if (a > peak) peak = a;
    }
    return peak;
  }

  function enqueuePcm(arrayBuffer) {
    sendQueue.push(arrayBuffer);
    while (sendQueue.length > MAX_QUEUE_FRAMES) sendQueue.shift();
    flushQueue();
  }

  function flushQueue() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    while (sendQueue.length) {
      ws.send(sendQueue.shift());
    }
  }

  function handleCaptureFloats(floatSamples, sid) {
    if (sid !== sessionId || state !== 'streaming') return;
    const rate = audioContext ? audioContext.sampleRate : TARGET_RATE;
    const resampled = resampleLinear(floatSamples, rate, TARGET_RATE);
    els.level.value = peakOf(resampled);

    const merged = new Float32Array(pcmCarry.length + resampled.length);
    merged.set(pcmCarry, 0);
    merged.set(resampled, pcmCarry.length);

    let offset = 0;
    while (offset + FRAME_SAMPLES <= merged.length) {
      const frame = merged.subarray(offset, offset + FRAME_SAMPLES);
      enqueuePcm(floatToPcm16(frame, gain));
      offset += FRAME_SAMPLES;
    }
    pcmCarry = merged.subarray(offset);
  }

  async function requestWakeLock() {
    try {
      if (navigator.wakeLock && navigator.wakeLock.request) {
        wakeLock = await navigator.wakeLock.request('screen');
        wakeLock.addEventListener('release', () => {
          wakeLock = null;
        });
      }
    } catch (_) {
      /* optional */
    }
  }

  async function releaseWakeLock() {
    try {
      if (wakeLock) await wakeLock.release();
    } catch (_) {
      /* ignore */
    }
    wakeLock = null;
  }

  async function openMic() {
    mediaStream = await navigator.mediaDevices.getUserMedia(audioConstraints());
    audioContext = new (window.AudioContext || window.webkitAudioContext)({
      sampleRate: TARGET_RATE,
    });
    if (audioContext.state === 'suspended') await audioContext.resume();
    sourceNode = audioContext.createMediaStreamSource(mediaStream);

    const sid = sessionId;
    const silent = audioContext.createGain();
    silent.gain.value = 0;
    try {
      await audioContext.audioWorklet.addModule('/worklet.js');
      workletNode = new AudioWorkletNode(audioContext, 'capture-processor');
      workletNode.port.onmessage = (ev) => {
        handleCaptureFloats(ev.data, sid);
      };
      sourceNode.connect(workletNode);
      // Keep graph alive without audible local monitor (avoids phone speaker echo).
      workletNode.connect(silent);
      silent.connect(audioContext.destination);
    } catch (_) {
      const bufferSize = 4096;
      scriptNode = audioContext.createScriptProcessor(bufferSize, 1, 1);
      scriptNode.onaudioprocess = (ev) => {
        const input = ev.inputBuffer.getChannelData(0);
        handleCaptureFloats(new Float32Array(input), sid);
      };
      sourceNode.connect(scriptNode);
      scriptNode.connect(silent);
      silent.connect(audioContext.destination);
    }
  }

  function stopMicOnly() {
    try {
      if (workletNode) workletNode.disconnect();
    } catch (_) {}
    try {
      if (scriptNode) scriptNode.disconnect();
    } catch (_) {}
    try {
      if (sourceNode) sourceNode.disconnect();
    } catch (_) {}
    workletNode = null;
    scriptNode = null;
    sourceNode = null;
    if (mediaStream) {
      mediaStream.getTracks().forEach((t) => t.stop());
      mediaStream = null;
    }
    if (audioContext) {
      audioContext.close();
      audioContext = null;
    }
    pcmCarry = new Float32Array(0);
    sendQueue = [];
    els.level.value = 0;
  }

  function closeSocket() {
    if (ws) {
      try {
        ws.close();
      } catch (_) {}
    }
    ws = null;
  }

  async function fullCleanup() {
    stopMicOnly();
    closeSocket();
    await releaseWakeLock();
  }

  function connectWs(sid) {
    return new Promise((resolve, reject) => {
      const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const socket = new WebSocket(`${scheme}//${location.host}/mic`);
      socket.binaryType = 'arraybuffer';
      let settled = false;

      const timer = setTimeout(() => {
        if (!settled) {
          settled = true;
          socket.close();
          reject(new Error('连接超时'));
        }
      }, 5000);

      socket.onopen = () => {
        socket.send(
          JSON.stringify({
            type: 'hello',
            version: 1,
            sampleRate: TARGET_RATE,
            channels: 1,
            format: 'pcm_s16le',
            token: token,
            device: deviceLabel(),
          })
        );
      };

      socket.onmessage = (ev) => {
        if (typeof ev.data !== 'string') return;
        let msg;
        try {
          msg = JSON.parse(ev.data);
        } catch (_) {
          return;
        }
        if (msg.type === 'ready' && !settled) {
          settled = true;
          clearTimeout(timer);
          resolve(socket);
        } else if (msg.type === 'error' && !settled) {
          settled = true;
          clearTimeout(timer);
          reject(new Error(msg.message || '连接被拒绝'));
        }
      };

      socket.onerror = () => {
        if (!settled) {
          settled = true;
          clearTimeout(timer);
          reject(new Error('WebSocket 错误'));
        }
      };

      socket.onclose = () => {
        if (sid === sessionId && (state === 'streaming' || state === 'paused')) {
          state = 'error';
          setStatus('错误');
          setError('连接已断开');
          setButtons();
          fullCleanup();
        }
        if (!settled) {
          settled = true;
          clearTimeout(timer);
          reject(new Error('连接关闭'));
        }
      };
    });
  }

  async function start() {
    if (state !== 'idle' && state !== 'error') return;
    sessionId += 1;
    const sid = sessionId;
    userPaused = false;
    setError('');
    state = 'requesting_mic';
    setStatus('申请麦克风…');
    setButtons();
    try {
      await openMic();
      if (sid !== sessionId) return;
      state = 'connecting';
      setStatus('连接中…');
      setButtons();
      ws = await connectWs(sid);
      if (sid !== sessionId) return;
      state = 'streaming';
      setStatus('传输中');
      setButtons();
      await requestWakeLock();
    } catch (err) {
      if (sid !== sessionId) return;
      state = 'error';
      setStatus('错误');
      setError(err && err.message ? err.message : String(err));
      setButtons();
      await fullCleanup();
    }
  }

  async function pauseToggle() {
    if (state === 'streaming') {
      userPaused = true;
      stopMicOnly();
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'pause' }));
      }
      state = 'paused';
      setStatus('已暂停');
      setButtons();
      return;
    }
    if (state === 'paused') {
      const sid = sessionId;
      try {
        if (!ws || ws.readyState !== WebSocket.OPEN) {
          state = 'connecting';
          setStatus('重连中…');
          setButtons();
          ws = await connectWs(sid);
        } else {
          ws.send(JSON.stringify({ type: 'resume' }));
        }
        await openMic();
        if (sid !== sessionId) return;
        userPaused = false;
        state = 'streaming';
        setStatus('传输中');
        setButtons();
        await requestWakeLock();
      } catch (err) {
        state = 'error';
        setStatus('错误');
        setError(err && err.message ? err.message : String(err));
        setButtons();
        await fullCleanup();
      }
    }
  }

  async function stop() {
    sessionId += 1;
    state = 'idle';
    setStatus('空闲');
    setError('');
    setButtons();
    await fullCleanup();
  }

  async function applyTrackConstraints() {
    if (!mediaStream) return;
    const track = mediaStream.getAudioTracks()[0];
    if (!track || !track.applyConstraints) return;
    try {
      await track.applyConstraints({
        echoCancellation: !!els.echo.checked,
        noiseSuppression: !!els.noise.checked,
        autoGainControl: !!els.agc.checked,
      });
    } catch (_) {
      /* some browsers reject partial constraint updates */
    }
  }

  els.start.addEventListener('click', () => start());
  els.pause.addEventListener('click', () => pauseToggle());
  els.stop.addEventListener('click', () => stop());
  els.gain.addEventListener('input', () => {
    gain = Number(els.gain.value) / 100;
    els.gainLabel.textContent = `${els.gain.value}%`;
  });
  els.echo.addEventListener('change', () => applyTrackConstraints());
  els.noise.addEventListener('change', () => applyTrackConstraints());
  els.agc.addEventListener('change', () => applyTrackConstraints());

  document.addEventListener('visibilitychange', () => {
    els.bgWarn.hidden = document.visibilityState === 'visible';
    if (document.visibilityState === 'visible' && state === 'streaming') {
      requestWakeLock();
      if (audioContext && audioContext.state === 'suspended') {
        audioContext.resume();
      }
    }
  });

  setButtons();
  setStatus('空闲');
})();
```

- [ ] **Step 5: Soften static test if needed**

`test_handle_get_index_ok` still asserts `b'Mobile Mic Bridge' in body` — keep that string in `<h1>`.

Run: `cd windows_receiver && python -m pytest tests/test_static_http.py tests/test_server_http.py -v`

Expected: PASS

- [ ] **Step 6: Manual smoke (developer machine)**

```bash
cd windows_receiver
python -m pip install -e .
mobile-mic-receiver --host 0.0.0.0 --port 8765 --token test --no-discovery
```

On phone or desktop browser: open `http://<lan-ip>:8765/?token=test`, allow mic, click 开始传输, confirm receiver prints connected and plays audio.

- [ ] **Step 7: Commit**

```bash
git add windows_receiver/mobile_mic_receiver/web_assets
git commit -m "feat(web): browser mic client with AEC/NS/AGC and PCM stream"
```

---

### Task 5: Controller, CLI, GUI default to web QR

**Files:**
- Modify: `windows_receiver/mobile_mic_receiver/controller.py`
- Modify: `windows_receiver/mobile_mic_receiver/cli.py`
- Modify: `windows_receiver/mobile_mic_receiver/gui/app.py`
- Modify: `windows_receiver/tests/test_controller.py`

**Interfaces:**
- `ControllerSnapshot` fields:
  - `pairing_uri: str` — **web** HTTP URI (default displayed / copied)
  - `app_pairing_uri: str` — `mobilemic://` URI
- Controller builds both when addresses available
- CLI: `--qr-mode` choices `web|app|both`, default `web`; pass to `print_pairing_qr`
- GUI: segmented control `网页` / `App`; regenerates QR with `mode=`; copy button copies currently shown URI

- [ ] **Step 1: Write / extend failing controller test**

In `tests/test_controller.py` add:

```python
def test_snapshot_pairing_uri_is_http_web() -> None:
    controller = ReceiverController()
    with patch('mobile_mic_receiver.controller.AudioOutput', DummyAudio), patch(
        'mobile_mic_receiver.controller.MdnsAdvertiser'
    ) as advertiser, patch(
        'mobile_mic_receiver.controller.local_ipv4_addresses',
        return_value=['192.168.1.20'],
    ):
        advertiser.return_value.start.return_value = None
        advertiser.return_value.close.return_value = None
        controller.start(
            ControllerConfig(
                device=None, host='127.0.0.1', port=18768, token='secret'
            )
        )
        try:
            deadline = time.time() + 3
            snap = controller.snapshot()
            while time.time() < deadline and not snap.pairing_uri:
                time.sleep(0.05)
                snap = controller.snapshot()
            assert snap.pairing_uri.startswith('http://192.168.1.20:18768/')
            assert 'token=secret' in snap.pairing_uri
            assert snap.app_pairing_uri.startswith('mobilemic://connect?')
        finally:
            controller.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd windows_receiver && python -m pytest tests/test_controller.py::test_snapshot_pairing_uri_is_http_web -v`

Expected: FAIL — missing `app_pairing_uri` or still `mobilemic` in `pairing_uri`.

- [ ] **Step 3: Update controller**

Import `build_web_pairing_uri` alongside `build_pairing_uri`.

Extend `ControllerSnapshot` with `app_pairing_uri: str`.

In `__init__` / `start` reset: `self._app_pairing_uri = ''`.

In `_thread_main` when addresses exist:

```python
            pairing_uri = ''
            app_pairing_uri = ''
            if addresses:
                pairing_uri = build_web_pairing_uri(
                    host=addresses[0],
                    port=config.port,
                    token=config.token,
                )
                app_pairing_uri = build_pairing_uri(
                    host=addresses[0],
                    port=config.port,
                    token=config.token,
                )
            with self._lock:
                self._local_addresses = addresses
                self._pairing_uri = pairing_uri
                self._app_pairing_uri = app_pairing_uri
```

Include `app_pairing_uri=self._app_pairing_uri` in `snapshot()` return.

Update any other `ControllerSnapshot(...)` constructions in tests if they construct manually (they currently only read snapshots).

- [ ] **Step 4: Update CLI**

In `build_parser()`:

```python
    parser.add_argument(
        '--qr-mode',
        choices=('web', 'app', 'both'),
        default='web',
        help='Pairing QR content (default: web page URL)',
    )
```

When printing QR:

```python
            print_pairing_qr(
                host=addresses[0],
                port=args.port,
                token=args.token,
                mode=args.qr_mode,
            )
```

Also print the web URL line for clarity when mode is web/both:

```python
        print(f'Web page: http://{addresses[0]}:{args.port}/')
```

- [ ] **Step 5: Update GUI**

1. After pairing title, add segmented control:

```python
        self._qr_mode_var = tk.StringVar(value='web')
        self._qr_mode = ctk.CTkSegmentedButton(
            pairing,
            values=['网页', 'App'],
            command=self._on_qr_mode,
        )
        self._qr_mode.set('网页')
        self._qr_mode.grid(row=0, column=0, sticky='e', padx=12, pady=(12, 8))
```

Adjust layout so title and segmented control share the header row (title column 0 left, segmented right) — use an inner header frame if easier.

2. Change `_update_qr` to:

```python
    def _qr_mode_key(self) -> str:
        return 'app' if self._qr_mode_var.get() == 'App' or self._qr_mode.get() == 'App' else 'web'

    def _update_qr(self, host: str, port: int, token: str) -> None:
        mode = 'app' if self._qr_mode.get() == 'App' else 'web'
        try:
            image = make_qr_image(
                host=host, port=port, token=token, box_size=5, mode=mode
            )
            ...
```

3. On mode change, rebuild QR and URI field from last known host/port/token and snapshot URIs:

```python
    def _on_qr_mode(self, _value: str) -> None:
        snap = self._controller.snapshot()
        if self._qr_mode.get() == 'App':
            if snap.app_pairing_uri:
                self._uri_var.set(snap.app_pairing_uri)
        else:
            if snap.pairing_uri:
                self._uri_var.set(snap.pairing_uri)
        # re-render QR using addresses + token fields
        ...
```

Store last `host/port` used for QR on the app instance when snapshot updates (`self._qr_host`, `self._qr_port`).

4. Update placeholder copy: `启动后显示二维码` → `启动后显示网页配对二维码` where appropriate.

5. When snapshot updates and mode is web, set URI from `snap.pairing_uri`; if App mode, `snap.app_pairing_uri`.

- [ ] **Step 6: Run tests**

```bash
cd windows_receiver
python -m pytest -q
```

Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add windows_receiver/mobile_mic_receiver/controller.py \
  windows_receiver/mobile_mic_receiver/cli.py \
  windows_receiver/mobile_mic_receiver/gui/app.py \
  windows_receiver/tests/test_controller.py
git commit -m "feat(receiver): default pairing QR to hosted web client"
```

---

### Task 6: PyInstaller packaging for web_assets

**Files:**
- Modify: `.github/workflows/release.yml`
- Modify: `windows_receiver/mobile-mic-receiver-windows-x64.spec` if kept in repo (optional; CI uses CLI flags)

**Interfaces:**
- Frozen EXE must resolve `asset_root()` to extracted `mobile_mic_receiver/web_assets`

- [ ] **Step 1: Update release workflow PyInstaller command**

In `.github/workflows/release.yml` windows build step, add `--add-data` for assets. On Windows runners the separator is `;`:

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
          --add-data "mobile_mic_receiver/web_assets;mobile_mic_receiver/web_assets"
          gui_main.py
```

- [ ] **Step 2: Update local spec file if present**

In `windows_receiver/mobile-mic-receiver-windows-x64.spec`, ensure datas includes:

```python
from PyInstaller.utils.hooks import collect_all
import os

datas = [('mobile_mic_receiver/web_assets', 'mobile_mic_receiver/web_assets')]
# then existing collect_all appends...
```

- [ ] **Step 3: Sanity check asset_root logic**

Optional unit test with monkeypatch:

```python
def test_asset_root_frozen(monkeypatch, tmp_path):
    assets = tmp_path / 'mobile_mic_receiver' / 'web_assets'
    assets.mkdir(parents=True)
    (assets / 'index.html').write_text('ok', encoding='utf-8')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    from mobile_mic_receiver.static_http import load_asset
    assert load_asset('index.html') == b'ok'
```

Add to `test_static_http.py` if easy; otherwise manual.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/release.yml windows_receiver/mobile-mic-receiver-windows-x64.spec windows_receiver/tests/test_static_http.py
git commit -m "build: package web_assets into Windows receiver EXE"
```

---

### Task 7: Documentation

**Files:**
- Modify: `docs/protocol.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`

- [ ] **Step 1: Update protocol pairing section**

In `docs/protocol.md` QR section, add HTTP form **before** or beside `mobilemic://`:

```markdown
## QR Pairing / 二维码配对

Default (web client) URI:

```text
http://192.168.1.20:8765/?token=optional
```

Phone browser opens this page (hosted by the receiver on the same port). The optional token is read from the query string for the current page session only.

App URI (Flutter):

```text
mobilemic://connect?host=192.168.1.20&port=8765&token=optional
```
```

In handshake `device` description, note values may be `web-android`, `web-ios`, `web-other`.

- [ ] **Step 2: Update English README**

Features bullet: browser web client via QR (no app install).

Quick start: after receiver Start, scan **web** QR with phone browser; grant microphone; keep page foreground; headphones recommended.

Limitations: browser background not guaranteed; AEC quality varies; iOS Safari best-effort.

CLI: document `--qr-mode`.

- [ ] **Step 3: Update Chinese README** symmetrically.

- [ ] **Step 4: Commit**

```bash
git add docs/protocol.md README.md README.zh-CN.md
git commit -m "docs: document browser web microphone client"
```

---

### Task 8: Final verification

**Files:** none new

- [ ] **Step 1: Full pytest**

```bash
cd windows_receiver
python -m pip install -e .[test]
python -m pytest -q
```

Expected: all green.

- [ ] **Step 2: Manual acceptance checklist (from spec)**

1. GUI start → web QR → Android Chrome streams → Windows hears audio  
2. VB-CABLE path works in a voice app if available  
3. AEC on vs off subjective check with PC playback  
4. Pause / resume / stop  
5. Second client rejected  
6. App QR mode still pairs Flutter app (if app available)  
7. Note iOS Safari results in README if tested  

- [ ] **Step 3: Commit any doc/test fixes only if needed**

No empty commit.

---

## Spec coverage self-check

| Spec requirement | Task |
| --- | --- |
| Same-port HTTP static hosting | 2, 3 |
| HTTP pairing QR default | 1, 5 |
| Optional App QR | 1, 5 |
| getUserMedia AEC/NS/AGC | 4 |
| PCM 48k mono s16le + hello/ready | 4 |
| Pause/resume/stop | 4 |
| Token not persisted in browser | 4 |
| Wake lock + visibility warning | 4 |
| Controller/GUI/CLI wiring | 5 |
| EXE package assets | 6 |
| Docs protocol + README | 7 |
| Tests + manual acceptance | 1–5, 8 |
| No RNNoise / no second port / no Flutter changes | honored by omission |

## Placeholder / consistency notes

- `pairing_uri` in snapshots is always the **web** URI; App URI is `app_pairing_uri`.
- QR `mode` values: `web` | `app` | `both` (CLI); GUI uses labels `网页` / `App`.
- Static whitelist paths: `/`, `/index.html`, `/app.js`, `/styles.css`, `/worklet.js`.
- `handle_http` returns `None` for non-static paths; server maps those (except `/mic`) to 404 for HTTP.
