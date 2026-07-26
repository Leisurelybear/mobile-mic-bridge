from mobile_mic_receiver.buffer import AudioBuffer


def make_buffer(**overrides: int) -> AudioBuffer:
    settings = {
        'sample_rate': 1000,
        'channels': 1,
        'max_latency_ms': 100,
        'prebuffer_ms': 20,
    }
    settings.update(overrides)
    return AudioBuffer(**settings)


def test_prebuffers_before_playback() -> None:
    buffer = make_buffer()
    buffer.write(b'\x01\x00' * 10)
    assert buffer.read(10) == bytes(20)
    buffer.write(b'\x02\x00' * 10)
    assert buffer.read(10) == b'\x01\x00' * 10


def test_underflow_outputs_silence_and_rebuffers() -> None:
    buffer = make_buffer()
    buffer.write(b'\x01\x00' * 20)
    assert buffer.read(15) == b'\x01\x00' * 15
    assert buffer.read(10) == b'\x01\x00' * 5 + bytes(10)
    assert buffer.stats().underflows == 1
    assert buffer.stats().buffering is True


def test_drops_oldest_audio_when_limit_is_exceeded() -> None:
    buffer = make_buffer(max_latency_ms=20, prebuffer_ms=1)
    buffer.write(b'\x01\x00' * 10)
    buffer.write(b'\x02\x00' * 20)
    assert buffer.stats().dropped_bytes == 20
    assert buffer.read(20) == b'\x02\x00' * 20


def test_ignores_partial_pcm_frame() -> None:
    buffer = make_buffer(prebuffer_ms=1)
    buffer.write(b'\x01')
    assert buffer.stats().queued_bytes == 0
