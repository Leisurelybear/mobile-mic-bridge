from __future__ import annotations

import array
import threading
import time
from dataclasses import dataclass
from .audio import AudioOutput
from .buffer import AudioBuffer, BufferStats
from .discovery import MdnsAdvertiser, local_ipv4_addresses
from .pairing import build_pairing_uri, build_web_pairing_uri
from .server import MicServer, ServerConfig, ServerEvent
from .tls_certs import default_tls_dir, ensure_tls_material


@dataclass(frozen=True)
class ControllerConfig:
    device: int | str | None
    host: str = '0.0.0.0'
    port: int = 8765
    token: str = ''
    latency_ms: int = 400
    prebuffer_ms: int = 80
    discovery_enabled: bool = True
    tls_enabled: bool = True


@dataclass(frozen=True)
class ControllerSnapshot:
    running: bool
    status: str
    client_label: str
    last_error: str
    warning: str
    peak: float
    queued_ms: float
    underflows: int
    buffering: bool
    local_addresses: tuple[str, ...]
    pairing_uri: str
    app_pairing_uri: str
    bound_port: int | None
    tls_enabled: bool
    tls_cert_path: str


class _PeakBuffer:
    def __init__(
        self,
        inner: AudioBuffer,
        peak_holder: list[float],
        lock: threading.Lock,
    ) -> None:
        self._inner = inner
        self._peak_holder = peak_holder
        self._lock = lock

    def write(self, data: bytes) -> None:
        if data:
            samples = array.array('h')
            samples.frombytes(data[: len(data) - (len(data) % 2)])
            if samples:
                peak = max(abs(sample) for sample in samples) / 32768.0
                with self._lock:
                    self._peak_holder[0] = max(peak, self._peak_holder[0] * 0.85)
        self._inner.write(data)

    def read(self, frames: int) -> bytes:
        return self._inner.read(frames)

    def clear(self) -> None:
        self._inner.clear()

    def stats(self) -> BufferStats:
        return self._inner.stats()


class ReceiverController:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._server: MicServer | None = None
        self._stop_requested = threading.Event()
        self._running = False
        self._status = 'stopped'
        self._client_label = ''
        self._last_error = ''
        self._warning = ''
        self._peak = [0.0]
        self._buffer: AudioBuffer | _PeakBuffer | None = None
        self._local_addresses: tuple[str, ...] = ()
        self._pairing_uri = ''
        self._app_pairing_uri = ''
        self._bound_port: int | None = None
        self._tls_enabled = True
        self._tls_cert_path = ''
        self._sample_rate = 48000
        self._channels = 1
        self._sample_width = 2

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def start(self, config: ControllerConfig) -> None:
        with self._lock:
            if self._running or (
                self._thread is not None and self._thread.is_alive()
            ):
                raise RuntimeError('Receiver is already running')
            self._stop_requested.clear()
            self._running = True
            self._status = 'starting'
            self._client_label = ''
            self._last_error = ''
            self._warning = ''
            self._peak[0] = 0.0
            self._local_addresses = ()
            self._pairing_uri = ''
            self._app_pairing_uri = ''
            self._bound_port = None
            self._tls_enabled = config.tls_enabled
            self._tls_cert_path = ''
            self._server = None
            self._buffer = None
            thread = threading.Thread(
                target=self._thread_main,
                args=(config,),
                name='mobile-mic-receiver',
                daemon=True,
            )
            self._thread = thread
        thread.start()

    def stop(self) -> None:
        self._stop_requested.set()
        deadline = time.time() + 2.0
        server: MicServer | None = None
        thread: threading.Thread | None = None
        while time.time() < deadline:
            with self._lock:
                server = self._server
                thread = self._thread
                if server is not None or thread is None or not thread.is_alive():
                    break
            time.sleep(0.02)
        with self._lock:
            server = self._server
            thread = self._thread
        if server is not None:
            server.request_stop()
        if thread is not None and thread.is_alive():
            thread.join(timeout=3)
        with self._lock:
            still_alive = thread is not None and thread.is_alive()
            self._running = still_alive
            if still_alive:
                self._status = 'error'
                self._last_error = '停止接收超时，请关闭窗口后重试'
            elif self._status != 'error':
                self._status = 'stopped'
                self._server = None
                self._thread = None
                self._client_label = ''
                self._bound_port = None
            else:
                self._server = None
                self._thread = None
                self._client_label = ''
                self._bound_port = None

    def snapshot(self) -> ControllerSnapshot:
        with self._lock:
            peak = self._peak[0]
            self._peak[0] = peak * 0.85
            stats = (
                self._buffer.stats()
                if self._buffer is not None
                else BufferStats(
                    queued_bytes=0,
                    dropped_bytes=0,
                    underflows=0,
                    buffering=True,
                )
            )
            bytes_per_ms = (
                self._sample_rate * self._channels * self._sample_width
            ) / 1000.0
            queued_ms = (
                stats.queued_bytes / bytes_per_ms if bytes_per_ms else 0.0
            )
            return ControllerSnapshot(
                running=self._running,
                status=self._status,
                client_label=self._client_label,
                last_error=self._last_error,
                warning=self._warning,
                peak=min(1.0, max(0.0, peak)),
                queued_ms=queued_ms,
                underflows=stats.underflows,
                buffering=stats.buffering,
                local_addresses=self._local_addresses,
                pairing_uri=self._pairing_uri,
                app_pairing_uri=self._app_pairing_uri,
                bound_port=self._bound_port,
                tls_enabled=self._tls_enabled,
                tls_cert_path=self._tls_cert_path,
            )

    def _on_event(self, event: ServerEvent) -> None:
        with self._lock:
            if event.kind == 'waiting':
                self._status = 'waiting'
                self._client_label = ''
            elif event.kind == 'connected':
                self._status = 'connected'
                label = event.device or '手机'
                if event.remote:
                    label = f'{label} ({event.remote})'
                self._client_label = label
            elif event.kind == 'disconnected':
                if self._running:
                    self._status = 'waiting'
                self._client_label = ''
            elif event.kind == 'rejected':
                # Keep waiting for a valid client; surface last reject briefly.
                if self._running and self._status != 'connected':
                    self._status = 'waiting'
                if event.message:
                    self._warning = event.message

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message
            self._status = 'error'
            self._running = False

    def _mark_stopped(self) -> None:
        with self._lock:
            if self._status != 'error':
                self._status = 'stopped'
            self._running = False
            self._server = None
            self._bound_port = None

    def _thread_main(self, config: ControllerConfig) -> None:
        import asyncio

        advertiser = MdnsAdvertiser(port=config.port)
        try:
            if self._stop_requested.is_set():
                return
            addresses = tuple(local_ipv4_addresses())
            scheme = 'https' if config.tls_enabled else 'http'
            pairing_uri = ''
            app_pairing_uri = ''
            if addresses:
                pairing_uri = build_web_pairing_uri(
                    host=addresses[0],
                    port=config.port,
                    token=config.token,
                    scheme=scheme,
                )
                app_pairing_uri = build_pairing_uri(
                    host=addresses[0],
                    port=config.port,
                    token=config.token,
                )
            with self._lock:
                self._local_addresses = addresses
                self._pairing_uri = pairing_uri
                self._app_pairing_uri = app_pairing_uri

            if self._stop_requested.is_set():
                return

            cert_path = ''
            key_path = ''
            if config.tls_enabled:
                hosts = addresses or ('127.0.0.1',)
                cert_file, key_file = ensure_tls_material(
                    default_tls_dir(), hosts=hosts
                )
                cert_path = str(cert_file)
                key_path = str(key_file)
                with self._lock:
                    self._tls_cert_path = cert_path
                    self._warning = (
                        '网页使用自签名 HTTPS：手机首次打开时需在浏览器中继续访问'
                    )

            buffer = AudioBuffer(
                sample_rate=self._sample_rate,
                channels=self._channels,
                max_latency_ms=config.latency_ms,
                prebuffer_ms=config.prebuffer_ms,
            )
            peak_buffer = _PeakBuffer(buffer, self._peak, self._lock)
            with self._lock:
                self._buffer = peak_buffer

            if config.discovery_enabled:
                try:
                    advertiser.start()
                except Exception as error:  # noqa: BLE001 - surface as warning
                    with self._lock:
                        existing = self._warning
                        note = f'mDNS 不可用: {error}'
                        self._warning = (
                            f'{existing}；{note}' if existing else note
                        )

            if self._stop_requested.is_set():
                return

            server = MicServer(
                ServerConfig(
                    host=config.host,
                    port=config.port,
                    sample_rate=self._sample_rate,
                    channels=self._channels,
                    token=config.token,
                    tls_enabled=config.tls_enabled,
                    tls_cert_path=cert_path,
                    tls_key_path=key_path,
                ),
                peak_buffer,  # type: ignore[arg-type]
                on_event=self._on_event,
            )
            with self._lock:
                self._server = server

            if self._stop_requested.is_set():
                server.request_stop()
                return

            with AudioOutput(
                peak_buffer,  # type: ignore[arg-type]
                device=config.device,
                sample_rate=self._sample_rate,
                channels=self._channels,
                blocksize=480,
            ):
                if self._stop_requested.is_set():
                    server.request_stop()
                    return
                asyncio.run(self._run_server(server))
        except Exception as error:  # noqa: BLE001 - report to UI
            self._set_error(str(error))
        finally:
            try:
                advertiser.close()
            except Exception:
                pass
            with self._lock:
                self._buffer = None
            self._mark_stopped()

    async def _run_server(self, server: MicServer) -> None:
        import asyncio

        task = asyncio.create_task(server.run())
        # Publish bound port once available.
        for _ in range(100):
            if server.bound_port is not None:
                with self._lock:
                    self._bound_port = server.bound_port
                break
            await asyncio.sleep(0.02)
        await task
