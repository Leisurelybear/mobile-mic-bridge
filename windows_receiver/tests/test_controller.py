import time
from unittest.mock import patch

from mobile_mic_receiver.controller import ControllerConfig, ReceiverController


class DummyAudio:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None


def test_start_stop_reaches_waiting() -> None:
    controller = ReceiverController()
    with patch('mobile_mic_receiver.controller.AudioOutput', DummyAudio), patch(
        'mobile_mic_receiver.controller.MdnsAdvertiser'
    ) as advertiser:
        advertiser.return_value.start.return_value = None
        advertiser.return_value.close.return_value = None
        controller.start(
            ControllerConfig(
                device=None, host='127.0.0.1', port=18765, token='t'
            )
        )
        deadline = time.time() + 3
        while time.time() < deadline:
            snap = controller.snapshot()
            if snap.status in {'waiting', 'connected'}:
                break
            time.sleep(0.05)
        assert controller.snapshot().running is True
        assert controller.snapshot().status == 'waiting'
        controller.stop()
        assert controller.snapshot().running is False
        assert controller.snapshot().status == 'stopped'


def test_stop_is_idempotent() -> None:
    controller = ReceiverController()
    controller.stop()
    controller.stop()


def test_start_while_running_raises() -> None:
    controller = ReceiverController()
    with patch('mobile_mic_receiver.controller.AudioOutput', DummyAudio), patch(
        'mobile_mic_receiver.controller.MdnsAdvertiser'
    ) as advertiser:
        advertiser.return_value.start.return_value = None
        advertiser.return_value.close.return_value = None
        controller.start(
            ControllerConfig(
                device=None, host='127.0.0.1', port=18766, token='t'
            )
        )
        try:
            deadline = time.time() + 3
            while time.time() < deadline and not controller.snapshot().running:
                time.sleep(0.05)
            raised = False
            try:
                controller.start(
                    ControllerConfig(
                        device=None, host='127.0.0.1', port=18767, token='t'
                    )
                )
            except RuntimeError:
                raised = True
            assert raised is True
        finally:
            controller.stop()
