from pathlib import Path

from mobile_mic_receiver.tls_certs import (
    build_server_ssl_context,
    ensure_tls_material,
)


def test_ensure_tls_material_creates_cert_and_key(tmp_path: Path) -> None:
    cert_path, key_path = ensure_tls_material(
        tmp_path,
        hosts=('127.0.0.1', '192.168.1.20'),
    )
    assert cert_path.is_file()
    assert key_path.is_file()
    assert cert_path.read_bytes()
    assert key_path.read_bytes()


def test_ensure_tls_material_reuses_existing(tmp_path: Path) -> None:
    first_cert, first_key = ensure_tls_material(
        tmp_path, hosts=('127.0.0.1',)
    )
    cert_bytes = first_cert.read_bytes()
    key_bytes = first_key.read_bytes()
    second_cert, second_key = ensure_tls_material(
        tmp_path, hosts=('127.0.0.1',)
    )
    assert second_cert == first_cert
    assert second_key == first_key
    assert second_cert.read_bytes() == cert_bytes
    assert second_key.read_bytes() == key_bytes


def test_build_server_ssl_context_loads(tmp_path: Path) -> None:
    cert_path, key_path = ensure_tls_material(
        tmp_path, hosts=('127.0.0.1',)
    )
    context = build_server_ssl_context(cert_path=cert_path, key_path=key_path)
    assert context is not None
