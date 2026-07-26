# Mobile Mic Bridge

[中文文档](README.zh-CN.md)

Use an Android or iOS phone as a low-latency Wi-Fi microphone for a Windows PC.

The mobile app captures mono PCM audio and streams it over a WebSocket on the local network. The Windows receiver plays that stream to a selected output device. To expose the stream as a microphone to Discord, OBS, games, meeting software, or a browser, select a virtual audio cable as the receiver output.

## Features

- One Flutter sender for Android and iOS
- 48 kHz, mono, signed 16-bit PCM transport
- Bounded jitter buffer with underflow recovery
- Optional connection password
- Automatic Windows receiver discovery with mDNS/DNS-SD
- QR-code pairing fallback when mDNS is unavailable
- Remembers the last receiver address, port, and transmit gain
- Phone-side transmit gain from 0% to 200%
- Repeatable pause and resume without reconnecting
- Selectable Windows output device
- Automatic Android APK, unsigned iOS app archive, and Windows x64/ARM64 EXE releases
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

1. Install Python 3.10 or newer.
2. Install a virtual audio cable. With VB-CABLE, the receiver sends audio to `CABLE Input`, while voice applications select `CABLE Output` as their microphone.
3. Open PowerShell in `windows_receiver`.
4. Create the environment and install the receiver:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

5. Find the virtual cable output device:

```powershell
mobile-mic-receiver --list-devices
```

6. Start the receiver using the displayed device index:

```powershell
mobile-mic-receiver --device 12 --token choose-a-password
```

Allow TCP port `8765` when Windows Firewall asks. The receiver prints the local IPv4 addresses that can be entered on the phone.

### 2. Build the Mobile App

Install Flutter, then run:

```powershell
cd mobile_app
.\tool\bootstrap.ps1
flutter run
```

An iOS build requires macOS, Xcode, an Apple developer team, and normal code signing. Android can be built on Windows, macOS, or Linux.

### 3. Connect

1. Put the phone and PC on the same Wi-Fi network.
2. Select the discovered PC, scan the QR code printed by Windows, or enter its IPv4 address and port `8765` manually.
3. Tap `开始传输`.
4. In the target Windows application, choose the virtual cable output as the microphone.

The app keeps the screen awake while streaming. Moving it to the background still stops the current MVP session. Use headphones to prevent the PC speakers from feeding back into the phone microphone.

The volume slider changes the PCM level sent to Windows. `100%` preserves the captured level, `0%` mutes it, and values above `100%` may clip loud samples.

The app remembers the last host, port, and gain. The connection password is intentionally kept only for the current app session and is not persisted.

## Receiver Options

```text
--host            Bind address, default 0.0.0.0
--port            WebSocket port, default 8765
--device          Output device index or name
--token           Optional connection password
--latency-ms      Maximum buffered audio, default 400
--prebuffer-ms    Startup and recovery buffer, default 80
--no-discovery    Disable mDNS advertisement
--no-qr           Do not print the terminal pairing QR code
--list-devices    List output devices and exit
```

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

The wire protocol is documented in `docs/protocol.md`.

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
