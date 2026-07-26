from __future__ import annotations

import re
import socket
from typing import Any

SERVICE_TYPE = '_mobilemic._tcp.local.'


def local_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()
    primary_address: str | None = None
    route_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        route_socket.connect(('8.8.8.8', 80))
        route_address = route_socket.getsockname()[0]
        if not route_address.startswith('127.'):
            primary_address = route_address
            addresses.add(route_address)
    except OSError:
        pass
    finally:
        route_socket.close()
    try:
        results = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        for result in results:
            address = result[4][0]
            if not address.startswith('127.'):
                addresses.add(address)
    except socket.gaierror:
        pass
    remaining = sorted(address for address in addresses if address != primary_address)
    return ([primary_address] if primary_address is not None else []) + remaining


def _server_hostname() -> str:
    hostname = socket.gethostname().strip() or 'mobile-mic-receiver'
    normalized = re.sub(r'[^A-Za-z0-9-]', '-', hostname).strip('-')
    return normalized or 'mobile-mic-receiver'


class MdnsAdvertiser:
    def __init__(self, *, port: int) -> None:
        self._port = port
        self._zeroconf: Any = None
        self._service_info: Any = None

    def start(self) -> None:
        from zeroconf import IPVersion, ServiceInfo, Zeroconf

        addresses = local_ipv4_addresses()
        if not addresses:
            raise RuntimeError('No local IPv4 address is available for discovery')

        display_name = socket.gethostname().strip() or 'Mobile Mic Receiver'
        server = f'{_server_hostname()}.local.'
        service_info = ServiceInfo(
            SERVICE_TYPE,
            f'{display_name}.{SERVICE_TYPE}',
            addresses=[socket.inet_aton(address) for address in addresses],
            port=self._port,
            properties={
                b'version': b'1',
                b'sampleRate': b'48000',
                b'channels': b'1',
                b'format': b'pcm_s16le',
            },
            server=server,
        )
        zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
        try:
            zeroconf.register_service(service_info, allow_name_change=True)
        except Exception:
            zeroconf.close()
            raise
        self._zeroconf = zeroconf
        self._service_info = service_info

    def close(self) -> None:
        zeroconf = self._zeroconf
        service_info = self._service_info
        self._zeroconf = None
        self._service_info = None
        if zeroconf is None:
            return
        try:
            if service_info is not None:
                zeroconf.unregister_service(service_info)
        finally:
            zeroconf.close()
