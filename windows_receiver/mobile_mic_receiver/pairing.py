from __future__ import annotations

import sys
from urllib.parse import urlencode


def build_pairing_uri(*, host: str, port: int, token: str) -> str:
    parameters = {'host': host, 'port': str(port)}
    if token:
        parameters['token'] = token
    return f'mobilemic://connect?{urlencode(parameters)}'


def print_pairing_qr(*, host: str, port: int, token: str) -> None:
    import qrcode

    pairing_uri = build_pairing_uri(host=host, port=port, token=token)
    code = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=1,
        border=4,
    )
    code.add_data(pairing_uri)
    code.make(fit=True)
    print('Scan this QR code in the mobile app:')
    code.print_ascii(out=sys.stdout, tty=False, invert=True)
    print(f'Pairing URI: {pairing_uri}')
