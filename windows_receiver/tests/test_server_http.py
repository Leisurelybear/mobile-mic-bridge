import asyncio
import json
import ssl
from pathlib import Path
from urllib.request import urlopen

import pytest

pytest.importorskip('websockets')

from websockets.asyncio.client import connect

from mobile_mic_receiver.buffer import AudioBuffer
from mobile_mic_receiver.server import MicServer, ServerConfig
from mobile_mic_receiver.tls_certs import ensure_tls_material


def _hello(token: str = 'secret') -> str:
    return json.dumps(
        {
            'type': 'hello',
            'version': 1,
            'sampleRate': 48000,
            'channels': 1,
            'format': 'pcm_s16le',
            'token': token,
            'device': 'web-other',
        }
    )


async def _start_server(
    token: str = 'secret',
    *,
    tls: bool = False,
    cert_dir: Path | None = None,
) -> tuple[MicServer, asyncio.Task, int]:
    buffer = AudioBuffer(sample_rate=48000, channels=1, prebuffer_ms=1)
    cert_path = ''
    key_path = ''
    if tls:
        assert cert_dir is not None
        cert_file, key_file = ensure_tls_material(
            cert_dir, hosts=('127.0.0.1',)
        )
        cert_path = str(cert_file)
        key_path = str(key_file)
    server = MicServer(
        ServerConfig(
            host='127.0.0.1',
            port=0,
            token=token,
            tls_enabled=tls,
            tls_cert_path=cert_path,
            tls_key_path=key_path,
        ),
        buffer,
    )
    task = asyncio.create_task(server.run())
    for _ in range(100):
        if server.bound_port is not None:
            break
        await asyncio.sleep(0.02)
    assert server.bound_port is not None
    return server, task, server.bound_port


def test_http_get_index_and_websocket_mic() -> None:
    async def scenario() -> None:
        server, task, port = await _start_server()
        try:
            def fetch() -> bytes:
                with urlopen(f'http://127.0.0.1:{port}/', timeout=2) as resp:
                    assert resp.status == 200
                    return resp.read()

            body = await asyncio.to_thread(fetch)
            assert b'Mobile Mic Bridge' in body

            async with connect(f'ws://127.0.0.1:{port}/mic') as ws:
                await ws.send(_hello())
                ready = json.loads(await ws.recv())
                assert ready['type'] == 'ready'
                await ws.send(b'\x01\x00')
        finally:
            server.request_stop()
            await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())


def test_http_unknown_path_is_404() -> None:
    async def scenario() -> None:
        server, task, port = await _start_server()
        try:
            def fetch_status() -> int:
                try:
                    urlopen(f'http://127.0.0.1:{port}/nope', timeout=2)
                    return 200
                except Exception as exc:  # urllib HTTPError
                    return getattr(exc, 'code', 0)

            status = await asyncio.to_thread(fetch_status)
            assert status == 404
        finally:
            server.request_stop()
            await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())


def test_https_get_index_and_wss_mic(tmp_path: Path) -> None:
    async def scenario() -> None:
        server, task, port = await _start_server(tls=True, cert_dir=tmp_path)
        try:
            def fetch() -> bytes:
                ctx = ssl._create_unverified_context()
                with urlopen(
                    f'https://127.0.0.1:{port}/', timeout=2, context=ctx
                ) as resp:
                    assert resp.status == 200
                    return resp.read()

            body = await asyncio.to_thread(fetch)
            assert b'Mobile Mic Bridge' in body

            ssl_ctx = ssl._create_unverified_context()
            async with connect(
                f'wss://127.0.0.1:{port}/mic', ssl=ssl_ctx
            ) as ws:
                await ws.send(_hello())
                ready = json.loads(await ws.recv())
                assert ready['type'] == 'ready'
                await ws.send(b'\x01\x00')
        finally:
            server.request_stop()
            await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())
