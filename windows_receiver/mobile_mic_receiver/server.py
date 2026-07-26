from __future__ import annotations

import asyncio
import json
import secrets
from dataclasses import dataclass

from websockets.exceptions import ConnectionClosed
from websockets.legacy.server import WebSocketServerProtocol, serve

from .buffer import AudioBuffer


@dataclass(frozen=True)
class ServerConfig:
    host: str = '0.0.0.0'
    port: int = 8765
    sample_rate: int = 48000
    channels: int = 1
    token: str = ''


class MicServer:
    def __init__(self, config: ServerConfig, buffer: AudioBuffer) -> None:
        self._config = config
        self._buffer = buffer
        self._client_lock = asyncio.Lock()

    async def _send_error(
        self, websocket: WebSocketServerProtocol, message: str
    ) -> None:
        await websocket.send(json.dumps({'type': 'error', 'message': message}))
        await websocket.close(code=1008, reason=message[:120])

    async def _validate_hello(self, websocket: WebSocketServerProtocol) -> bool:
        try:
            first_message = await asyncio.wait_for(websocket.recv(), timeout=5)
            if not isinstance(first_message, str):
                await self._send_error(websocket, 'First frame must be hello JSON')
                return False
            hello = json.loads(first_message)
        except (asyncio.TimeoutError, json.JSONDecodeError):
            await self._send_error(websocket, 'Invalid or missing hello message')
            return False

        if hello.get('type') != 'hello' or hello.get('version') != 1:
            await self._send_error(websocket, 'Unsupported protocol')
            return False
        if hello.get('sampleRate') != self._config.sample_rate:
            await self._send_error(websocket, 'Sample rate must be 48000 Hz')
            return False
        if hello.get('channels') != self._config.channels:
            await self._send_error(websocket, 'Only mono audio is supported')
            return False
        if hello.get('format') != 'pcm_s16le':
            await self._send_error(websocket, 'Audio format must be pcm_s16le')
            return False
        if self._config.token and not secrets.compare_digest(
            str(hello.get('token', '')), self._config.token
        ):
            await self._send_error(websocket, 'Incorrect connection password')
            return False
        return True

    async def handler(
        self, websocket: WebSocketServerProtocol, path: str
    ) -> None:
        if path != '/mic':
            await self._send_error(websocket, 'Unknown endpoint')
            return
        if self._client_lock.locked():
            await self._send_error(websocket, 'Another phone is already connected')
            return

        async with self._client_lock:
            if not await self._validate_hello(websocket):
                return
            self._buffer.clear()
            print(f'Phone connected: {websocket.remote_address}')
            await websocket.send(json.dumps({'type': 'ready'}))
            try:
                async for message in websocket:
                    if isinstance(message, bytes):
                        self._buffer.write(message)
            except ConnectionClosed:
                pass
            finally:
                self._buffer.clear()
                print('Phone disconnected')

    async def run(self) -> None:
        async with serve(
            self.handler,
            self._config.host,
            self._config.port,
            max_size=None,
            ping_interval=20,
            ping_timeout=20,
        ):
            await asyncio.Future()
