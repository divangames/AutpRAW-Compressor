"""Drag-and-drop для Windows + tkinter через windnd (без WinAPI subclassing)."""
from __future__ import annotations

import platform
import queue
from pathlib import Path

import tkinter

try:
    import windnd  # type: ignore[import-not-found]
except ImportError:
    windnd = None  # type: ignore[assignment]


def _decode_path(raw: str | bytes) -> str:
    if isinstance(raw, bytes):
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("mbcs", errors="replace")
    return str(raw)


def paths_from_drop(files) -> list[Path]:
    paths: list[Path] = []
    for item in files:
        p = Path(_decode_path(item).strip().strip('"'))
        if p.is_dir():
            paths.append(p)
    return paths


def install_drop_target(tk_window: tkinter.Misc, drop_queue: queue.Queue) -> bool:
    """Drop-пути попадают в drop_queue; обработка — только в главном потоке tkinter."""
    if platform.system() != "Windows" or windnd is None:
        return False

    def on_drop(files) -> None:
        paths = paths_from_drop(files)
        if paths:
            drop_queue.put(paths)

    try:
        windnd.hook_dropfiles(tk_window, func=on_drop, force_unicode=True)
        return True
    except Exception:
        return False
