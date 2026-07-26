import asyncio
import json
from dataclasses import dataclass, field

import pytest

pytest.importorskip('websockets')

from websockets.asyncio.client import connect

from mobile_mic_receiver.buffer import AudioBuffer
from mobile_mic_receiver.server import MicServer, ServerConfig, ServerEvent


@dataclass
class EventLog:
    events: list[ServerEvent] = field(default_factory=list)

    def __call__(self, event: ServerEvent) -> None:
        self.events.append(event)


def _hello(token: str = 'secret', device: str = 'test-phone') -> str:
    return json.dumps(
        {
            'type': 'hello',
            'version': 1,
            'sampleRate': 48000,
            'channels': 1,
            'format': 'pcm_s16le',
            'token': token,
            'device': device,
        }
    )


def test_run_emits_waiting_and_stops_on_request() -> None:
    async def scenario() -> None:
        log = EventLog()
        buffer = AudioBuffer(sample_rate=48000, channels=1)
        server = MicServer(
            ServerConfig(host='127.0.0.1', port=0, token='secret'),
            buffer,
            on_event=log,
        )
        task = asyncio.create_task(server.run())
        for _ in range(50):
            if any(event.kind == 'waiting' for event in log.events):
                break
            await asyncio.sleep(0.02)
        assert any(event.kind == 'waiting' for event in log.events)
        server.request_stop()
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())


def test_connect_disconnect_events_include_device() -> None:
    async def scenario() -> None:
        log = EventLog()
        buffer = AudioBuffer(sample_rate=48000, channels=1, prebuffer_ms=1)
        server = MicServer(
            ServerConfig(host='127.0.0.1', port=0, token='secret'),
            buffer,
            on_event=log,
        )
        task = asyncio.create_task(server.run())
        for _ in range(50):
            if server.bound_port is not None:
                break
            await asyncio.sleep(0.02)
        port = server.bound_port
        assert port is not None
        async with connect(f'ws://127.0.0.1:{port}/mic') as websocket:
            await websocket.send(_hello(device='Pixel'))
            ready = json.loads(await websocket.recv())
            assert ready['type'] == 'ready'
            for _ in range(50):
                if any(event.kind == 'connected' for event in log.events):
                    break
                await asyncio.sleep(0.02)
        for _ in range(50):
            if any(event.kind == 'disconnected' for event in log.events):
                break
            await asyncio.sleep(0.02)
        connected = next(event for event in log.events if event.kind == 'connected')
        assert connected.device == 'Pixel'
        assert any(event.kind == 'disconnected' for event in log.events)
        server.request_stop()
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())


def test_rejected_event_on_bad_token() -> None:
    async def scenario() -> None:
        log = EventLog()
        buffer = AudioBuffer(sample_rate=48000, channels=1)
        server = MicServer(
            ServerConfig(host='127.0.0.1', port=0, token='secret'),
            buffer,
            on_event=log,
        )
        task = asyncio.create_task(server.run())
        for _ in range(50):
            if server.bound_port is not None:
                break
            await asyncio.sleep(0.02)
        port = server.bound_port
        assert port is not None
        async with connect(f'ws://127.0.0.1:{port}/mic') as websocket:
            await websocket.send(_hello(token='wrong'))
            try:
                await websocket.recv()
            except Exception:
                pass
        for _ in range(50):
            if any(event.kind == 'rejected' for event in log.events):
                break
            await asyncio.sleep(0.02)
        assert any(event.kind == 'rejected' for event in log.events)
        server.request_stop()
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())
