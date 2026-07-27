from __future__ import annotations

import sys
from urllib.parse import urlencode


def build_pairing_uri(*, host: str, port: int, token: str) -> str:
    parameters = {'host': host, 'port': str(port)}
    if token:
        parameters['token'] = token
    return f'mobilemic://connect?{urlencode(parameters)}'


def build_web_pairing_uri(
    *, host: str, port: int, token: str, scheme: str = 'https'
) -> str:
    scheme_name = (scheme or 'https').lower()
    if scheme_name not in {'http', 'https'}:
        raise ValueError(f'unsupported web pairing scheme: {scheme}')
    base = f'{scheme_name}://{host}:{port}/'
    if not token:
        return base
    return f'{base}?{urlencode({"token": token})}'


def _pairing_data(
    *, host: str, port: int, token: str, mode: str, scheme: str = 'https'
) -> str:
    if mode == 'app':
        return build_pairing_uri(host=host, port=port, token=token)
    if mode == 'web':
        return build_web_pairing_uri(
            host=host, port=port, token=token, scheme=scheme
        )
    raise ValueError(f'unsupported pairing mode: {mode}')


def make_qr_image(
    *,
    host: str,
    port: int,
    token: str,
    box_size: int = 6,
    mode: str = 'web',
    scheme: str = 'https',
):
    import qrcode
    from PIL import Image

    pairing_uri = _pairing_data(
        host=host, port=port, token=token, mode=mode, scheme=scheme
    )
    code = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=2,
    )
    code.add_data(pairing_uri)
    code.make(fit=True)
    image = code.make_image(fill_color='black', back_color='white')
    if not isinstance(image, Image.Image):
        image = image.get_image()
    return image.convert('RGB')


def print_pairing_qr(
    *,
    host: str,
    port: int,
    token: str,
    mode: str = 'web',
    scheme: str = 'https',
) -> None:
    import qrcode

    modes = ['web', 'app'] if mode == 'both' else [mode]
    for item in modes:
        pairing_uri = _pairing_data(
            host=host, port=port, token=token, mode=item, scheme=scheme
        )
        code = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=1,
            border=4,
        )
        code.add_data(pairing_uri)
        code.make(fit=True)
        label = (
            'Scan this QR code in the phone browser:'
            if item == 'web'
            else 'Scan this QR code in the mobile app:'
        )
        print(label)
        code.print_ascii(out=sys.stdout, tty=False, invert=True)
        print(f'Pairing URI: {pairing_uri}')
