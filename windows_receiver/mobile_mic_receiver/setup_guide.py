from __future__ import annotations

from dataclasses import dataclass

from .audio import is_recommended_output_name

# Official VB-CABLE download page (user installs signed driver themselves).
VB_CABLE_DOWNLOAD_URL = 'https://vb-audio.com/Cable/'


@dataclass(frozen=True)
class VirtualCableStatus:
    ready: bool
    device_index: int | None
    device_name: str | None
    summary: str
    next_step: str
    download_url: str = VB_CABLE_DOWNLOAD_URL


def should_show_setup_wizard(*, setup_completed: bool) -> bool:
    return not setup_completed


def pick_recommended_device(
    devices: list[tuple[int, str, int]],
) -> tuple[int, str, int] | None:
    """Prefer VB-CABLE Input, then other known virtual-cable inputs."""
    if not devices:
        return None
    cable_inputs = [
        item
        for item in devices
        if 'cable input' in item[1].casefold()
        or (
            'vb-audio' in item[1].casefold()
            and 'input' in item[1].casefold()
        )
    ]
    if cable_inputs:
        return cable_inputs[0]
    recommended = [
        item for item in devices if is_recommended_output_name(item[1])
    ]
    if recommended:
        return recommended[0]
    return None


def describe_virtual_cable_status(
    devices: list[tuple[int, str, int]],
) -> VirtualCableStatus:
    picked = pick_recommended_device(devices)
    if picked is not None:
        index, name, _channels = picked
        return VirtualCableStatus(
            ready=True,
            device_index=index,
            device_name=name,
            summary=f'已检测到虚拟声卡：{name}',
            next_step=(
                '本软件输出选它。Discord/游戏/会议的麦克风请选对应的 '
                'CABLE Output（或 Voicemeeter Out）。'
            ),
        )
    return VirtualCableStatus(
        ready=False,
        device_index=None,
        device_name=None,
        summary='未检测到虚拟声卡（如 VB-CABLE）。',
        next_step=(
            '安装 VB-CABLE 后点“重新检测”。安装后本软件选 CABLE Input，'
            'Discord/游戏麦克风选 CABLE Output。'
        ),
    )
