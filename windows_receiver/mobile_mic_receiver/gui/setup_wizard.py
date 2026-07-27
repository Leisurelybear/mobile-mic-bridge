from __future__ import annotations

import webbrowser
from collections.abc import Callable

import customtkinter as ctk

from mobile_mic_receiver.audio import list_output_devices
from mobile_mic_receiver.setup_guide import (
    VB_CABLE_DOWNLOAD_URL,
    describe_virtual_cable_status,
)


class SetupWizard(ctk.CTkToplevel):
    """First-run / on-demand guide for virtual cable + Discord setup."""

    def __init__(
        self,
        master: ctk.CTk,
        *,
        on_apply_device: Callable[[str], None],
        on_finished: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self.title('快速设置向导')
        self.geometry('560x520')
        self.minsize(520, 480)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self._on_apply_device = on_apply_device
        self._on_finished = on_finished
        self._step = 0
        self._status = describe_virtual_cable_status(list_output_devices())

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._title_var = ctk.StringVar(value='')
        ctk.CTkLabel(
            self,
            textvariable=self._title_var,
            font=ctk.CTkFont(size=18, weight='bold'),
        ).grid(row=0, column=0, sticky='w', padx=20, pady=(18, 8))

        self._body = ctk.CTkFrame(self)
        self._body.grid(row=1, column=0, sticky='nsew', padx=16, pady=8)
        self._body.grid_columnconfigure(0, weight=1)

        self._footer = ctk.CTkFrame(self, fg_color='transparent')
        self._footer.grid(row=2, column=0, sticky='ew', padx=16, pady=(4, 16))
        self._footer.grid_columnconfigure(0, weight=1)

        self._back_btn = ctk.CTkButton(
            self._footer, text='上一步', width=100, command=self._back
        )
        self._back_btn.grid(row=0, column=0, sticky='w')
        self._next_btn = ctk.CTkButton(
            self._footer, text='下一步', width=120, command=self._next
        )
        self._next_btn.grid(row=0, column=1, sticky='e', padx=(8, 0))

        self.protocol('WM_DELETE_WINDOW', self._skip)
        self.after(10, self._render)

    def _clear_body(self) -> None:
        for child in self._body.winfo_children():
            child.destroy()

    def _render(self) -> None:
        self._clear_body()
        if self._step == 0:
            self._render_welcome()
        elif self._step == 1:
            self._render_cable()
        else:
            self._render_apps()
        self._back_btn.configure(state='normal' if self._step > 0 else 'disabled')
        if self._step >= 2:
            self._next_btn.configure(text='完成')
        else:
            self._next_btn.configure(text='下一步')

    def _render_welcome(self) -> None:
        self._title_var.set('欢迎使用手机无线麦克风')
        lines = [
            '三步就能给 Discord / 游戏 / 会议当麦克风：',
            '',
            '1. 安装或检测虚拟声卡（只需一次）',
            '2. 本软件自动选好输出设备',
            '3. 手机扫码开麦；语音软件选 CABLE Output',
            '',
            '为什么需要虚拟声卡？',
            'Windows 不允许普通软件直接变成系统麦克风。',
            '虚拟声卡负责把本软件播放的声音，变成 Discord 能选的麦克风。',
        ]
        ctk.CTkLabel(
            self._body,
            text='\n'.join(lines),
            justify='left',
            anchor='w',
        ).grid(row=0, column=0, sticky='nw', padx=16, pady=16)

    def _render_cable(self) -> None:
        self._title_var.set('第 1 步：虚拟声卡')
        self._status = describe_virtual_cable_status(list_output_devices())
        status_color = '#3D9A5F' if self._status.ready else '#C9A227'
        ctk.CTkLabel(
            self._body,
            text=self._status.summary,
            text_color=status_color,
            font=ctk.CTkFont(size=14, weight='bold'),
            justify='left',
            wraplength=480,
        ).grid(row=0, column=0, sticky='nw', padx=16, pady=(16, 8))
        ctk.CTkLabel(
            self._body,
            text=self._status.next_step,
            justify='left',
            wraplength=480,
        ).grid(row=1, column=0, sticky='nw', padx=16, pady=4)

        actions = ctk.CTkFrame(self._body, fg_color='transparent')
        actions.grid(row=2, column=0, sticky='ew', padx=16, pady=16)
        ctk.CTkButton(
            actions,
            text='打开 VB-CABLE 下载页',
            command=self._open_download,
        ).grid(row=0, column=0, sticky='w')
        ctk.CTkButton(
            actions,
            text='重新检测',
            width=100,
            command=self._redetect,
        ).grid(row=0, column=1, sticky='w', padx=8)

        if self._status.ready and self._status.device_name:
            ctk.CTkLabel(
                self._body,
                text=f'将自动选择输出设备：{self._status.device_name}',
                text_color='#9DB0C7',
                justify='left',
                wraplength=480,
            ).grid(row=3, column=0, sticky='nw', padx=16, pady=(0, 12))
        else:
            ctk.CTkLabel(
                self._body,
                text=(
                    '也可以稍后手动安装。没有虚拟声卡时，本软件只能用扬声器试听，'
                    'Discord 无法把它当麦克风。'
                ),
                text_color='#9DB0C7',
                justify='left',
                wraplength=480,
            ).grid(row=3, column=0, sticky='nw', padx=16, pady=(0, 12))

    def _render_apps(self) -> None:
        self._title_var.set('第 2 步：语音软件怎么选')
        lines = [
            '本软件启动后：',
            '  · 输出设备 = CABLE Input（向导可自动选好）',
            '  · 手机扫码 → 开始传输',
            '',
            'Discord / Steam / 会议 / OBS：',
            '  · 麦克风 / 输入设备 = CABLE Output',
            '  · 不要选本机 Realtek 麦克风，也不要选 CABLE Input',
            '',
            '电脑游戏声音：',
            '  · 继续用你的音箱/耳机，不要改成 CABLE',
            '',
            '手机建议戴耳机，减少游戏声音被手机再次录入。',
        ]
        ctk.CTkLabel(
            self._body,
            text='\n'.join(lines),
            justify='left',
            anchor='w',
        ).grid(row=0, column=0, sticky='nw', padx=16, pady=16)

    def _open_download(self) -> None:
        webbrowser.open(VB_CABLE_DOWNLOAD_URL)

    def _redetect(self) -> None:
        self._status = describe_virtual_cable_status(list_output_devices())
        self._render()

    def _back(self) -> None:
        if self._step > 0:
            self._step -= 1
            self._render()

    def _next(self) -> None:
        if self._step == 1 and self._status.ready and self._status.device_name:
            self._on_apply_device(self._status.device_name)
        if self._step >= 2:
            self._finish()
            return
        self._step += 1
        self._render()

    def _skip(self) -> None:
        # Closing still marks wizard seen so it does not loop forever;
        # user can reopen from the main window.
        self._finish()

    def _finish(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self._on_finished()
        self.destroy()
