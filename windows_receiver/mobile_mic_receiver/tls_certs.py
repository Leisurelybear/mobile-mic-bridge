from __future__ import annotations

import ipaddress
import os
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def default_tls_dir() -> Path:
    appdata = os.environ.get('APPDATA')
    root = Path(appdata) if appdata else Path.home()
    return root / 'MobileMicBridge' / 'tls'


def ensure_tls_material(
    directory: Path | None = None,
    *,
    hosts: tuple[str, ...] = ('127.0.0.1',),
) -> tuple[Path, Path]:
    """Create or reuse a self-signed server certificate for LAN HTTPS/WSS."""
    target = directory or default_tls_dir()
    target.mkdir(parents=True, exist_ok=True)
    cert_path = target / 'server.crt'
    key_path = target / 'server.key'
    if cert_path.is_file() and key_path.is_file():
        return cert_path, key_path

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, 'Mobile Mic Bridge'),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'Mobile Mic Bridge'),
        ]
    )
    san_entries: list[x509.GeneralName] = [
        x509.DNSName('localhost'),
        x509.DNSName('mobile-mic.local'),
    ]
    seen_ips: set[str] = set()
    for host in hosts:
        value = (host or '').strip()
        if not value or value in seen_ips:
            continue
        seen_ips.add(value)
        try:
            san_entries.append(x509.IPAddress(ipaddress.ip_address(value)))
        except ValueError:
            san_entries.append(x509.DNSName(value))
    if '127.0.0.1' not in seen_ips:
        san_entries.append(x509.IPAddress(ipaddress.IPv4Address('127.0.0.1')))

    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None), critical=True
        )
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def build_server_ssl_context(
    *, cert_path: Path, key_path: Path
) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    return context
