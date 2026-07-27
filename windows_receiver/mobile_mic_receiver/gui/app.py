from __future__ import annotations

import tkinter as tk
from typing import Any

import customtkinter as ctk
from PIL import Image, ImageTk

from mobile_mic_receiver.audio import list_output_devices
from mobile_mic_receiver.controller import (
    ControllerConfig,
    ControllerSnapshot,
    ReceiverController,
)
from mobile_mic_receiver.pairing import make_qr_image
from mobile_mic_receiver.settings import (
    ReceiverSettings,
    load_settings,
    save_settings,
)

STATUS_LABELS = {
    'stopped': '空闲',
    'starting': '正在启动…',
    'waiting': '等待手机连接',
    'connected': '已连接',
    'error': '错误',
}


def run_app() -> None:
    ctk.set_appearance_mode('System')
    ctk.set_default_color_theme('blue')
    app = ReceiverApp()
    app.mainloop()


class ReceiverApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title('Mobile Mic Bridge')
        self.geometry('920x600')
        self.minsize(820, 540)

        self._controller = ReceiverController()
        self._settings = load_settings()
        self._devices: list[tuple[int, str, int]] = []
        self._device_labels: list[str] = []
        self._save_after_id: str | None = None
        self._last_status = ''
        self._qr_photo: ImageTk.PhotoImage | None = None
        self._running_ui = False
        self._qr_host = ''
        self._qr_port = 8765
        self._last_qr_key = ''

        self._build_widgets()
        self._refresh_devices()
        self._apply_settings(self._settings)
        if self._settings.window_geometry:
            try:
                self.geometry(self._settings.window_geometry)
            except tk.TclError:
                pass

        self.protocol('WM_DELETE_WINDOW', self._on_close)
        self.after(50, self._tick)

    def _build_widgets(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self)
        header.grid(row=0, column=0, sticky='ew', padx=16, pady=(16, 8))
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            header, text='Mobile Mic Bridge', font=ctk.CTkFont(size=20, weight='bold')
        ).grid(row=0, column=0, sticky='w', padx=12, pady=10)
        self._status_var = tk.StringVar(value='状态：空闲')
        ctk.CTkLabel(header, textvariable=self._status_var).grid(
            row=0, column=1, sticky='e', padx=12, pady=10
        )

        body = ctk.CTkFrame(self)
        body.grid(row=1, column=0, sticky='nsew', padx=16, pady=8)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        settings = ctk.CTkFrame(body)
        settings.grid(row=0, column=0, sticky='nsew', padx=(12, 6), pady=12)
        settings.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            settings, text='设置', font=ctk.CTkFont(size=16, weight='bold')
        ).grid(row=0, column=0, columnspan=3, sticky='w', padx=12, pady=(12, 8))

        ctk.CTkLabel(settings, text='输出设备').grid(
            row=1, column=0, sticky='w', padx=12, pady=6
        )
        self._device_var = tk.StringVar(value='')
        self._device_menu = ctk.CTkOptionMenu(
            settings, variable=self._device_var, values=['']
        )
        self._device_menu.grid(row=1, column=1, sticky='ew', padx=6, pady=6)
        self._refresh_btn = ctk.CTkButton(
            settings, text='刷新', width=70, command=self._refresh_devices
        )
        self._refresh_btn.grid(row=1, column=2, sticky='e', padx=12, pady=6)

        ctk.CTkLabel(settings, text='端口').grid(
            row=2, column=0, sticky='w', padx=12, pady=6
        )
        self._port_var = tk.StringVar(value='8765')
        self._port_entry = ctk.CTkEntry(settings, textvariable=self._port_var)
        self._port_entry.grid(
            row=2, column=1, columnspan=2, sticky='ew', padx=12, pady=6
        )

        ctk.CTkLabel(settings, text='连接密码').grid(
            row=3, column=0, sticky='w', padx=12, pady=6
        )
        self._token_var = tk.StringVar(value='')
        self._token_entry = ctk.CTkEntry(
            settings, textvariable=self._token_var, show='•'
        )
        self._token_entry.grid(row=3, column=1, sticky='ew', padx=6, pady=6)
        self._show_token = tk.BooleanVar(value=False)
        self._show_token_btn = ctk.CTkCheckBox(
            settings,
            text='显示',
            variable=self._show_token,
            command=self._toggle_token_visibility,
            width=70,
        )
        self._show_token_btn.grid(row=3, column=2, sticky='e', padx=12, pady=6)

        ctk.CTkLabel(
            settings, text='高级', font=ctk.CTkFont(size=14, weight='bold')
        ).grid(row=4, column=0, columnspan=3, sticky='w', padx=12, pady=(16, 6))

        ctk.CTkLabel(settings, text='延迟 (ms)').grid(
            row=5, column=0, sticky='w', padx=12, pady=6
        )
        self._latency_var = tk.StringVar(value='400')
        self._latency_entry = ctk.CTkEntry(settings, textvariable=self._latency_var)
        self._latency_entry.grid(
            row=5, column=1, columnspan=2, sticky='ew', padx=12, pady=6
        )

        ctk.CTkLabel(settings, text='预缓冲 (ms)').grid(
            row=6, column=0, sticky='w', padx=12, pady=6
        )
        self._prebuffer_var = tk.StringVar(value='80')
        self._prebuffer_entry = ctk.CTkEntry(
            settings, textvariable=self._prebuffer_var
        )
        self._prebuffer_entry.grid(
            row=6, column=1, columnspan=2, sticky='ew', padx=12, pady=6
        )

        self._discovery_var = tk.BooleanVar(value=True)
        self._discovery_check = ctk.CTkCheckBox(
            settings, text='启用 mDNS 自动发现', variable=self._discovery_var
        )
        self._discovery_check.grid(
            row=7, column=0, columnspan=3, sticky='w', padx=12, pady=10
        )

        for var in (
            self._device_var,
            self._port_var,
            self._token_var,
            self._latency_var,
            self._prebuffer_var,
            self._discovery_var,
        ):
            var.trace_add('write', self._schedule_save)

        pairing = ctk.CTkFrame(body)
        pairing.grid(row=0, column=1, sticky='nsew', padx=(6, 12), pady=12)
        pairing.grid_columnconfigure(0, weight=1)
        pairing.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(pairing, fg_color='transparent')
        header.grid(row=0, column=0, sticky='ew', padx=12, pady=(12, 8))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header, text='配对', font=ctk.CTkFont(size=16, weight='bold')
        ).grid(row=0, column=0, sticky='w')
        self._qr_mode = ctk.CTkSegmentedButton(
            header,
            values=['网页', 'App'],
            command=self._on_qr_mode,
        )
        self._qr_mode.set('网页')
        self._qr_mode.grid(row=0, column=1, sticky='e')

        self._qr_label = ctk.CTkLabel(pairing, text='启动后显示网页配对二维码')
        self._qr_label.grid(row=1, column=0, sticky='nsew', padx=12, pady=8)

        self._addresses_var = tk.StringVar(value='本机地址：—')
        ctk.CTkLabel(pairing, textvariable=self._addresses_var, justify='left').grid(
            row=2, column=0, sticky='w', padx=12, pady=4
        )

        self._uri_var = tk.StringVar(value='')
        self._uri_entry = ctk.CTkEntry(pairing, textvariable=self._uri_var)
        self._uri_entry.grid(row=3, column=0, sticky='ew', padx=12, pady=4)
        self._copy_btn = ctk.CTkButton(
            pairing, text='复制配对链接', command=self._copy_uri
        )
        self._copy_btn.grid(row=4, column=0, sticky='ew', padx=12, pady=(4, 12))

        # Keep row indices consistent with header at 0 and QR at 1.
        # addresses/uri/copy stay at 2/3/4.

        meters = ctk.CTkFrame(self)
        meters.grid(row=2, column=0, sticky='ew', padx=16, pady=8)
        meters.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(meters, text='电平').grid(
            row=0, column=0, sticky='w', padx=12, pady=8
        )
        self._level_bar = ctk.CTkProgressBar(meters)
        self._level_bar.set(0)
        self._level_bar.grid(row=0, column=1, sticky='ew', padx=8, pady=8)

        self._buffer_var = tk.StringVar(value='缓冲 0 ms · 欠载 0')
        ctk.CTkLabel(meters, textvariable=self._buffer_var).grid(
            row=0, column=2, sticky='e', padx=12, pady=8
        )

        actions = ctk.CTkFrame(self)
        actions.grid(row=3, column=0, sticky='ew', padx=16, pady=(8, 16))
        actions.grid_columnconfigure(0, weight=1)
        actions.grid_columnconfigure(1, weight=1)

        self._start_btn = ctk.CTkButton(
            actions, text='启动接收', command=self._start, height=40
        )
        self._start_btn.grid(row=0, column=0, sticky='ew', padx=(12, 6), pady=12)
        self._stop_btn = ctk.CTkButton(
            actions,
            text='停止',
            command=self._stop,
            height=40,
            state='disabled',
            fg_color='#8B3A3A',
            hover_color='#6E2E2E',
        )
        self._stop_btn.grid(row=0, column=1, sticky='ew', padx=(6, 12), pady=12)

        self._message_var = tk.StringVar(value='')
        ctk.CTkLabel(self, textvariable=self._message_var, text_color='#C9A227').grid(
            row=4, column=0, sticky='w', padx=28, pady=(0, 12)
        )

    def _toggle_token_visibility(self) -> None:
        self._token_entry.configure(show='' if self._show_token.get() else '•')

    def _schedule_save(self, *_args: Any) -> None:
        if self._running_ui:
            return
        if self._save_after_id is not None:
            self.after_cancel(self._save_after_id)
        self._save_after_id = self.after(500, self._save_settings_now)

    def _collect_settings(self) -> ReceiverSettings:
        device_name = ''
        label = self._device_var.get()
        if label and ': ' in label:
            device_name = label.split(': ', 1)[1]
        try:
            port = int(self._port_var.get().strip())
        except ValueError:
            port = 8765
        try:
            latency = int(self._latency_var.get().strip())
        except ValueError:
            latency = 400
        try:
            prebuffer = int(self._prebuffer_var.get().strip())
        except ValueError:
            prebuffer = 80
        return ReceiverSettings(
            device_name=device_name,
            port=port,
            token=self._token_var.get(),
            latency_ms=latency,
            prebuffer_ms=prebuffer,
            discovery_enabled=bool(self._discovery_var.get()),
            window_geometry=self.geometry(),
        )

    def _save_settings_now(self) -> None:
        self._save_after_id = None
        settings = self._collect_settings()
        self._settings = settings
        try:
            save_settings(settings)
        except OSError as error:
            self._message_var.set(f'设置保存失败：{error}')

    def _apply_settings(self, settings: ReceiverSettings) -> None:
        self._port_var.set(str(settings.port))
        self._token_var.set(settings.token)
        self._latency_var.set(str(settings.latency_ms))
        self._prebuffer_var.set(str(settings.prebuffer_ms))
        self._discovery_var.set(settings.discovery_enabled)
        if settings.device_name:
            for label in self._device_labels:
                if label.endswith(f': {settings.device_name}'):
                    self._device_var.set(label)
                    break

    def _refresh_devices(self) -> None:
        try:
            devices = list_output_devices()
        except Exception as error:  # noqa: BLE001
            self._message_var.set(f'无法枚举音频设备：{error}')
            return
        self._devices = devices
        self._device_labels = [f'{index}: {name}' for index, name, _ in devices]
        values = self._device_labels or ['(无可用输出设备)']
        current = self._device_var.get()
        self._device_menu.configure(values=values)
        if current in values:
            self._device_var.set(current)
        else:
            self._device_var.set(values[0])

    def _selected_device(self) -> int | str | None:
        label = self._device_var.get()
        if not label or label.startswith('('):
            return None
        if ': ' not in label:
            return None
        index_text, name = label.split(': ', 1)
        try:
            return int(index_text)
        except ValueError:
            return name

    def _validate_form(self) -> tuple[bool, str, ControllerConfig | None]:
        try:
            port = int(self._port_var.get().strip())
        except ValueError:
            return False, '端口必须是数字', None
        if not 1 <= port <= 65535:
            return False, '端口必须在 1 到 65535 之间', None
        try:
            latency = int(self._latency_var.get().strip())
            prebuffer = int(self._prebuffer_var.get().strip())
        except ValueError:
            return False, '延迟和预缓冲必须是正整数', None
        if latency <= 0 or prebuffer <= 0:
            return False, '延迟和预缓冲必须是正整数', None
        if prebuffer > latency:
            return False, '预缓冲不能大于延迟', None
        device = self._selected_device()
        if device is None and self._devices:
            return False, '请选择输出设备', None
        config = ControllerConfig(
            device=device,
            host='0.0.0.0',
            port=port,
            token=self._token_var.get(),
            latency_ms=latency,
            prebuffer_ms=prebuffer,
            discovery_enabled=bool(self._discovery_var.get()),
        )
        return True, '', config

    def _set_running_ui(self, running: bool) -> None:
        self._running_ui = running
        state = 'disabled' if running else 'normal'
        for widget in (
            self._device_menu,
            self._refresh_btn,
            self._port_entry,
            self._token_entry,
            self._show_token_btn,
            self._latency_entry,
            self._prebuffer_entry,
            self._discovery_check,
        ):
            widget.configure(state=state)
        self._start_btn.configure(state='disabled' if running else 'normal')
        self._stop_btn.configure(state='normal' if running else 'disabled')

    def _start(self) -> None:
        ok, message, config = self._validate_form()
        if not ok or config is None:
            self._message_var.set(message)
            return
        if not config.token:
            self._message_var.set('提示：未设置连接密码，局域网内任何设备都可能连接')
        else:
            self._message_var.set('')
        self._save_settings_now()
        try:
            self._controller.start(config)
        except RuntimeError as error:
            self._message_var.set(str(error))
            return
        except Exception as error:  # noqa: BLE001
            self._message_var.set(f'启动失败：{error}')
            return
        self._set_running_ui(True)
        self._status_var.set('状态：正在启动…')

    def _stop(self) -> None:
        self._controller.stop()
        snap = self._controller.snapshot()
        if snap.running or snap.status not in {'stopped', 'error'}:
            if snap.last_error:
                self._message_var.set(snap.last_error)
            else:
                self._message_var.set('正在停止，请稍候…')
            return
        self._set_running_ui(False)
        self._level_bar.set(0)
        self._clear_qr()
        if snap.status == 'error' and snap.last_error:
            self._status_var.set(f'状态：错误：{snap.last_error}')
            self._message_var.set(snap.last_error)
        else:
            self._status_var.set('状态：空闲')
        self._addresses_var.set('本机地址：—')
        self._uri_var.set('')
        self._buffer_var.set('缓冲 0 ms · 欠载 0')

    def _clear_qr(self) -> None:
        self._qr_photo = None
        self._last_qr_key = ''
        self._qr_label.configure(image=None, text='启动后显示网页配对二维码')

    def _qr_mode_key(self) -> str:
        return 'app' if self._qr_mode.get() == 'App' else 'web'

    def _update_qr(
        self, host: str, port: int, token: str, *, tls_enabled: bool = True
    ) -> None:
        mode = self._qr_mode_key()
        scheme = 'https' if tls_enabled else 'http'
        key = f'{mode}|{scheme}|{host}|{port}|{token}'
        if key == self._last_qr_key and self._qr_photo is not None:
            return
        try:
            image = make_qr_image(
                host=host,
                port=port,
                token=token,
                box_size=5,
                mode=mode,
                scheme=scheme,
            )
            image = image.resize((220, 220), Image.Resampling.NEAREST)
            self._qr_photo = ImageTk.PhotoImage(image)
            self._qr_label.configure(image=self._qr_photo, text='')
            self._last_qr_key = key
            self._qr_host = host
            self._qr_port = port
        except Exception as error:  # noqa: BLE001
            self._qr_photo = None
            self._last_qr_key = ''
            self._qr_label.configure(image=None, text=f'二维码不可用：{error}')

    def _on_qr_mode(self, _value: str) -> None:
        snap = self._controller.snapshot()
        if self._qr_mode_key() == 'app':
            if snap.app_pairing_uri:
                self._uri_var.set(snap.app_pairing_uri)
        else:
            if snap.pairing_uri:
                self._uri_var.set(snap.pairing_uri)
        host = self._qr_host or (
            snap.local_addresses[0] if snap.local_addresses else ''
        )
        port = snap.bound_port or self._qr_port or int(self._port_var.get() or 8765)
        if host:
            self._last_qr_key = ''
            self._update_qr(
                host,
                port,
                self._token_var.get(),
                tls_enabled=snap.tls_enabled,
            )

    def _copy_uri(self) -> None:
        uri = self._uri_var.get().strip()
        if not uri:
            self._message_var.set('暂无配对链接可复制')
            return
        self.clipboard_clear()
        self.clipboard_append(uri)
        self._message_var.set('配对链接已复制')

    def _tick(self) -> None:
        snap = self._controller.snapshot()
        self._apply_snapshot(snap)
        self.after(50, self._tick)

    def _apply_snapshot(self, snap: ControllerSnapshot) -> None:
        if snap.running and not self._running_ui:
            self._set_running_ui(True)
        if not snap.running and self._running_ui and snap.status in {
            'stopped',
            'error',
        }:
            self._set_running_ui(False)
            if snap.status == 'error' and snap.last_error:
                self._message_var.set(snap.last_error)
            self._clear_qr()

        status_text = STATUS_LABELS.get(snap.status, snap.status)
        if snap.status == 'connected' and snap.client_label:
            status_text = f'已连接 · {snap.client_label}'
        if snap.status == 'error' and snap.last_error:
            status_text = f'错误：{snap.last_error}'
        full_status = f'状态：{status_text}'
        if full_status != self._last_status:
            self._status_var.set(full_status)
            self._last_status = full_status

        self._level_bar.set(snap.peak if snap.running else 0.0)
        buffering = '预缓冲中' if snap.buffering else '播放中'
        self._buffer_var.set(
            f'缓冲 {snap.queued_ms:.0f} ms · 欠载 {snap.underflows} · {buffering}'
        )

        if snap.running:
            if snap.local_addresses:
                self._addresses_var.set(
                    '本机地址：' + '  ·  '.join(snap.local_addresses)
                )
            else:
                self._addresses_var.set('本机地址：未检测到 IPv4，请用 ipconfig 查看')
            target_uri = (
                snap.app_pairing_uri
                if self._qr_mode_key() == 'app'
                else snap.pairing_uri
            )
            if target_uri:
                if self._uri_var.get() != target_uri:
                    self._uri_var.set(target_uri)
                host = snap.local_addresses[0] if snap.local_addresses else ''
                port = snap.bound_port or int(self._port_var.get() or 8765)
                if host:
                    self._update_qr(
                        host,
                        port,
                        self._token_var.get(),
                        tls_enabled=snap.tls_enabled,
                    )
            elif not snap.local_addresses:
                self._uri_var.set('')
                self._qr_label.configure(
                    image=None, text='无本机 IPv4，无法生成二维码'
                )
            if snap.warning:
                self._message_var.set(snap.warning)

    def _on_close(self) -> None:
        try:
            self._controller.stop()
        finally:
            try:
                self._save_settings_now()
            except Exception:
                pass
            self.destroy()
