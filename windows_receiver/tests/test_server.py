import asyncio
import json

import pytest

pytest.importorskip('websockets')

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from mobile_mic_receiver.buffer import AudioBuffer
from mobile_mic_receiver.server import MicServer, ServerConfig


class FakeWebSocket:
    def __init__(self, first_message: str) -> None:
        self.first_message = first_message
        self.sent: list[str] = []
        self.closed: tuple[int, str] | None = None

    async def recv(self) -> str:
        return self.first_message

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def close(self, *, code: int, reason: str) -> None:
        self.closed = (code, reason)


def make_server() -> MicServer:
    buffer = AudioBuffer(sample_rate=48000, channels=1)
    return MicServer(ServerConfig(token='secret'), buffer)


def test_accepts_valid_hello() -> None:
    websocket = FakeWebSocket(
        json.dumps(
            {
                'type': 'hello',
                'version': 1,
                'sampleRate': 48000,
                'channels': 1,
                'format': 'pcm_s16le',
                'token': 'secret',
            }
        )
    )
    assert asyncio.run(make_server()._validate_hello(websocket)) is True
    assert websocket.closed is None


def test_rejects_non_object_hello() -> None:
    websocket = FakeWebSocket('[]')
    assert asyncio.run(make_server()._validate_hello(websocket)) is False
    assert websocket.closed is not None
    assert 'JSON object' in websocket.sent[0]


def test_rejects_incorrect_password() -> None:
    websocket = FakeWebSocket(
        json.dumps(
            {
                'type': 'hello',
                'version': 1,
                'sampleRate': 48000,
                'channels': 1,
                'format': 'pcm_s16le',
                'token': 'wrong',
            }
        )
    )
    assert asyncio.run(make_server()._validate_hello(websocket)) is False
    assert websocket.closed is not None


def test_websocket_round_trip_preserves_split_sample() -> None:
    async def scenario() -> None:
        buffer = AudioBuffer(sample_rate=48000, channels=1, prebuffer_ms=1)
        server = MicServer(ServerConfig(token='secret'), buffer)
        async with serve(server.handler, '127.0.0.1', 0) as running_server:
            port = running_server.sockets[0].getsockname()[1]
            async with connect(f'ws://127.0.0.1:{port}/mic') as websocket:
                await websocket.send(
                    json.dumps(
                        {
                            'type': 'hello',
                            'version': 1,
                            'sampleRate': 48000,
                            'channels': 1,
                            'format': 'pcm_s16le',
                            'token': 'secret',
                        }
                    )
                )
                response = json.loads(await websocket.recv())
                assert response['type'] == 'ready'
                await websocket.send(b'\x01')
                await websocket.send(b'\x00')
                await asyncio.sleep(0.01)
                assert buffer.stats().queued_bytes == 2

    asyncio.run(scenario())
