"""Safe QR image helpers for CustomTkinter labels.

CTkLabel.configure(image=None) drops the Python reference without clearing the
underlying tkinter.Label image. Once the PhotoImage is garbage-collected, any
later text configure raises: TclError: image "pyimageN" doesn't exist.
"""

from __future__ import annotations

from typing import Any, MutableMapping

import customtkinter as ctk
from PIL import Image


def set_qr_label_image(
    label: ctk.CTkLabel,
    holder: MutableMapping[str, Any],
    image: Image.Image,
    *,
    size: tuple[int, int] = (220, 220),
) -> None:
    """Show a PIL image on a CTkLabel, keeping a live CTkImage reference."""
    ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=size)
    holder['image'] = ctk_image
    label.configure(image=ctk_image, text='')


def clear_qr_label(
    label: ctk.CTkLabel,
    holder: MutableMapping[str, Any],
    *,
    text: str,
) -> None:
    """Remove QR art and restore placeholder text without dangling pyimages.

    Passing image='' (not None) is required: CTk treats empty string as no
    image while still clearing the tkinter.Label image option. image=None only
    nulls CTk's Python ref and leaves a dead pyimage name behind.
    """
    holder['image'] = None
    label.configure(image='', text=text)
