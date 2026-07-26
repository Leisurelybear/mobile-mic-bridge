from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class BufferStats:
    queued_bytes: int
    dropped_bytes: int
    underflows: int
    buffering: bool


class AudioBuffer:
    def __init__(
        self,
        *,
        sample_rate: int,
        channels: int,
        sample_width: int = 2,
        max_latency_ms: int = 400,
        prebuffer_ms: int = 80,
    ) -> None:
        if sample_rate <= 0 or channels <= 0 or sample_width <= 0:
            raise ValueError('Audio format values must be positive')
        if prebuffer_ms <= 0 or max_latency_ms <= 0:
            raise ValueError('Buffer durations must be positive')
        if prebuffer_ms > max_latency_ms:
            raise ValueError('Prebuffer cannot exceed maximum latency')
        self._bytes_per_frame = channels * sample_width
        self._max_bytes = self._to_bytes(sample_rate, max_latency_ms)
        self._prebuffer_bytes = self._to_bytes(sample_rate, prebuffer_ms)
        self._data = bytearray()
        self._remainder = b''
        self._lock = Lock()
        self._buffering = True
        self._dropped_bytes = 0
        self._underflows = 0

    def _to_bytes(self, sample_rate: int, duration_ms: int) -> int:
        frames = max(1, sample_rate * duration_ms // 1000)
        return frames * self._bytes_per_frame

    def write(self, data: bytes) -> None:
        with self._lock:
            combined = self._remainder + data
            usable_length = len(combined) - (len(combined) % self._bytes_per_frame)
            self._remainder = combined[usable_length:]
            if usable_length <= 0:
                return
            self._data.extend(combined[:usable_length])
            overflow = len(self._data) - self._max_bytes
            if overflow > 0:
                overflow -= overflow % self._bytes_per_frame
                del self._data[:overflow]
                self._dropped_bytes += overflow

    def read(self, frames: int) -> bytes:
        requested_bytes = frames * self._bytes_per_frame
        silence = bytes(requested_bytes)
        with self._lock:
            if self._buffering:
                if len(self._data) < self._prebuffer_bytes:
                    return silence
                self._buffering = False

            available = min(requested_bytes, len(self._data))
            available -= available % self._bytes_per_frame
            chunk = bytes(self._data[:available])
            del self._data[:available]
            if available < requested_bytes:
                self._underflows += 1
                self._buffering = True
                return chunk + bytes(requested_bytes - available)
            return chunk

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._remainder = b''
            self._buffering = True

    def stats(self) -> BufferStats:
        with self._lock:
            return BufferStats(
                queued_bytes=len(self._data),
                dropped_bytes=self._dropped_bytes,
                underflows=self._underflows,
                buffering=self._buffering,
            )
