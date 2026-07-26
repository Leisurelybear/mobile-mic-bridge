from __future__ import annotations

import argparse
import asyncio
import socket

from .audio import AudioOutput, list_output_devices
from .buffer import AudioBuffer
from .server import MicServer, ServerConfig


def _local_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        results = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        for result in results:
            address = result[4][0]
            if not address.startswith('127.'):
                addresses.add(address)
    except socket.gaierror:
        pass
    return sorted(addresses)


def _device_value(value: str | None) -> int | str | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Mobile Mic Bridge receiver')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--device', help='Output device index or name')
    parser.add_argument('--token', default='', help='Optional connection password')
    parser.add_argument('--latency-ms', type=int, default=400)
    parser.add_argument('--prebuffer-ms', type=int, default=80)
    parser.add_argument('--list-devices', action='store_true')
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.list_devices:
        for index, name, channels in list_output_devices():
            print(f'{index:>3}  {name} (outputs: {channels})')
        return

    sample_rate = 48000
    channels = 1
    buffer = AudioBuffer(
        sample_rate=sample_rate,
        channels=channels,
        max_latency_ms=args.latency_ms,
        prebuffer_ms=args.prebuffer_ms,
    )
    server = MicServer(
        ServerConfig(
            host=args.host,
            port=args.port,
            sample_rate=sample_rate,
            channels=channels,
            token=args.token,
        ),
        buffer,
    )

    print('Mobile Mic Bridge receiver')
    print(f'Listening on port {args.port}')
    addresses = _local_addresses()
    if addresses:
        print('Enter one of these addresses on the phone:')
        for address in addresses:
            print(f'  {address}')
    else:
        print('Run ipconfig to find this computer IPv4 address.')

    try:
        with AudioOutput(
            buffer,
            device=_device_value(args.device),
            sample_rate=sample_rate,
            channels=channels,
            blocksize=480,
        ):
            asyncio.run(server.run())
    except KeyboardInterrupt:
        print('\nReceiver stopped')


if __name__ == '__main__':
    main()
