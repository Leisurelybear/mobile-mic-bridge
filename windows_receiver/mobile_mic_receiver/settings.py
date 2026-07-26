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


def save_settings(
    settings: ReceiverSettings, path: Path | None = None
) -> None:
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
