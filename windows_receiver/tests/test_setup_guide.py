from mobile_mic_receiver.setup_guide import (
    VB_CABLE_DOWNLOAD_URL,
    describe_virtual_cable_status,
    pick_recommended_device,
    should_show_setup_wizard,
)


def test_pick_recommended_device_prefers_cable_input() -> None:
    devices = [
        (0, 'Speakers (Realtek)', 2),
        (12, 'CABLE Input (VB-Audio Virtual Cable)', 2),
        (8, 'Voicemeeter Input', 8),
    ]
    picked = pick_recommended_device(devices)
    assert picked is not None
    assert picked[0] == 12
    assert 'CABLE Input' in picked[1]


def test_pick_recommended_device_returns_none_when_missing() -> None:
    devices = [
        (0, 'Speakers (Realtek)', 2),
        (1, 'Microsoft Sound Mapper - Output', 2),
    ]
    assert pick_recommended_device(devices) is None


def test_should_show_setup_wizard() -> None:
    assert should_show_setup_wizard(setup_completed=False) is True
    assert should_show_setup_wizard(setup_completed=True) is False


def test_describe_status_ready() -> None:
    devices = [(12, 'CABLE Input (VB-Audio Virtual Cable)', 2)]
    status = describe_virtual_cable_status(devices)
    assert status.ready is True
    assert status.device_name is not None
    assert 'CABLE' in status.device_name.upper() or 'cable' in status.summary.casefold()


def test_describe_status_missing() -> None:
    devices = [(0, 'Speakers (Realtek)', 2)]
    status = describe_virtual_cable_status(devices)
    assert status.ready is False
    assert status.download_url == VB_CABLE_DOWNLOAD_URL
