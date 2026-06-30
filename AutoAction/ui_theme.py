"""Windows 11 Fluent Design — палитра, шрифты, иконки."""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

# ── Win11 dark palette ───────────────────────────────────────────
C = dict(
    BG="#0d0d0f",
    CHROME="#111114",
    RAIL="#141418",
    MAIN="#0d0d0f",
    DOCK="#16161a",
    MICA="#1a1a1f",
    MICA_LIGHT="#222228",
    ACRYLIC="#25252c",
    CARD="#2a2a32",
    CARD_HOVER="#33333c",
    CARD_SEL="#243044",
    CARD_SEL_BORDER="#4d9cf5",
    ELEVATION="#000000",
    TEXT="#f3f3f6",
    TEXT2="#9b9ba8",
    TEXT3="#636370",
    ACCENT="#0a84ff",
    ACCENT_H="#2995ff",
    ACCENT_P="#0070e0",
    ACCENT_GLOW="#0a84ff33",
    SUCCESS="#32d74b",
    ERROR="#ff453a",
    WARN="#ffd60a",
    PENDING="#636370",
    PROCESSING="#64d2ff",
    SKIPPED="#8e8e98",
    DROP_BG="#1c1c22",
    DROP_BORDER="#3a3a48",
    DROP_H="#242430",
    DROP_ACTIVE="#152a45",
    PROGRESS_BG="#2a2a34",
    PROGRESS_FILL="#0a84ff",
    BTN_SEC="#2c2c34",
    BTN_SEC_H="#383842",
    BTN_SEC_P="#222228",
    DIVIDER="#2a2a32",
)

# Режимы прохода — оттенки карточек и строк
MODE = {
    "main": dict(
        CARD="#1c2838",
        CARD_BORDER="#2d4a68",
        ROW="#182230",
        ROW_BORDER="#243850",
        PILL="#0a84ff",
        PILL_TEXT="#ffffff",
        ACCENT="#5eb0ff",
    ),
    "old": dict(
        CARD="#2a2418",
        CARD_BORDER="#5c4a28",
        ROW="#241e14",
        ROW_BORDER="#4a3c20",
        PILL="#d4a017",
        PILL_TEXT="#1a1408",
        ACCENT="#e8b84a",
    ),
}


def mode_palette(mode: str) -> dict[str, str]:
    return MODE.get(mode, MODE["main"])

RADIUS = 14
RADIUS_SM = 10
RADIUS_LG = 16
PAD = 20
PAD_SM = 12
ANIM_MS = 16

# Segoe MDL2 Assets (Fluent-style icons on Windows)
ICO = dict(
    FOLDER="\uE8B7",
    ADD="\uE710",
    PLAY="\uE768",
    STOP="\uE71A",
    INFO="\uE946",
    SETTINGS="\uE713",
    DELETE="\uE74D",
    SKIP="\uE718",
    REFRESH="\uE72C",
    CHEVRON_DOWN="\uE70D",
    CHEVRON_UP="\uE70E",
    CHECK="\uE73E",
    CLOSE="\uE711",
    SELECT_ALL="\uE8B3",
)


def _pick_family(candidates: tuple[str, ...], fallback: str = "Segoe UI") -> str:
    try:
        families = set(tkfont.families())
    except Exception:
        return fallback
    for name in candidates:
        if name in families:
            return name
    return fallback


FONT_UI = _pick_family(("Segoe UI Variable Text", "Segoe UI Variable Display", "Segoe UI"))
FONT_DISPLAY = _pick_family(("Segoe UI Variable Display", "Segoe UI Variable Text", "Segoe UI"))
FONT_ICONS = _pick_family(("Segoe Fluent Icons", "Segoe MDL2 Assets", "Segoe UI"))


def font(size: int = 10, weight: str = "normal") -> tuple[str, int, str] | tuple[str, int]:
    if weight == "normal":
        return (FONT_UI, size)
    return (FONT_UI, size, weight)


def font_display(size: int = 20, weight: str = "bold") -> tuple[str, int, str]:
    return (FONT_DISPLAY, size, weight)


def font_icon(size: int = 20) -> tuple[str, int]:
    return (FONT_ICONS, size)


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 8:
        h = h[:6]
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def lerp_color(c1: str, c2: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    r1, g1, b1 = hex_to_rgb(c1)
    r2, g2, b2 = hex_to_rgb(c2)
    return rgb_to_hex(
        int(r1 + (r2 - r1) * t),
        int(g1 + (g2 - g1) * t),
        int(b1 + (b2 - b1) * t),
    )
