# Mobile Mic Bridge

[中文文档](README.zh-CN.md)

Use an Android or iOS phone as a low-latency Wi-Fi microphone for a Windows PC.

The mobile app or the **built-in browser page** captures mono PCM audio and streams it over a WebSocket on the local network. The Windows receiver plays that stream to a selected output device. To expose the stream as a microphone to Discord, OBS, games, meeting software, or a browser, select a virtual audio cable as the receiver output.

## Features

- One Flutter sender for Android and iOS
- **Browser web client** hosted by the Windows receiver (scan QR, no app install)
- 48 kHz, mono, signed 16-bit PCM transport
- Bounded jitter buffer with underflow recovery
- Optional connection password
- Automatic Windows receiver discovery with mDNS/DNS-SD
- Windows GUI receiver with in-window pairing QR and level meters
- QR-code pairing for the web page (default) or Flutter app
- Remembers the last receiver address, port, and transmit gain
- Phone-side transmit gain from 0% to 200%
- Repeatable pause and resume without reconnecting
- Selectable Windows output device
- Automatic Android APK, unsigned iOS app archive, and Windows x64/ARM64 GUI EXE releases
- English and Chinese documentation

## Architecture

```text
Phone microphone
      |
      | PCM16 over WebSocket / Wi-Fi
      v
Windows receiver
      |
      | audio output
      v
Virtual cable input  ->  Virtual cable output  ->  Windows microphone app
```

The virtual cable is required because normal Windows applications cannot create a system microphone endpoint without a signed audio driver. This project intentionally stays in user space and works with products such as VB-CABLE or equivalent virtual audio devices.

## Quick Start

### 1. Prepare Windows

1. Install a virtual audio cable. With VB-CABLE, the receiver sends audio to `CABLE Input`, while voice applications select `CABLE Output` as their microphone.
2. Download `mobile-mic-receiver-windows-x64.exe` from [Releases](https://github.com/Leisurelybear/mobile-mic-bridge/releases) (use the ARM64 build on ARM PCs).
3. Double-click the GUI receiver (or run `.\start-receiver.ps1`). A **setup wizard** opens on first launch.
4. Follow the wizard to install/detect VB-CABLE and auto-select `CABLE Input`. You can reopen **快速设置向导** anytime from the main window.
5. Set a connection password and click **Start**.
6. Allow TCP port `8765` when Windows Firewall asks.
7. The window shows local addresses and a **web pairing QR code** (`https://...:8765/`). On first open, accept the self-signed certificate warning in the phone browser.
8. In Discord/games/meetings, set the microphone to **CABLE Output**.

Settings are stored at `%APPDATA%\MobileMicBridge\settings.json`, including the connection password in plain text for local convenience (not a secure vault).

#### Developers: run from source

Root launchers create/use `windows_receiver/.venv` and install deps if needed:

```powershell
# GUI (default, web pairing QR)
.\start-receiver.ps1
# or double-click
.\start-receiver.bat

# Console receiver
.\start-receiver.ps1 -Cli -ListDevices
.\start-receiver.ps1 -Cli -Device 12 -Token choose-a-password

# Force recreate venv and reinstall
.\start-receiver.ps1 -Rebuild
```

After the first run you can also call:

```powershell
.\windows_receiver\.venv\Scripts\mobile-mic-receiver-gui.exe
.\windows_receiver\.venv\Scripts\mobile-mic-receiver.exe --list-devices
```

Manual steps:

```powershell
cd windows_receiver
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
mobile-mic-receiver-gui
```

### 2. Connect with the phone browser (recommended, no app install)

1. Put the phone and PC on the same Wi-Fi network.
2. Scan the **网页** QR code in the Windows window (or open `https://PC-IP:8765/?token=...`). Accept the certificate warning once if prompted.
3. Allow microphone access, keep the page in the foreground, and tap **开始传输**.
4. Prefer headphones so PC speaker audio is less likely to re-enter the phone mic. Browser echo cancellation / noise suppression / AGC are on by default.
5. In the target Windows application, choose the virtual cable output as the microphone.

Browser background capture is **best-effort** only. Locking the screen or switching apps may stop audio, especially on iOS Safari. The connection password from the QR query string stays in page memory for the session and is not stored.

### 3. Or build the Flutter mobile app

Install Flutter, then run:

```powershell
cd mobile_app
.\tool\bootstrap.ps1
flutter run
```

An iOS build requires macOS, Xcode, an Apple developer team, and normal code signing. Android can be built on Windows, macOS, or Linux.

In the Windows GUI, switch the QR mode to **App** (or use `--qr-mode app`) to show the `mobilemic://` pairing code.

1. Put the phone and PC on the same Wi-Fi network.
2. Select the discovered PC, scan the App QR code, or enter its IPv4 address and port `8765` manually.
3. Tap `开始传输`.
4. In the target Windows application, choose the virtual cable output as the microphone.

The Flutter app keeps streaming while it is backgrounded or the screen is locked. Android shows an ongoing microphone notification; iOS uses the audio background mode. User-paused sessions remain paused, and force-stop, swipe-away, or process termination ends the session. Use headphones to prevent the PC speakers from feeding back into the phone microphone.

The volume slider changes the PCM level sent to Windows. `100%` preserves the captured level, `0%` mutes it, and values above `100%` may clip loud samples.

The app remembers the last host, port, and gain. The connection password is intentionally kept only for the current app session and is not persisted.

## Receiver CLI Options

The developer console entry `mobile-mic-receiver` supports:

```text
--host            Bind address, default 0.0.0.0
--port            WebSocket port, default 8765
--device          Output device index or name
--token           Optional connection password
--latency-ms      Maximum buffered audio, default 400
--prebuffer-ms    Startup and recovery buffer, default 80
--no-discovery    Disable mDNS advertisement
--no-qr           Do not print the terminal pairing QR code
--qr-mode         web|app|both (default web page URL)
--no-tls          Disable HTTPS/WSS (phones usually cannot open mic over plain HTTP)
--list-devices    List output devices and exit
```

The GUI exposes the same port, password, latency, prebuffer, and mDNS controls, plus a Web/App QR toggle.

Lower `--prebuffer-ms` reduces latency but increases crackling risk on unstable Wi-Fi. Values between 60 and 120 ms are practical starting points.
`--prebuffer-ms` must not exceed `--latency-ms`.

## Security

- The stream is intended for a trusted local network.
- The default `ws://` transport is not encrypted.
- Set `--token` to prevent accidental connections by other devices on the LAN.
- Do not expose port `8765` directly to the internet.
- A future internet-facing mode should use TLS, stronger authentication, and an encoded transport such as Opus.

## Development

Run receiver tests:

```powershell
cd windows_receiver
python -m pip install -e .[test]
python -m pytest -q
```

Run Flutter checks after bootstrapping platform files:

```powershell
cd mobile_app
flutter analyze
flutter test
```

The wire protocol is documented in `docs/protocol.md`. Mobile background recording behavior and limitations are documented in `docs/background-audio-spec.md`. LAN PCM remains unencrypted; the token controls access but does not encrypt audio.

## Releases

Push a tag such as `v0.1.0` to trigger `.github/workflows/release.yml`. The workflow publishes:

- Android universal release APK
- Windows standalone receiver EXE for x64
- Windows standalone receiver EXE for ARM64
- Unsigned iOS Runner app archive for later signing on macOS

GitHub Actions cannot produce an installable signed iOS IPA without repository-specific Apple signing certificates and provisioning profiles.

## Limitations

- One phone can connect at a time.
- Audio is uncompressed PCM, so typical bandwidth is about 768 kbit/s before WebSocket overhead.
- The current transport is optimized for a local Wi-Fi network, not the public internet.
- Windows microphone exposure depends on a separately installed virtual audio cable.
- The browser web client requires HTTPS on most phones; the receiver enables self-signed TLS by default. Accept the certificate warning once.
- The browser web client does not guarantee background or lock-screen capture; keep the page foreground when possible.
- Browser echo cancellation quality varies by device and OS; headphones are still recommended.
- iOS Safari support is best-effort compared with Android Chrome.
