from __future__ import annotations

from typing import Any

import sounddevice as sd

from .buffer import AudioBuffer

# Prefer these when the phone stream should become a Windows "microphone"
# for Discord/OBS/meetings via a virtual audio cable.
RECOMMENDED_OUTPUT_KEYWORDS = (
    'cable input',
    'vb-audio',
    'vb-cable',
    'voicemeeter input',
    'voicemeeter vaio',
    'voicemeeter aux',
    'voicemeeter out',
    'virtual cable',
)


def is_recommended_output_name(name: str) -> bool:
    lower = name.casefold()
    return any(keyword in lower for keyword in RECOMMENDED_OUTPUT_KEYWORDS)


def list_output_devices() -> list[tuple[int, str, int]]:
    devices: list[tuple[int, str, int]] = []
    for index, device in enumerate(sd.query_devices()):
        output_channels = int(device['max_output_channels'])
        if output_channels > 0:
            devices.append((index, str(device['name']), output_channels))
    # Recommended virtual-cable inputs first for easier selection.
    devices.sort(
        key=lambda item: (0 if is_recommended_output_name(item[1]) else 1, item[0])
    )
    return devices


class AudioOutput:
    def __init__(
        self,
        buffer: AudioBuffer,
        *,
        device: int | str | None,
        sample_rate: int,
        channels: int,
        blocksize: int,
    ) -> None:
        self._buffer = buffer
        self._stream = sd.RawOutputStream(
            samplerate=sample_rate,
            blocksize=blocksize,
            device=device,
            channels=channels,
            dtype='int16',
            callback=self._callback,
        )

    def _callback(
        self,
        outdata: Any,
        frames: int,
        time_info: Any,
        status: Any,
    ) -> None:
        del time_info, status
        outdata[:] = self._buffer.read(frames)

    def __enter__(self) -> AudioOutput:
        self._stream.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self._stream.stop()
        self._stream.close()
