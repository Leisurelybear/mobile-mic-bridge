from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from .buffer import AudioBuffer


@dataclass(frozen=True)
class ServerConfig:
    host: str = '0.0.0.0'
    port: int = 8765
    sample_rate: int = 48000
    channels: int = 1
    token: str = ''


@dataclass(frozen=True)
class ServerEvent:
    kind: str
    message: str = ''
    device: str = ''
    remote: str = ''


class MicServer:
    def __init__(
        self,
        config: ServerConfig,
        buffer: AudioBuffer,
        on_event: Callable[[ServerEvent], None] | None = None,
    ) -> None:
        self._config = config
        self._buffer = buffer
        self._on_event = on_event or (lambda _event: None)
        self._client_lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self.bound_port: int | None = None

    def _emit(self, kind: str, **kwargs: str) -> None:
        self._on_event(ServerEvent(kind=kind, **kwargs))

    def request_stop(self) -> None:
        loop = self._loop
        stop_event = self._stop_event
        if loop is None or stop_event is None:
            return
        loop.call_soon_threadsafe(stop_event.set)

    async def _send_error(
        self, websocket: ServerConnection, message: str
    ) -> None:
        self._emit('rejected', message=message)
        await websocket.send(json.dumps({'type': 'error', 'message': message}))
        await websocket.close(code=1008, reason=message[:120])

    async def _validate_hello(
        self, websocket: ServerConnection
    ) -> tuple[bool, str]:
        try:
            first_message = await asyncio.wait_for(websocket.recv(), timeout=5)
            if not isinstance(first_message, str):
                await self._send_error(websocket, 'First frame must be hello JSON')
                return False, ''
            hello = json.loads(first_message)
        except (asyncio.TimeoutError, json.JSONDecodeError):
            await self._send_error(websocket, 'Invalid or missing hello message')
            return False, ''

        if not isinstance(hello, dict):
            await self._send_error(websocket, 'Hello message must be a JSON object')
            return False, ''
        if hello.get('type') != 'hello' or hello.get('version') != 1:
            await self._send_error(websocket, 'Unsupported protocol')
            return False, ''
        if hello.get('sampleRate') != self._config.sample_rate:
            await self._send_error(websocket, 'Sample rate must be 48000 Hz')
            return False, ''
        if hello.get('channels') != self._config.channels:
            await self._send_error(websocket, 'Only mono audio is supported')
            return False, ''
        if hello.get('format') != 'pcm_s16le':
            await self._send_error(websocket, 'Audio format must be pcm_s16le')
            return False, ''
        if self._config.token and not secrets.compare_digest(
            str(hello.get('token', '')), self._config.token
        ):
            await self._send_error(websocket, 'Incorrect connection password')
            return False, ''
        return True, str(hello.get('device', '') or '')

    async def handler(self, websocket: ServerConnection) -> None:
        if websocket.request.path != '/mic':
            await self._send_error(websocket, 'Unknown endpoint')
            return
        if self._client_lock.locked():
            await self._send_error(websocket, 'Another phone is already connected')
            return

        async with self._client_lock:
            ok, device = await self._validate_hello(websocket)
            if not ok:
                return
            self._buffer.clear()
            remote = str(websocket.remote_address)
            print(f'Phone connected: {websocket.remote_address}')
            self._emit('connected', device=device, remote=remote)
            await websocket.send(json.dumps({'type': 'ready'}))
            try:
                async for message in websocket:
                    if isinstance(message, bytes):
                        self._buffer.write(message)
                    elif self._is_buffer_reset_message(message):
                        self._buffer.clear()
            except ConnectionClosed:
                pass
            finally:
                self._buffer.clear()
                print('Phone disconnected')
                self._emit('disconnected')

    def _is_buffer_reset_message(self, message: str) -> bool:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return False
        return isinstance(payload, dict) and payload.get('type') in {
            'pause',
            'resume',
        }

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        try:
            async with serve(
                self.handler,
                self._config.host,
                self._config.port,
                max_size=256 * 1024,
                max_queue=8,
                ping_interval=20,
                ping_timeout=20,
            ) as ws_server:
                sockets = getattr(ws_server, 'sockets', None) or []
                if sockets:
                    self.bound_port = int(sockets[0].getsockname()[1])
                else:
                    self.bound_port = self._config.port
                self._emit('waiting')
                await self._stop_event.wait()
        finally:
            self.bound_port = None
            self._loop = None
            self._stop_event = None
