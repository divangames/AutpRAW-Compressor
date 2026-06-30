"""Тёмная шапка окна Windows 11 и настройка chrome."""
from __future__ import annotations

import ctypes
import sys
import tkinter as tk


def apply_windows_chrome(window: tk.Misc) -> None:
    if sys.platform != "win32":
        return
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        if not hwnd:
            hwnd = window.winfo_id()
        dwm = ctypes.windll.dwmapi
        dark = ctypes.c_int(1)
        for attr in (20, 19):  # immersive dark mode (Win11 / Win10 20H1+)
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(dark), ctypes.sizeof(dark))
        # Цвет заголовка и текста (Win11 22H2+)
        caption = ctypes.c_int(0x00161618)  # COLORREF BGR
        text = ctypes.c_int(0x00F5F5F7)
        for attr, val in ((35, caption), (36, text)):
            try:
                dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
            except Exception:
                pass
    except Exception:
        pass
