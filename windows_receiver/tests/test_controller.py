import threading
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


def test_stop_during_audio_open_exits_cleanly() -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingAudio:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            entered.set()
            assert release.wait(timeout=5)
            return self

        def __exit__(self, *args) -> None:
            return None

    controller = ReceiverController()
    with patch(
        'mobile_mic_receiver.controller.AudioOutput', BlockingAudio
    ), patch('mobile_mic_receiver.controller.MdnsAdvertiser') as advertiser:
        advertiser.return_value.start.return_value = None
        advertiser.return_value.close.return_value = None
        controller.start(
            ControllerConfig(
                device=None, host='127.0.0.1', port=18768, token='t'
            )
        )
        assert entered.wait(timeout=3)
        stop_done = threading.Event()

        def do_stop() -> None:
            controller.stop()
            stop_done.set()

        threading.Thread(target=do_stop, daemon=True).start()
        time.sleep(0.1)
        release.set()
        assert stop_done.wait(timeout=5)
        deadline = time.time() + 3
        while time.time() < deadline and controller.snapshot().running:
            time.sleep(0.05)
        assert controller.snapshot().running is False
        assert controller.snapshot().status in {'stopped', 'error'}
        with patch(
            'mobile_mic_receiver.controller.AudioOutput', DummyAudio
        ), patch('mobile_mic_receiver.controller.MdnsAdvertiser') as adv2:
            adv2.return_value.start.return_value = None
            adv2.return_value.close.return_value = None
            controller.start(
                ControllerConfig(
                    device=None, host='127.0.0.1', port=18768, token='t'
                )
            )
            deadline = time.time() + 3
            while time.time() < deadline:
                if controller.snapshot().status == 'waiting':
                    break
                time.sleep(0.05)
            assert controller.snapshot().status == 'waiting'
            controller.stop()
            assert controller.snapshot().running is False


def test_snapshot_pairing_uri_is_https_web() -> None:
    controller = ReceiverController()
    with patch('mobile_mic_receiver.controller.AudioOutput', DummyAudio), patch(
        'mobile_mic_receiver.controller.MdnsAdvertiser'
    ) as advertiser, patch(
        'mobile_mic_receiver.controller.local_ipv4_addresses',
        return_value=['192.168.1.20'],
    ):
        advertiser.return_value.start.return_value = None
        advertiser.return_value.close.return_value = None
        controller.start(
            ControllerConfig(
                device=None, host='127.0.0.1', port=18769, token='secret'
            )
        )
        try:
            deadline = time.time() + 3
            snap = controller.snapshot()
            while time.time() < deadline and not snap.pairing_uri:
                time.sleep(0.05)
                snap = controller.snapshot()
            assert snap.pairing_uri.startswith('https://192.168.1.20:18769/')
            assert 'token=secret' in snap.pairing_uri
            assert snap.app_pairing_uri.startswith('mobilemic://connect?')
            assert snap.tls_enabled is True
        finally:
            controller.stop()
