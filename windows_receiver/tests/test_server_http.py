import asyncio
import json
from urllib.request import urlopen

import pytest

pytest.importorskip('websockets')

from websockets.asyncio.client import connect

from mobile_mic_receiver.buffer import AudioBuffer
from mobile_mic_receiver.server import MicServer, ServerConfig


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


async def _start_server(token: str = 'secret') -> tuple[MicServer, asyncio.Task, int]:
    buffer = AudioBuffer(sample_rate=48000, channels=1, prebuffer_ms=1)
    server = MicServer(
        ServerConfig(host='127.0.0.1', port=0, token=token),
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
