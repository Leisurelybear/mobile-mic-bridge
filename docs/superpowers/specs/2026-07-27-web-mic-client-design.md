# Web Mic Client Design

**Date:** 2026-07-27  
**Status:** Approved  
**Scope:** Add a browser-based phone microphone client hosted by the Windows receiver, with QR pairing and browser built-in echo/noise controls as the first noise-control layer.

## Goal

Let a user start the Windows receiver (CLI or GUI), scan an on-screen QR code with a phone browser, and use that phone as a Wi-Fi microphone without installing the Flutter app.

Success criteria:

1. Receiver start → show HTTP pairing QR → phone browser opens page → grant mic → stream PCM to Windows over existing `/mic` protocol.
2. Default `getUserMedia` constraints enable `echoCancellation`, `noiseSuppression`, and `autoGainControl` to reduce PC speaker re-pickup and ambient noise.
3. Flutter app remains usable (optional App QR / manual connect); still only one phone client at a time.
4. Existing receiver unit tests keep passing; static assets ship inside the Windows EXE.
5. Docs state clearly: keep the page foreground when possible; background is best-effort; headphones recommended.

## Non-goals (v1)

- RNNoise / custom WASM DSP (later enhancement)
- Guaranteed background / lock-screen capture on all browsers
- HTTPS / WSS or public-internet mode
- Browser mDNS discovery
- Protocol version bump, Opus, multi-client
- Changing Flutter app behavior beyond optional dual QR on the receiver
- Second listen port for HTTP

## Context

Current stack:

- Flutter sender (`mobile_app`) captures mono PCM and streams over WebSocket
- Windows Python receiver: `MicServer` on port `8765`, path `/mic`, optional token, jitter buffer, output device, GUI with `mobilemic://` QR
- Wire protocol: hello/ready JSON, binary `pcm_s16le` 48 kHz mono (see `docs/protocol.md`)

User priority for this work: **daily primary alternative to the Flutter app**, with background support **best-effort**, noise control **browser constraints first, stronger DSP later**, and pages **hosted by the receiver** (same port).

## Approach

**Approach A (chosen): Receiver-hosted static web client on the same port as WebSocket.**

- HTTP GET serves a small whitelist of static files from the receiver process
- WebSocket continues at `ws://host:8765/mic` with protocol v1 unchanged
- Default pairing QR encodes `http://host:port/?token=...`
- Phone page uses `getUserMedia` + Web Audio → PCM → existing handshake

Rejected alternatives:

- **B: Separate HTTP port** — clearer separation, worse UX (second firewall rule, second URL)
- **C: External static host only** — minimal receiver change, poor daily pairing and mixed-content friction

## Architecture

```text
Phone browser                         Windows receiver
─────────────                         ────────────────
Scan QR
http://PC:8765/?token=...
        │
        │ GET /  (HTML/JS/CSS/worklet)
        ▼
  Web mic page
        │
        │ getUserMedia
        │   echoCancellation
        │   noiseSuppression
        │   autoGainControl
        ▼
  AudioWorklet (preferred) /
  ScriptProcessor (fallback)
  → resample to 48000 if needed
  → float32 → pcm_s16le mono
        │
        │ ws://PC:8765/mic
        │ hello → ready → binary PCM
        ▼
                         MicServer (existing)
                         + process_request static HTTP
                         + web pairing QR
                                │
                                ▼
                         AudioBuffer → output device
                         (e.g. VB-CABLE)
```

### Key decisions

| Topic | Decision |
| --- | --- |
| Port | Keep `8765`; HTTP + WebSocket share one port |
| Protocol | Reuse v1 hello/ready + PCM; no new fields required |
| Coexistence | Flutter and web share `/mic`; single active client lock unchanged |
| Default QR | HTTP web URI; optional App `mobilemic://` QR |
| Noise v1 | Browser `getUserMedia` constraints only |
| Background | Best-effort (wake lock, visibility UX); no hard guarantee |
| Packaging | Static assets inside receiver package / PyInstaller EXE |

## Pairing and QR

### URI forms

| Use | URI |
| --- | --- |
| Web client (default) | `http://192.168.1.20:8765/?token=optional` |
| Flutter app (existing) | `mobilemic://connect?host=192.168.1.20&port=8765&token=optional` |

Empty token omits the query parameter.

Token in the QR is intentional for LAN convenience, same trust model as today’s App QR. Docs must state: trusted LAN only; QR may reveal the connection password to anyone who can see the screen.

### After scan

1. Browser opens the HTTP URL.
2. Page reads `token` from the query string into memory only — **not** `localStorage` / cookies (aligned with Flutter: password is session-only).
3. UI shows status, start/pause/stop, transmit gain, and processing toggles.
4. On Start: request microphone → connect `ws://` same host/port `/mic` → send `hello` with token → wait for `ready` → stream.

### Host address

Reuse existing LAN IPv4 selection used for App pairing. GUI continues to list addresses; QR uses the preferred LAN IPv4. Port/bind changes refresh the QR.

### GUI / CLI

**GUI**

- Default QR: web pairing URI
- Label: phone-browser scan copy (Chinese labels consistent with current GUI)
- Show full URL as copyable text
- Segmented control or toggle: Web / App QR (`web` default)

**CLI**

- Default ASCII QR: web URI
- `--qr-mode web|app|both` (default `web`)
- Keep `--no-qr`

### Static surface and security

Serve only a whitelist:

- `/`, `/index.html`, `/app.js`, `/styles.css`, and optional `/worklet.js` (plus tiny assets if needed, e.g. favicon)

Rules:

- GET/HEAD only
- Unknown paths → 404
- No directory listing, uploads, or path traversal
- WebSocket remains only `/mic`

## Web audio capture and noise control

### Capture pipeline

```text
getUserMedia({
  audio: {
    channelCount: 1,
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true
  }
})
  → MediaStream
  → AudioContext (prefer sampleRate 48000)
  → AudioWorklet (preferred) / ScriptProcessor (fallback)
  → resample to 48000 when context rate differs
  → float32 → pcm_s16le mono
  → ~20 ms binary WebSocket frames
```

### Noise strategy (v1)

| Layer | Behavior |
| --- | --- |
| Required default | `echoCancellation: true` — reduce PC speaker re-pickup |
| Required default | `noiseSuppression: true` — steady ambient noise |
| Default on | `autoGainControl: true` — user can disable in UI |
| UX | Prominent “prefer headphones” guidance; AEC is not perfect |
| Out of v1 | RNNoise / custom DSP |

UI exposes three toggles (default all on), applied via `applyConstraints` or track recreation:

- Echo cancellation
- Noise suppression
- Auto gain

### Format and rate

Protocol fixed: **48000 Hz / mono / pcm_s16le**.

- Prefer `new AudioContext({ sampleRate: 48000 })`
- If browser gives another rate (e.g. 44100): resample to 48000 before send
- `hello` always declares `sampleRate: 48000`, `channels: 1`, `format: "pcm_s16le"`, `version: 1`
- `device` string: `web-android` / `web-ios` / `web-other` from coarse UA detection

### Packetization and gain

- Target ~20 ms packets (960 samples @ 48 kHz ≈ 1920 bytes)
- Bounded send queue: on backlog drop oldest frames to bound latency
- Transmit gain 0%–200%, same idea as mobile `audio_gain` (scale floats, clamp to int16)

### Web client state machine

```text
idle → requesting_mic → connecting → streaming
streaming → paused → streaming
any → error → idle
streaming/paused → stopped → idle
```

- **Pause:** stop capture, send `pause`, keep WebSocket (protocol-compatible)
- **Resume:** send `resume`, re-acquire mic if needed (some browsers invalidate tracks)
- **Stop:** stop tracks, close WebSocket, close AudioContext
- All async callbacks check a session id so stale sessions cannot mutate new state
- Cleanup must be idempotent

### Background best-effort

| Mechanism | Role |
| --- | --- |
| Screen Wake Lock API | Reduce auto lock when supported |
| `visibilitychange` | Warn when hidden; re-check track/WS on visible |
| On-page guidance | Keep page foreground; prefer power connected |
| No promise | iOS Safari often suspends capture when locked/backgrounded |

On suspend/failure: surface a clear error or try one recovery; if recovery fails, require user Start again.

### Minimal UI

- Connection status + error text
- Start / Pause / Stop
- Transmit gain slider
- Three processing toggles
- Local input level meter
- Headphones / foreground tips

### Browser targets

- **Android Chrome:** primary
- **iOS Safari:** best-effort; document AEC/sample-rate/background limits
- Desktop browsers: debug only

## Receiver HTTP and packaging changes

### Same-port HTTP via websockets `process_request`

```text
TCP 8765
├── HTTP GET whitelist → static assets
├── HTTP other → 404
└── WS /mic → MicServer.handler (unchanged validation)
```

No Flask/Starlette in v1 (keep EXE lean).

### Suggested modules

```text
mobile_mic_receiver/
  web_assets/
    index.html
    app.js
    styles.css
    worklet.js          # if AudioWorklet used
  static_http.py        # whitelist, content-types, resource load
  pairing.py            # + build_web_pairing_uri / mode on QR helpers
  server.py             # process_request hook
  controller.py         # expose web pairing URL to GUI/CLI
  gui/app.py            # default web QR
  cli.py                # --qr-mode
```

Load assets with `importlib.resources`, with PyInstaller `sys._MEIPASS` compatibility. Spec/datas must include `web_assets/**`.

### `static_http.py`

- Map path → (resource name, Content-Type)
- GET/HEAD only
- Sensible `Cache-Control` (short cache or no-cache acceptable for v1)
- Reject traversal and unknown paths

### `pairing.py`

- `build_web_pairing_uri(host, port, token)`
- Keep existing `build_pairing_uri` for App
- QR helpers accept `mode="web"|"app"`

### Controller / GUI / CLI

| Piece | Change |
| --- | --- |
| Snapshot | Include web `pairing_url` (and app URI as needed) |
| GUI | Default web QR + copyable URL; Web/App toggle |
| CLI | `--qr-mode web|app|both`, default `web` |
| Settings | Optional `qr_mode` persistence; v1 may hard-default to web |

### Explicit non-changes

- Audio buffer, output device selection, token digest check
- Protocol fields and version
- Flutter app code (except optional dual QR on receiver side)
- Second bind port

## Error handling

| Case | Web client | Receiver |
| --- | --- | --- |
| Mic permission denied | Error + how to allow | No connection |
| `getUserMedia` failure | Show reason; retryable | None |
| Hello timeout / bad ready | Close WS; check PC running | Existing 5s / policy close |
| Wrong password | Show incorrect password | Existing reject |
| Another phone connected | Show busy message | Existing single-client lock |
| Network drop | Error or one reconnect attempt | Clear buffer; disconnected event |
| Page suspended | Prompt; recheck on foreground | Existing underflow behavior |
| Cannot produce 48 kHz PCM | Error after failed resample | Still only accepts 48 kHz hello |
| Missing static asset | Browser 404; App path still works | Log if useful |

## Testing

### Automated (pytest)

- Web pairing URI with/without token; App URI unchanged
- Static whitelist Content-Type; illegal path 404; method restrictions
- HTTP and WS on same port do not break hello/ready
- No path traversal file leak
- Full regression of existing buffer/server/controller/pairing tests

### Web client

- Unit-test pure helpers if extracted (PCM conversion, gain, resample)
- Real mic/WebSocket coverage is primarily manual

### Manual acceptance

1. GUI start → scan web QR → Android Chrome streams → Windows hears audio  
2. Output to VB-CABLE → Discord/meeting app receives voice  
3. PC plays music with AEC on vs off — re-pickup subjectively lower with AEC on  
4. Pause / resume / stop repeatable  
5. Second phone rejected while first connected  
6. Flutter app still works via App QR or manual entry  
7. iOS Safari: document pass/fail and limits  
8. Packaged EXE serves page without source tree  

## Documentation updates

- `README.md` / `README.zh-CN.md`: quick start path for web mic; limitations (foreground, headphones, browser variance)
- `docs/protocol.md`: document HTTP pairing URI alongside `mobilemic://`; note `device` may be `web-*` (frame schema unchanged)

## Implementation sketch (for planning)

1. Pairing helpers + tests for web URI / QR mode  
2. `static_http` + wire into `MicServer.process_request` + tests  
3. Minimal `web_assets` page: connect, hello, PCM stream, gain, toggles  
4. Resample + worklet/fallback path  
5. GUI/CLI default web QR + toggle/mode flag  
6. PyInstaller datas  
7. Docs and manual acceptance  

## Future (explicitly later)

- RNNoise or stronger DSP  
- WSS / better auth for non-LAN  
- Stronger background strategies where platforms allow  
- Optional external static hosting for development convenience  
