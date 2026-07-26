from __future__ import annotations

import argparse
import asyncio

from .audio import AudioOutput, list_output_devices
from .buffer import AudioBuffer
from .discovery import MdnsAdvertiser, local_ipv4_addresses
from .pairing import print_pairing_qr
from .server import MicServer, ServerConfig


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
    parser.add_argument('--no-discovery', action='store_true')
    parser.add_argument('--no-qr', action='store_true')
    parser.add_argument('--list-devices', action='store_true')
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.list_devices:
        for index, name, channels in list_output_devices():
            print(f'{index:>3}  {name} (outputs: {channels})')
        return
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    if args.latency_ms <= 0:
        parser.error('--latency-ms must be positive')
    if args.prebuffer_ms <= 0:
        parser.error('--prebuffer-ms must be positive')
    if args.prebuffer_ms > args.latency_ms:
        parser.error('--prebuffer-ms cannot exceed --latency-ms')

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
    if not args.token:
        print('Warning: no connection password is configured')
    addresses = local_ipv4_addresses()
    if addresses:
        print('Enter one of these addresses on the phone:')
        for address in addresses:
            print(f'  {address}')
    else:
        print('Run ipconfig to find this computer IPv4 address.')
    if addresses and not args.no_qr:
        try:
            print_pairing_qr(
                host=addresses[0],
                port=args.port,
                token=args.token,
            )
        except Exception as error:
            print(f'Warning: pairing QR unavailable: {error}')

    advertiser = MdnsAdvertiser(port=args.port)
    if not args.no_discovery:
        try:
            advertiser.start()
            print('Automatic discovery enabled: _mobilemic._tcp.local')
        except Exception as error:
            print(f'Warning: automatic discovery unavailable: {error}')

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
    finally:
        advertiser.close()


if __name__ == '__main__':
    main()
