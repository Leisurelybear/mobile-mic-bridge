"""Regression: clearing a CTkLabel image must not leave a dead tk PhotoImage."""

from __future__ import annotations

import gc

import customtkinter as ctk
import pytest
from PIL import Image


def test_set_and_clear_qr_label_survives_gc_and_text_update() -> None:
    from mobile_mic_receiver.gui.qr_display import clear_qr_label, set_qr_label_image

    root = ctk.CTk()
    root.withdraw()
    label = ctk.CTkLabel(root, text='placeholder')
    label.pack()

    holder: dict[str, object] = {'image': None}
    image = Image.new('RGB', (64, 64), 'white')
    # Draw a black square so the image is non-trivial.
    for x in range(16, 48):
        for y in range(16, 48):
            image.putpixel((x, y), (0, 0, 0))

    set_qr_label_image(label, holder, image, size=(64, 64))
    assert holder['image'] is not None

    clear_qr_label(label, holder, text='启动后显示网页配对二维码')
    assert holder['image'] is None
    gc.collect()

    # The original crash: text configure after the PhotoImage was GC'd.
    label.configure(text='状态更新')
    assert label.cget('text') == '状态更新'

    root.destroy()


def test_replace_qr_image_does_not_crash() -> None:
    from mobile_mic_receiver.gui.qr_display import set_qr_label_image

    root = ctk.CTk()
    root.withdraw()
    label = ctk.CTkLabel(root, text='placeholder')
    label.pack()
    holder: dict[str, object] = {'image': None}

    set_qr_label_image(
        label, holder, Image.new('RGB', (32, 32), 'red'), size=(32, 32)
    )
    set_qr_label_image(
        label, holder, Image.new('RGB', (32, 32), 'blue'), size=(32, 32)
    )
    gc.collect()
    label.configure(text='')
    root.destroy()
