from __future__ import annotations

import sys
from pathlib import Path

from websockets.datastructures import Headers
from websockets.http11 import Response

STATIC_ROUTES: dict[str, tuple[str, str]] = {
    '/': ('index.html', 'text/html; charset=utf-8'),
    '/index.html': ('index.html', 'text/html; charset=utf-8'),
    '/app.js': ('app.js', 'application/javascript; charset=utf-8'),
    '/styles.css': ('styles.css', 'text/css; charset=utf-8'),
    '/worklet.js': ('worklet.js', 'application/javascript; charset=utf-8'),
}


def resolve_static(path: str) -> tuple[str, str] | None:
    raw = path.split('?', 1)[0]
    if raw != '/' and raw.endswith('/'):
        raw = raw.rstrip('/')
    return STATIC_ROUTES.get(raw)


def asset_root() -> Path:
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / 'mobile_mic_receiver' / 'web_assets'
    return Path(__file__).resolve().parent / 'web_assets'


def load_asset(filename: str) -> bytes:
    if '/' in filename or '\\' in filename or '..' in filename:
        raise FileNotFoundError(filename)
    path = asset_root() / filename
    return path.read_bytes()


def handle_http(path: str, method: str) -> Response | None:
    resolved = resolve_static(path)
    if resolved is None:
        return None
    filename, content_type = resolved
    upper = method.upper()
    if upper not in {'GET', 'HEAD'}:
        return Response(
            405,
            'Method Not Allowed',
            Headers(
                [
                    ('Content-Type', 'text/plain; charset=utf-8'),
                    ('Allow', 'GET, HEAD'),
                    ('Connection', 'close'),
                ]
            ),
            b'Method Not Allowed',
        )
    try:
        data = load_asset(filename)
    except OSError:
        return Response(
            404,
            'Not Found',
            Headers(
                [
                    ('Content-Type', 'text/plain; charset=utf-8'),
                    ('Connection', 'close'),
                ]
            ),
            b'Not Found',
        )
    body = b'' if upper == 'HEAD' else data
    return Response(
        200,
        'OK',
        Headers(
            [
                ('Content-Type', content_type),
                ('Content-Length', str(len(data))),
                ('Cache-Control', 'no-cache'),
                ('Connection', 'close'),
            ]
        ),
        body,
    )
