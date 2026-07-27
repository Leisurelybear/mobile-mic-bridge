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
        setup_completed=True,
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


def test_setup_completed_defaults_false(tmp_path: Path) -> None:
    path = tmp_path / 'settings.json'
    path.write_text('{"token": "x"}', encoding='utf-8')
    loaded = load_settings(path)
    assert loaded.setup_completed is False
