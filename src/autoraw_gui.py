from __future__ import annotations

import json
import sys
import queue
import subprocess
import threading
import time
import math
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    import windnd  # type: ignore[import-not-found]
except Exception:
    windnd = None

from PIL import Image, ImageEnhance, ImageOps, ImageTk

from app_paths import resource_path
from version import APP_NAME, APP_TITLE
from autoraw_crop import (
    CANVAS_SIZE,
    LAYOUT_RULES,
    Box,
    compute_auto_crop_box,
    frame_id,
    image_files,
    open_preview,
    target_aspect,
)


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".nef", ".dng"}
PREVIEW_SIZE = (700, 525)
RIGHT_PANEL_W = 320
THUMB_SIZE = (138, 104)
ZOOM_MAX = 3.0

# ── Palettes (Light / Dark) ──────────────────────────────────────
_PALETTES: dict[str, dict[str, str]] = {
    "dark": dict(
        BG="#1c1c1c", PANEL="#252525", PANEL_L="#303030",
        SURFACE="#2b2b2b", BORDER="#3d3d3d",
        TEXT="#d4d4d4", TEXT2="#888888",
        ACCENT="#4b9ef0", ACCENT_H="#6cb3ff",
        SEL="#1f4275", INPUT="#1a1a1a", BTN="#3c3c3c",
        SL_TRACK="#111111", SL_ACTIVE="#4b9ef0",
        SL_THUMB="#a0a8b0", SL_THUMB_BD="#6a7280",
        PREVIEW_BG="#0b0c0f",
    ),
    "light": dict(
        BG="#f3f3f3", PANEL="#e8e8e8", PANEL_L="#d5d5d5",
        SURFACE="#ebebeb", BORDER="#c4c4c4",
        TEXT="#202020", TEXT2="#555555",
        ACCENT="#0067c0", ACCENT_H="#005ea6",
        SEL="#c9dff5", INPUT="#ffffff", BTN="#d8d8d8",
        SL_TRACK="#c0c0c0", SL_ACTIVE="#0067c0",
        SL_THUMB="#505050", SL_THUMB_BD="#888888",
        PREVIEW_BG="#1a1a1a",
    ),
}

# Mutable globals – updated by _apply_palette()
FIG_BG      = "#1c1c1c"
FIG_PANEL   = "#252525"
FIG_PANEL_L = "#303030"
FIG_SURFACE = "#2b2b2b"
FIG_BORDER  = "#3d3d3d"
FIG_TEXT    = "#d4d4d4"
FIG_TEXT2   = "#888888"
FIG_ACCENT  = "#4b9ef0"
FIG_ACCENT_H= "#6cb3ff"
FIG_SEL     = "#1f4275"
FIG_INPUT   = "#1a1a1a"
FIG_BTN     = "#3c3c3c"
SL_TRACK    = "#111111"
SL_ACTIVE   = "#4b9ef0"
SL_THUMB    = "#a0a8b0"
SL_THUMB_BD = "#6a7280"
_PREVIEW_BG = "#0b0c0f"
_DARK_MODE  = True


def _detect_system_dark() -> bool:
    """Return True when Windows Apps use dark mode (via registry)."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return val == 0   # 0 = dark, 1 = light
    except Exception:
        return True


def _apply_palette(mode: str) -> None:
    """Overwrite the mutable FIG_* / SL_* globals with the chosen palette."""
    global FIG_BG, FIG_PANEL, FIG_PANEL_L, FIG_SURFACE, FIG_BORDER
    global FIG_TEXT, FIG_TEXT2, FIG_ACCENT, FIG_ACCENT_H, FIG_SEL
    global FIG_INPUT, FIG_BTN, SL_TRACK, SL_ACTIVE, SL_THUMB, SL_THUMB_BD
    global _PREVIEW_BG, _DARK_MODE
    p = _PALETTES[mode]
    FIG_BG      = p["BG"];      FIG_PANEL   = p["PANEL"]; FIG_PANEL_L = p["PANEL_L"]
    FIG_SURFACE = p["SURFACE"]; FIG_BORDER  = p["BORDER"]
    FIG_TEXT    = p["TEXT"];    FIG_TEXT2   = p["TEXT2"]
    FIG_ACCENT  = p["ACCENT"];  FIG_ACCENT_H= p["ACCENT_H"]
    FIG_SEL     = p["SEL"];     FIG_INPUT   = p["INPUT"]; FIG_BTN = p["BTN"]
    SL_TRACK    = p["SL_TRACK"]; SL_ACTIVE  = p["SL_ACTIVE"]
    SL_THUMB    = p["SL_THUMB"]; SL_THUMB_BD= p["SL_THUMB_BD"]
    _PREVIEW_BG = p["PREVIEW_BG"]
    _DARK_MODE  = (mode == "dark")


_CONFIG_PATH = resource_path("ui_config.json")


def _load_theme_choice() -> str:
    try:
        data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        v = data.get("theme", "system")
        return v if v in ("dark", "light", "system") else "system"
    except Exception:
        return "system"


def _save_theme_choice(choice: str) -> None:
    try:
        _CONFIG_PATH.write_text(json.dumps({"theme": choice}), encoding="utf-8")
    except Exception:
        pass


# Apply initial palette so module-level constants are set before class creation
_apply_palette("dark")
REFERENCE_DIR = resource_path("reference", "Sneakers")
WORKING_MAX_SIDE = 2600
STANDARD_PROFILE = "Adobe Стандарт"
STANDARD_CONTRAST = 20
STANDARD_SHADOWS = 13
STANDARD_TEMPERATURE = 6500
STANDARD_TINT = 4
DROPLETS_DIR = resource_path("droplets")
DROPLET_BY_FRAME = {
    "01": "01_drop.exe",
    "02": "02-03-04-08_drop.exe",
    "03": "02-03-04-08_drop.exe",
    "04": "02-03-04-08_drop.exe",
    "08": "02-03-04-08_drop.exe",
    "05": "05-06-07_drop.exe",
    "06": "05-06-07_drop.exe",
    "07": "05-06-07_drop.exe",
}


@dataclass
class FrameState:
    path: Path
    frame: str
    image: Image.Image
    crop_box: Box
    checked: bool = True
    offset_x: float = 0.0
    offset_y: float = 0.0
    zoom: float = 1.0
    rotation: float = 0.0
    profile: str = STANDARD_PROFILE
    contrast: int = STANDARD_CONTRAST
    shadows: int = STANDARD_SHADOWS
    temperature: int = STANDARD_TEMPERATURE
    tint: int = STANDARD_TINT
    thumb_cache: Image.Image | None = None


@dataclass
class FolderState:
    path: Path
    checked: bool = True
    frames: list[FrameState] | None = None


def frame_sort_key(path: Path) -> tuple[int, str]:
    frame = frame_id(path)
    return (int(frame) if frame.isdigit() else 999, path.name.lower())


def direct_image_files(folder: Path) -> list[Path]:
    files = [path for path in sorted(folder.iterdir(), key=lambda p: p.name.lower()) if path.is_file()]
    images = [path for path in files if path.suffix.lower() in IMAGE_EXTENSIONS]
    if not images:
        images = list(image_files(folder))

    priority = {".nef": 0, ".dng": 1, ".jpg": 2, ".jpeg": 2, ".png": 3, ".tif": 4, ".tiff": 4}
    by_frame: dict[str, Path] = {}
    for path in images:
        frame = frame_id(path)
        current = by_frame.get(frame)
        if current is None or priority.get(path.suffix.lower(), 9) < priority.get(current.suffix.lower(), 9):
            by_frame[frame] = path

    return sorted(by_frame.values(), key=frame_sort_key)


def has_direct_sources(folder: Path) -> bool:
    try:
        return any(path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS for path in folder.iterdir())
    except OSError:
        return False


def is_export_folder(path: Path) -> bool:
    return path.parent.name == path.name


def discover_source_folders(root: Path) -> list[Path]:
    folders: list[Path] = []
    if has_direct_sources(root):
        folders.append(root)

    for path in sorted(root.rglob("*"), key=lambda p: str(p).lower()):
        if path.is_dir() and not is_export_folder(path) and has_direct_sources(path):
            folders.append(path)

    seen: set[Path] = set()
    unique: list[Path] = []
    for folder in folders:
        resolved = folder.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(folder)
    return unique


def fit_image(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    fitted = img.copy()
    fitted.thumbnail(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", size, "white")
    left = (size[0] - fitted.width) // 2
    top = (size[1] - fitted.height) // 2
    canvas.paste(fitted, (left, top))
    return canvas


def render_frame(
    state: FrameState,
    size: tuple[int, int] = CANVAS_SIZE,
    *,
    source_image: Image.Image | None = None,
    crop_box: Box | None = None,
) -> Image.Image:
    # Render from the full source image, not from pre-cropped preview pixels.
    # This keeps repositioning smooth and prevents white side stripes from
    # appearing too early when the user adjusts the frame.
    source = source_image if source_image is not None else state.image
    box = crop_box if crop_box is not None else state.crop_box
    box = box.clamp(source.width, source.height)
    if box.width <= 0 or box.height <= 0:
        return Image.new("RGB", size, "white")

    zoom = max(0.2, float(state.zoom or 1.0))
    rotation = float(state.rotation or 0.0)
    if abs(rotation) < 0.05:
        rotation = 0.0

    theta = abs(math.radians(rotation))
    sin_t = abs(math.sin(theta))
    cos_t = abs(math.cos(theta))

    # Не усиливаем зум при повороте: пользовательский масштаб должен
    # оставаться тем, который выставлен на слайдере.
    if rotation:
        zoom = max(1.0, zoom)

    viewport_w = max(1.0, box.width / zoom)
    viewport_h = max(1.0, box.height / zoom)
    scale_src_x = viewport_w / size[0]
    scale_src_y = viewport_h / size[1]

    base_cx = (box.left + box.right) / 2.0
    base_cy = (box.top + box.bottom) / 2.0
    # Смещения заданы в пикселях холста CANVAS_SIZE (как слайдеры и перетаскивание).
    canvas_w, canvas_h = float(CANVAS_SIZE[0]), float(CANVAS_SIZE[1])
    dx_screen = state.offset_x * viewport_w / canvas_w
    dy_screen = state.offset_y * viewport_h / canvas_h
    # Keep panning strictly in screen/canvas axes:
    # X/Y sliders and drag should always move image horizontally/vertically
    # regardless of rotation angle.
    cx = base_cx - dx_screen
    cy = base_cy - dy_screen

    # Для поворота берём из источника увеличенную область (bounding box),
    # чтобы после rotate() центр кадра остался заполненным пикселями фото.
    rot_bbox_w = cos_t * viewport_w + sin_t * viewport_h
    rot_bbox_h = sin_t * viewport_w + cos_t * viewport_h
    min_cx = rot_bbox_w / 2.0
    max_cx = float(source.width) - rot_bbox_w / 2.0
    min_cy = rot_bbox_h / 2.0
    max_cy = float(source.height) - rot_bbox_h / 2.0
    if min_cx > max_cx:
        cx = float(source.width) / 2.0
    else:
        cx = max(min_cx, min(max_cx, cx))
    if min_cy > max_cy:
        cy = float(source.height) / 2.0
    else:
        cy = max(min_cy, min(max_cy, cy))

    if rotation:
        rot_factor_x = (cos_t * float(size[0]) + sin_t * float(size[1])) / max(1.0, float(size[0]))
        rot_factor_y = (sin_t * float(size[0]) + cos_t * float(size[1])) / max(1.0, float(size[1]))
        sample_size = (
            max(size[0], int(math.ceil(size[0] * rot_factor_x))),
            max(size[1], int(math.ceil(size[1] * rot_factor_y))),
        )
    else:
        sample_size = size

    sample_left = cx - (sample_size[0] * scale_src_x) / 2.0
    sample_top = cy - (sample_size[1] * scale_src_y) / 2.0
    frame = source.transform(
        sample_size,
        Image.Transform.AFFINE,
        (scale_src_x, 0.0, sample_left, 0.0, scale_src_y, sample_top),
        resample=Image.Resampling.BICUBIC,
    )

    if rotation:
        frame = frame.rotate(rotation, resample=Image.Resampling.BICUBIC, expand=False)
        crop_left = max(0, (sample_size[0] - size[0]) // 2)
        crop_top = max(0, (sample_size[1] - size[1]) // 2)
        frame = frame.crop((crop_left, crop_top, crop_left + size[0], crop_top + size[1]))

    return frame


def _channel_mult(img: Image.Image, r_mult: float, g_mult: float, b_mult: float) -> Image.Image:
    r, g, b = img.split()

    def apply_mult(ch: Image.Image, mult: float) -> Image.Image:
        lut = [max(0, min(255, int(i * mult))) for i in range(256)]
        return ch.point(lut)

    return Image.merge("RGB", (apply_mult(r, r_mult), apply_mult(g, g_mult), apply_mult(b, b_mult)))


def _clamp_int(value: int, min_value: int, max_value: int) -> int:
    return max(min_value, min(max_value, int(value)))


def apply_standard_look(
    img: Image.Image,
    *,
    contrast: int = STANDARD_CONTRAST,
    shadows: int = STANDARD_SHADOWS,
    temperature: int = STANDARD_TEMPERATURE,
    tint: int = STANDARD_TINT,
) -> Image.Image:
    contrast = _clamp_int(contrast, -100, 100)
    shadows = _clamp_int(shadows, -100, 100)
    temperature = _clamp_int(temperature, 2000, 10000)
    tint = _clamp_int(tint, -100, 100)

    # Contrast
    result = ImageEnhance.Contrast(img).enhance(1.0 + contrast / 100.0)

    # Shadows (lift dark areas stronger than highlights)
    lifted = ImageEnhance.Brightness(result).enhance(1.0 + shadows / 100.0)
    inv_luma = ImageOps.invert(result.convert("L"))
    shadow_mask = inv_luma.point(lambda v: max(0, min(255, int(v * 0.42))))
    result = Image.composite(lifted, result, shadow_mask)

    # Temperature and tint. Neutral point is 6500 (your base preset).
    temp_delta = (temperature - 6500) / 2500.0
    r_mult = 1.0 + 0.015 * temp_delta
    b_mult = 1.0 - 0.015 * temp_delta
    g_mult = 1.0

    tint_delta = tint / 100.0
    r_mult *= 1.0 + 0.006 * tint_delta
    b_mult *= 1.0 + 0.006 * tint_delta
    g_mult *= 1.0 - 0.010 * tint_delta

    # Safety bounds against accidental extreme cast.
    r_mult = max(0.85, min(1.15, r_mult))
    g_mult = max(0.85, min(1.15, g_mult))
    b_mult = max(0.85, min(1.15, b_mult))

    return _channel_mult(result, r_mult=r_mult, g_mult=g_mult, b_mult=b_mult)


class AutoRawGui(tk.Tk):
    def __init__(self, initial_folder: Path | None = None) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1440x900")
        self.minsize(1260, 780)

        self.root_folder: Path | None = None
        self.folder_states: dict[Path, FolderState] = {}
        self.selected_folder: Path | None = None
        self.selected_index = 0
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.thumb_photos: list[ImageTk.PhotoImage] = []
        self.drag_start: tuple[int, int, float, float] | None = None
        self._updating_controls = False
        self.worker_events: queue.Queue[tuple] = queue.Queue()
        self.load_token = 0
        self.loading_frames = False
        self.pending_folder: Path | None = None
        self.tree_path_by_iid: dict[str, Path] = {}
        self.tree_iid_by_path: dict[Path, str] = {}
        self.drop_window: tk.Toplevel | None = None
        self.thumb_btns: list[tk.Label] = []

        # Theme – must be set before _build_ui() applies palette
        self._theme_choice: str = _load_theme_choice()
        dark = self._resolve_dark(self._theme_choice)
        _apply_palette("dark" if dark else "light")

        self._build_ui()
        self._set_window_icon()
        self.after(50, self._enable_drop_target)
        self.after(100, self.process_worker_events)

        if initial_folder:
            self.load_root(initial_folder)

    def _resolve_dark(self, choice: str) -> bool:
        """Return True (dark mode) for the given theme choice string."""
        if choice == "dark":
            return True
        if choice == "light":
            return False
        return _detect_system_dark()

    def _change_theme(self, choice: str) -> None:
        """Switch theme, persist to config, and rebuild the entire UI."""
        # Save current edits into FrameState before destroying widgets
        if hasattr(self, "offset_x"):
            self._save_controls_to_current()

        self._theme_choice = choice
        _save_theme_choice(choice)
        _apply_palette("dark" if self._resolve_dark(choice) else "light")

        # Snapshot mutable state (folder images are preserved inside FolderState)
        saved_root     = self.root_folder
        saved_states   = self.folder_states
        saved_folder   = self.selected_folder
        saved_idx      = self.selected_index
        saved_loading  = self.loading_frames
        saved_token    = self.load_token

        # Destroy all widgets and rebuild with updated FIG_* globals
        for w in self.winfo_children():
            w.destroy()

        self._build_ui()
        self._set_window_icon()

        # Restore state
        self.root_folder    = saved_root
        self.folder_states  = saved_states
        self.selected_folder = saved_folder
        self.selected_index  = saved_idx
        self.loading_frames  = saved_loading
        self.load_token      = saved_token

        if saved_root:
            self.drop_var.set(str(saved_root))
            if self.folder_states:
                self.render_folder_tree()
                if saved_folder and saved_folder in self.folder_states:
                    iid = self.tree_iid_by_path.get(saved_folder)
                    if iid:
                        self.folder_tree.selection_set(iid)
                    fs = self.folder_states[saved_folder]
                    if fs.frames is not None:
                        self.render_thumbnails()
                        n = len(fs.frames)
                        idx = max(0, min(saved_idx, n - 1)) if n else 0
                        self.select_frame(idx, save_previous=False)

    def _set_window_icon(self) -> None:
        icon_path = resource_path("assets", "image", "favicon.ico")
        if not icon_path.is_file():
            return
        try:
            self.iconbitmap(str(icon_path))
        except tk.TclError:
            pass

    def _setup_theme(self) -> None:
        self.configure(bg=FIG_BG)
        st = ttk.Style(self)
        st.theme_use("clam")

        # Base defaults
        st.configure(".",
            background=FIG_PANEL,
            foreground=FIG_TEXT,
            font=("Segoe UI", 10),
            borderwidth=0,
            relief="flat",
        )
        st.configure("TFrame",  background=FIG_PANEL)
        st.configure("TLabel",  background=FIG_PANEL, foreground=FIG_TEXT)

        # Buttons
        st.configure("TButton",
            background=FIG_BTN,
            foreground=FIG_TEXT,
            padding=(10, 5),
            relief="flat",
            borderwidth=0,
            focuscolor=FIG_BTN,
        )
        st.map("TButton",
            background=[("active", FIG_PANEL_L), ("pressed", "#222222")],
            foreground=[("active", "#ffffff"), ("pressed", "#ffffff")],
        )
        st.configure("Accent.TButton",
            background=FIG_ACCENT,
            foreground="#ffffff",
            padding=(12, 5),
            relief="flat",
            borderwidth=0,
            focuscolor=FIG_ACCENT,
        )
        st.map("Accent.TButton",
            background=[("active", FIG_ACCENT_H), ("pressed", "#2a6dbf")],
        )

        # Tree
        st.configure("Treeview",
            background=FIG_SURFACE,
            foreground=FIG_TEXT,
            fieldbackground=FIG_SURFACE,
            borderwidth=0,
            rowheight=26,
        )
        st.configure("Treeview.Heading",
            background=FIG_BG,
            foreground=FIG_TEXT2,
            borderwidth=0,
            relief="flat",
            font=("Segoe UI", 9),
        )
        st.map("Treeview",
            background=[("selected", FIG_SEL)],
            foreground=[("selected", "#ffffff")],
        )
        st.map("Treeview.Heading",
            background=[("active", FIG_PANEL_L)],
        )

        # Progress bar
        st.configure("TProgressbar",
            background=FIG_ACCENT,
            troughcolor=FIG_INPUT,
            borderwidth=0,
            thickness=4,
        )

        # Entry
        st.configure("TEntry",
            fieldbackground=FIG_INPUT,
            foreground=FIG_TEXT,
            insertcolor=FIG_TEXT,
            borderwidth=1,
            relief="flat",
            bordercolor=FIG_BORDER,
        )
        st.map("TEntry",
            fieldbackground=[("focus", FIG_PANEL_L)],
            bordercolor=[("focus", FIG_ACCENT)],
        )

        # Spinbox
        st.configure("TSpinbox",
            fieldbackground=FIG_INPUT,
            foreground=FIG_TEXT,
            insertcolor=FIG_TEXT,
            background=FIG_BTN,
            arrowcolor=FIG_TEXT2,
            borderwidth=1,
            relief="flat",
            bordercolor=FIG_BORDER,
            lightcolor=FIG_BORDER,
            darkcolor=FIG_BORDER,
        )
        st.map("TSpinbox",
            fieldbackground=[("focus", FIG_PANEL_L)],
            bordercolor=[("focus", FIG_ACCENT)],
        )

        # Combobox
        st.configure("TCombobox",
            fieldbackground=FIG_INPUT,
            foreground=FIG_TEXT,
            background=FIG_BTN,
            selectbackground=FIG_SEL,
            arrowcolor=FIG_TEXT2,
            borderwidth=1,
        )
        st.map("TCombobox",
            fieldbackground=[("readonly", FIG_INPUT)],
            selectbackground=[("readonly", "")],
            selectforeground=[("readonly", FIG_TEXT)],
        )

        # Checkbuttons
        st.configure("TCheckbutton",
            background=FIG_PANEL,
            foreground=FIG_TEXT,
            indicatorcolor=FIG_INPUT,
        )
        st.map("TCheckbutton",
            background=[("active", FIG_PANEL)],
            indicatorcolor=[("selected", FIG_ACCENT)],
        )
        st.configure("Dark.TCheckbutton",
            background=FIG_BG,
            foreground=FIG_TEXT,
            indicatorcolor=FIG_INPUT,
        )
        st.map("Dark.TCheckbutton",
            background=[("active", FIG_BG)],
            indicatorcolor=[("selected", FIG_ACCENT)],
        )

        # Scrollbar — thin, dark, accent on hover
        st.configure("Vertical.TScrollbar",
            background=FIG_BTN,
            troughcolor=FIG_BG,
            bordercolor=FIG_BG,
            arrowcolor=FIG_TEXT2,
            gripcount=0,
            relief="flat",
            borderwidth=0,
            width=8,
        )
        st.map("Vertical.TScrollbar",
            background=[("active", FIG_ACCENT), ("pressed", FIG_ACCENT_H)],
            arrowcolor=[("active", "#ffffff")],
        )

    def _section_label(self, parent: tk.Widget, text: str) -> None:
        tk.Label(
            parent, text=text, bg=str(parent.cget("bg")),
            fg=FIG_TEXT2, font=("Segoe UI", 9, "bold"),
        ).pack(anchor=tk.W, padx=10, pady=(10, 6))

    def _hsep(self, parent: tk.Widget) -> None:
        tk.Frame(parent, bg=FIG_BORDER, height=1).pack(fill=tk.X)

    def _rounded_rect(
        self,
        canvas: tk.Canvas,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        radius: int,
        *,
        fill: str,
        outline: str,
        width: int = 1,
    ) -> None:
        points = [
            x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
            x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
            x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
        ]
        canvas.create_polygon(points, smooth=True, splinesteps=16, fill=fill, outline=outline, width=width)

    def _draw_check(self, canvas: tk.Canvas, checked: bool) -> None:
        canvas.delete("all")
        bg = str(canvas.cget("bg"))
        if checked:
            # filled accent square + white tick
            self._rounded_rect(canvas, 1, 1, 19, 19, 4,
                                fill=FIG_ACCENT, outline=FIG_ACCENT, width=1)
            canvas.create_line(5, 10, 8, 14, 15, 6,
                                fill="#ffffff", width=2,
                                capstyle=tk.ROUND, joinstyle=tk.ROUND)
        else:
            # transparent interior, always-visible border (FIG_TEXT2 = medium gray)
            self._rounded_rect(canvas, 1, 1, 19, 19, 4,
                                fill=bg, outline=FIG_TEXT2, width=1)
        canvas.configure(highlightthickness=0)

    def _make_check(
        self,
        parent: tk.Widget,
        checked: bool,
        command,
        *,
        bg: str = FIG_BG,
        tooltip_text: str | None = None,
    ) -> tk.Canvas:
        canvas = tk.Canvas(parent, width=20, height=20, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        canvas._checked = checked  # type: ignore[attr-defined]
        self._draw_check(canvas, checked)

        def toggle(_event: tk.Event | None = None) -> str:
            new_value = not bool(getattr(canvas, "_checked", False))
            canvas._checked = new_value  # type: ignore[attr-defined]
            self._draw_check(canvas, new_value)
            command(new_value)
            return "break"

        canvas.bind("<Button-1>", toggle)
        canvas.bind("<Return>", toggle)
        canvas.bind("<space>", toggle)
        canvas.bind("<Enter>", lambda _e: canvas.configure(bg=FIG_PANEL_L if bg == FIG_BG else bg))
        canvas.bind("<Leave>", lambda _e: canvas.configure(bg=bg))
        canvas.configure(takefocus=1)
        if tooltip_text:
            canvas.bind("<FocusIn>", lambda _e: self.set_progress(self.progress_var.get(), tooltip_text))
        return canvas

    def _draw_switch(self, canvas: tk.Canvas, enabled: bool) -> None:
        canvas.delete("all")
        track = FIG_ACCENT if enabled else FIG_INPUT
        knob_x = 32 if enabled else 12
        self._rounded_rect(canvas, 1, 2, 47, 24, 12, fill=track, outline=FIG_BORDER if not enabled else track, width=1)
        canvas.create_oval(knob_x - 8, 5, knob_x + 8, 21, fill="#ffffff", outline="")
        canvas.create_text(62, 13, text="ВКЛ" if enabled else "ВЫКЛ", fill=FIG_TEXT if enabled else FIG_TEXT2,
                           font=("Segoe UI", 8, "bold"), anchor=tk.W)

    def _make_switch(self, parent: tk.Widget, variable: tk.BooleanVar, command) -> tk.Canvas:
        canvas = tk.Canvas(parent, width=92, height=26, bg=FIG_PANEL, highlightthickness=0, bd=0, cursor="hand2")
        self._draw_switch(canvas, bool(variable.get()))

        def toggle(_event: tk.Event | None = None) -> str:
            variable.set(not bool(variable.get()))
            self._draw_switch(canvas, bool(variable.get()))
            command()
            return "break"

        canvas.bind("<Button-1>", toggle)
        canvas.bind("<Return>", toggle)
        canvas.bind("<space>", toggle)
        canvas.configure(takefocus=1)
        return canvas

    def _build_ui(self) -> None:
        self._setup_theme()

        # ── Title bar with theme selector ────────────────────────────
        titlebar = tk.Frame(self, bg=FIG_BG, height=36)
        titlebar.pack(fill=tk.X)
        titlebar.pack_propagate(False)
        tk.Label(titlebar, text="AutoRAW Compressor", bg=FIG_BG, fg=FIG_TEXT2,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=12, pady=8)
        tk.Frame(titlebar, bg=FIG_BORDER, height=1).pack(side=tk.BOTTOM, fill=tk.X)

        # Theme toggle buttons (right side of titlebar)
        theme_bar = tk.Frame(titlebar, bg=FIG_BG)
        theme_bar.pack(side=tk.RIGHT, padx=8)
        for _lbl, _mode in (("☀ Светлая", "light"), ("🌙 Тёмная", "dark"), ("⚙ Авто", "system")):
            _active = (self._theme_choice == _mode)
            _btn = tk.Label(
                theme_bar, text=_lbl,
                bg=FIG_ACCENT if _active else FIG_BTN,
                fg="#ffffff" if _active else FIG_TEXT2,
                font=("Segoe UI", 9),
                padx=8, pady=3, cursor="hand2",
                relief="flat",
            )
            _btn.pack(side=tk.LEFT, padx=2, pady=6)
            _btn.bind("<Button-1>", lambda e, m=_mode: self._change_theme(m))
            _btn.bind("<Enter>",    lambda e, w=_btn, m=_mode: w.configure(
                bg=FIG_ACCENT_H if self._theme_choice == m else FIG_PANEL_L))
            _btn.bind("<Leave>",    lambda e, w=_btn, m=_mode: w.configure(
                bg=FIG_ACCENT if self._theme_choice == m else FIG_BTN))

        # ── Path / action toolbar ─────────────────────────────────────
        bar = tk.Frame(self, bg=FIG_PANEL, height=44)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)
        tk.Frame(bar, bg=FIG_BORDER, height=1).pack(side=tk.BOTTOM, fill=tk.X)

        bar_inner = tk.Frame(bar, bg=FIG_PANEL)
        bar_inner.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)

        self.drop_var = tk.StringVar(value="Вставьте путь или перетащите папку…")
        self.drop_entry = ttk.Entry(bar_inner, textvariable=self.drop_var, font=("Segoe UI", 10))
        self.drop_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

        ttk.Button(bar_inner, text="📂", width=3, command=self.pick_folder).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(bar_inner, text="Загрузить", command=self.load_from_entry).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(bar_inner, text="Экспорт", style="Accent.TButton", command=self.export_checked).pack(side=tk.LEFT, padx=(2, 12))

        # separator dot
        tk.Frame(bar_inner, bg=FIG_BORDER, width=1).pack(side=tk.LEFT, fill=tk.Y, pady=4)

        self.use_droplet_var = tk.BooleanVar(value=False)
        tk.Label(bar_inner, text="Дроплет", bg=FIG_PANEL, fg=FIG_TEXT2,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(8, 4))
        self._make_check(
            bar_inner, False,
            lambda value: self.use_droplet_var.set(value),
            bg=FIG_PANEL,
        ).pack(side=tk.LEFT)

        # ── Status bar ───────────────────────────────────────────────
        sb = tk.Frame(self, bg=FIG_BG, height=22)
        sb.pack(fill=tk.X)
        sb.pack_propagate(False)
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(sb, variable=self.progress_var, maximum=100, length=200)
        self.progress_bar.pack(side=tk.LEFT, padx=(10, 8), pady=4)
        self.progress_label = tk.StringVar(value="Готово")
        tk.Label(sb, textvariable=self.progress_label, bg=FIG_BG, fg=FIG_TEXT2,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)
        tk.Frame(self, bg=FIG_BORDER, height=1).pack(fill=tk.X)

        # ── Main body ────────────────────────────────────────────────
        body = tk.Frame(self, bg=FIG_BG)
        body.pack(fill=tk.BOTH, expand=True)

        # ── Left: folder tree ─────────────────────────────────────
        left = tk.Frame(body, bg=FIG_SURFACE, width=240)
        left.pack(side=tk.LEFT, fill=tk.Y)
        left.pack_propagate(False)
        self._section_label(left, "Папки")
        self.folder_tree = ttk.Treeview(left, columns=("check", "count"),
                                         show="tree headings", height=30)
        self.folder_tree.heading("#0", text="Имя")
        self.folder_tree.heading("check", text="✓")
        self.folder_tree.heading("count", text="")
        self.folder_tree.column("#0", width=158, stretch=True)
        self.folder_tree.column("check", width=26, anchor=tk.CENTER, stretch=False)
        self.folder_tree.column("count", width=28, anchor=tk.CENTER, stretch=False)
        self.folder_tree.pack(fill=tk.BOTH, expand=True, padx=(6, 0), pady=(0, 6))
        self.folder_tree.bind("<<TreeviewSelect>>", self.on_folder_select)
        self.folder_tree.bind("<Button-1>", self.on_folder_click)

        # left separator
        tk.Frame(body, bg=FIG_BORDER, width=1).pack(side=tk.LEFT, fill=tk.Y)

        # ── Right: thumbnails + info — pack RIGHT before center ───
        # (RIGHT items must be packed before the LEFT+expand center)
        right = tk.Frame(body, bg=FIG_SURFACE, width=RIGHT_PANEL_W)
        right.pack(side=tk.RIGHT, fill=tk.Y)
        right.pack_propagate(False)

        # right separator
        tk.Frame(body, bg=FIG_BORDER, width=1).pack(side=tk.RIGHT, fill=tk.Y)

        self.info_var = tk.StringVar(value="Папка не загружена")
        self._section_label(right, "Кадры")

        info_card = tk.Frame(right, bg=FIG_PANEL_L)
        info_card.pack(fill=tk.X, padx=8, pady=(0, 8))
        tk.Label(info_card, textvariable=self.info_var, bg=FIG_PANEL, fg=FIG_TEXT2,
                 font=("Segoe UI", 9), wraplength=RIGHT_PANEL_W - 40,
                 justify="left").pack(anchor=tk.W, padx=8, pady=6)

        self._hsep(right)

        thumb_wrap = tk.Frame(right, bg=FIG_SURFACE)
        thumb_wrap.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.thumb_canvas = tk.Canvas(thumb_wrap, bg=FIG_SURFACE, highlightthickness=0, bd=0)
        thumb_scroll = ttk.Scrollbar(
            thumb_wrap, orient=tk.VERTICAL, command=self.thumb_canvas.yview, style="Vertical.TScrollbar"
        )
        self.thumb_canvas.configure(yscrollcommand=thumb_scroll.set)
        thumb_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.thumb_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.thumbs = tk.Frame(self.thumb_canvas, bg=FIG_SURFACE)
        self._thumb_canvas_window = self.thumb_canvas.create_window(
            (0, 0), window=self.thumbs, anchor=tk.NW,
        )
        self.thumbs.bind(
            "<Configure>",
            lambda _e: self.thumb_canvas.configure(scrollregion=self.thumb_canvas.bbox("all")),
        )
        self.thumb_canvas.bind(
            "<Configure>",
            lambda e: self.thumb_canvas.itemconfigure(self._thumb_canvas_window, width=e.width),
        )
        self.thumb_canvas.bind("<MouseWheel>", self._on_thumb_mousewheel)
        self.thumbs.bind("<MouseWheel>", self._on_thumb_mousewheel)

        # ── Center: canvas + controls + colour ───────────────────
        center = tk.Frame(body, bg=FIG_BG)
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.preview = tk.Canvas(center, width=PREVIEW_SIZE[0], height=PREVIEW_SIZE[1],
                                  bg=_PREVIEW_BG, highlightthickness=0)
        self.preview.pack(fill=tk.BOTH, expand=True)
        self.preview.bind("<ButtonPress-1>", self.start_drag)
        self.preview.bind("<B1-Motion>",     self.drag_preview)
        self.preview.bind("<ButtonRelease-1>", self.stop_drag)
        self.preview.bind("<MouseWheel>",    self.mousewheel_zoom)
        self.preview.bind("<Left>",  lambda _e: self.nudge_current(-1, 0))
        self.preview.bind("<Right>", lambda _e: self.nudge_current(1, 0))
        self.preview.bind("<Up>",    lambda _e: self.nudge_current(0, -1))
        self.preview.bind("<Down>",  lambda _e: self.nudge_current(0, 1))

        # ── Bottom controls panel ────────────────────────────────────
        bottom = tk.Frame(center, bg=FIG_PANEL)
        bottom.pack(fill=tk.X)
        tk.Frame(bottom, bg=FIG_BORDER, height=1).pack(fill=tk.X)

        # ── Sliders + reset ──────────────────────────────────────────
        ctrl_wrap = tk.Frame(bottom, bg=FIG_PANEL)
        ctrl_wrap.pack(fill=tk.X, padx=16, pady=(10, 0))

        ctrl = tk.Frame(ctrl_wrap, bg=FIG_PANEL)
        ctrl.pack(fill=tk.X)
        self.offset_x = self._slider(ctrl, "X",        -450,  450,    self.update_current, "{:.0f}")
        self.offset_y = self._slider(ctrl, "Y",        -350,  350,    self.update_current, "{:.0f}")
        self.zoom     = self._slider(ctrl, "Масштаб",   0.5,  ZOOM_MAX, self.update_current, "{:.2f}")
        self.rotation = self._slider(ctrl, "Поворот",  -20,   20,     self.update_current, "{:.1f}°")
        self.zoom.set(1.0)

        rb = tk.Frame(ctrl_wrap, bg=FIG_PANEL)
        rb.pack(fill=tk.X, pady=(2, 10))
        ttk.Button(rb, text="Сбросить кадр",  command=self.reset_current).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(rb, text="Сбросить папку", command=self.reset_folder).pack(side=tk.LEFT)

        # ── Colour correction ─────────────────────────────────────────
        tk.Frame(bottom, bg=FIG_BORDER, height=1).pack(fill=tk.X)

        self.profile_var     = tk.StringVar(value=STANDARD_PROFILE)
        self.contrast_var    = tk.IntVar(value=STANDARD_CONTRAST)
        self.shadows_var     = tk.IntVar(value=STANDARD_SHADOWS)
        self.temperature_var = tk.IntVar(value=STANDARD_TEMPERATURE)
        self.tint_var        = tk.IntVar(value=STANDARD_TINT)
        self.use_colorcor_var = tk.BooleanVar(value=False)

        cc_wrap = tk.Frame(bottom, bg=FIG_PANEL)
        cc_wrap.pack(fill=tk.X, padx=16, pady=(8, 10))

        # ── row 0: heading + actions ─────────────────────────────────
        cc_head = tk.Frame(cc_wrap, bg=FIG_PANEL)
        cc_head.pack(fill=tk.X, pady=(0, 8))

        tk.Label(cc_head, text="ЦВЕТОКОР", bg=FIG_PANEL, fg=FIG_TEXT2,
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)

        # switch + action buttons on the right
        cc_right = tk.Frame(cc_head, bg=FIG_PANEL)
        cc_right.pack(side=tk.RIGHT)
        self.colorcor_switch = self._make_switch(cc_right, self.use_colorcor_var, self.on_colorcor_toggle)
        self.colorcor_switch.pack(side=tk.LEFT, padx=(0, 12))
        ttk.Button(cc_right, text="Сохранить",
                   command=self.save_color_settings).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(cc_right, text="Сбросить",
                   command=self.reset_color_settings).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Button(cc_right, text="Применить к папке",
                   command=self.apply_look_to_folder).pack(side=tk.LEFT)

        # ── row 1: spinbox fields ─────────────────────────────────────
        cc_fields = tk.Frame(cc_wrap, bg=FIG_PANEL)
        cc_fields.pack(fill=tk.X)
        fields = [
            ("Контраст",    self.contrast_var,    -100, 100),
            ("Тени",        self.shadows_var,      -100, 100),
            ("Температура", self.temperature_var, 2000, 10000),
            ("Оттенок",     self.tint_var,         -100, 100),
        ]
        for lbl, var, lo, hi in fields:
            cell = tk.Frame(cc_fields, bg=FIG_PANEL)
            cell.pack(side=tk.LEFT, padx=(0, 18))
            tk.Label(cell, text=lbl, bg=FIG_PANEL, fg=FIG_TEXT2,
                     font=("Segoe UI", 9)).pack(anchor="w")
            sp = ttk.Spinbox(cell, from_=lo, to=hi, textvariable=var,
                             width=6, command=self.update_current)
            sp.pack(anchor="w")
            sp.bind("<KeyRelease>", lambda _e: self.update_current())

    def _slider(self, parent: tk.Frame, label: str, start: float, end: float,
                command, fmt: str = "{:.0f}") -> tk.DoubleVar:
        """
        Custom Canvas slider inspired by Adobe Photoshop:
          - thin dark track, accent-filled left portion
          - round light-gray thumb (visible against dark trough)
          - drag with mouse, fine-tune with scroll wheel
          - returns tk.DoubleVar (same interface as before)
        """
        TRACK_H = 3
        THUMB_R = 7
        BG = FIG_PANEL

        col = tk.Frame(parent, bg=BG)
        col.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 16))

        # ── header row: name left | value right ───
        hdr = tk.Frame(col, bg=BG)
        hdr.pack(fill=tk.X, pady=(0, 1))
        tk.Label(hdr, text=label, bg=BG, fg=FIG_TEXT2,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)
        val_str = tk.StringVar(value=fmt.format(0.0))
        tk.Label(hdr, textvariable=val_str, bg=BG, fg=FIG_ACCENT,
                 font=("Segoe UI", 9, "bold"), width=7, anchor="e").pack(side=tk.RIGHT)

        var = tk.DoubleVar(value=0.0)

        # ── canvas slider ───
        c = tk.Canvas(col, height=20, bg=BG, highlightthickness=0, bd=0, cursor="hand2")
        c.pack(fill=tk.X, pady=(2, 4))

        resolution = 0.01 if abs(end - start) <= 10 else 1.0

        def _redraw(*_: object) -> None:
            w = c.winfo_width()
            if w < 6:
                return
            c.delete("all")
            cy = 10
            r = THUMB_R
            # full track
            c.create_rectangle(r, cy - TRACK_H // 2,
                                w - r, cy + TRACK_H // 2 + 1,
                                fill=SL_TRACK, outline="", tags="track")
            # filled (left) portion
            ratio = max(0.0, min(1.0, (var.get() - start) / (end - start)))
            tx = r + ratio * (w - 2 * r)
            if tx > r + 1:
                c.create_rectangle(r, cy - TRACK_H // 2,
                                   tx, cy + TRACK_H // 2 + 1,
                                   fill=SL_ACTIVE, outline="", tags="active")
            # thumb
            c.create_oval(tx - r, cy - r, tx + r, cy + r,
                          fill=SL_THUMB, outline=SL_THUMB_BD, width=1, tags="thumb")

        def _val_from_x(x: int) -> float:
            w = c.winfo_width()
            r = THUMB_R
            ratio = max(0.0, min(1.0, (x - r) / max(1, w - 2 * r)))
            raw = start + ratio * (end - start)
            return round(raw / resolution) * resolution

        def _set(x: int) -> None:
            var.set(_val_from_x(x))
            command()

        def _on_scroll(event: tk.Event) -> None:
            step = resolution * (10 if event.state & 0x1 else 1)  # Shift = ×10
            delta = step if event.delta > 0 else -step
            var.set(max(start, min(end, var.get() + delta)))
            command()

        c.bind("<Configure>",     _redraw)
        c.bind("<ButtonPress-1>", lambda e: _set(e.x))
        c.bind("<B1-Motion>",     lambda e: _set(e.x))
        c.bind("<MouseWheel>",    _on_scroll)
        var.trace_add("write", lambda *_: (val_str.set(fmt.format(var.get())), c.after_idle(_redraw)))

        return var

    def _on_thumb_mousewheel(self, event: tk.Event) -> None:
        if not self.thumb_canvas.winfo_exists():
            return
        self.thumb_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def pick_folder(self) -> None:
        folder = filedialog.askdirectory(title="Выберите корневую папку")
        if folder:
            self.load_root(Path(folder))

    def _enable_drop_target(self) -> None:
        # Safe GUI drag-and-drop (no low-level WinAPI subclassing).
        if windnd is None:
            return
        try:
            windnd.hook_dropfiles(self, func=self._on_drop_files)
        except Exception:
            pass

    def _on_drop_files(self, files) -> None:
        dropped: list[str] = []
        for item in files:
            if isinstance(item, bytes):
                try:
                    dropped.append(item.decode("utf-8"))
                except UnicodeDecodeError:
                    dropped.append(item.decode("mbcs", errors="ignore"))
            else:
                dropped.append(str(item))

        folder = self._path_from_input(" ".join(f'"{item}"' for item in dropped if item))
        if folder is None:
            return
        self.after_idle(lambda: self.load_root(folder))

    def open_drop_window(self) -> None:
        if self.drop_window and self.drop_window.winfo_exists():
            self.drop_window.lift()
            self.drop_window.focus_force()
            return

        win = tk.Toplevel(self)
        win.title("Дроп файлов")
        win.geometry("500x260")
        win.minsize(420, 220)
        win.transient(self)
        win.grab_set()
        win.configure(bg=FIG_BG)
        self.drop_window = win

        panel = tk.Frame(win, bg=FIG_PANEL,
                         highlightbackground=FIG_ACCENT, highlightthickness=2)
        panel.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)
        label = tk.Label(
            panel,
            text="Перетащите сюда папку или файл\n\nПосле дропа окно закроется и путь загрузится в GUI",
            bg=FIG_PANEL,
            fg=FIG_TEXT,
            font=("Segoe UI", 12),
            justify=tk.CENTER,
        )
        label.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        buttons = tk.Frame(win, bg=FIG_BG)
        buttons.pack(fill=tk.X, padx=16, pady=(0, 12))
        ttk.Button(buttons, text="Выбрать папку…", command=lambda: self._pick_from_drop_window(win)).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Закрыть", command=win.destroy).pack(side=tk.RIGHT)

        def _cleanup() -> None:
            if self.drop_window is win:
                self.drop_window = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", _cleanup)

        if windnd is None:
            label.configure(text="windnd не найден.\nИспользуйте кнопку «Выбрать папку...»")
            return

        def on_drop(files) -> None:
            dropped: list[str] = []
            for item in files:
                if isinstance(item, bytes):
                    try:
                        dropped.append(item.decode("utf-8"))
                    except UnicodeDecodeError:
                        dropped.append(item.decode("mbcs", errors="ignore"))
                else:
                    dropped.append(str(item))
            folder = self._path_from_input(" ".join(f'"{item}"' for item in dropped if item))
            if folder is None:
                return

            def apply_drop() -> None:
                if win.winfo_exists():
                    _cleanup()
                self.load_root(folder)

            self.after_idle(apply_drop)

        try:
            windnd.hook_dropfiles(win, func=on_drop)
            windnd.hook_dropfiles(panel, func=on_drop)
            windnd.hook_dropfiles(label, func=on_drop)
        except Exception:
            label.configure(text="Не удалось включить дроп в этом окне.\nИспользуйте кнопку «Выбрать папку...»")

    def _pick_from_drop_window(self, win: tk.Toplevel) -> None:
        folder = filedialog.askdirectory(title="Выберите корневую папку")
        if not folder:
            return
        if win.winfo_exists():
            win.destroy()
        if self.drop_window is win:
            self.drop_window = None
        self.load_root(Path(folder))

    def _path_from_input(self, raw: str) -> Path | None:
        text = raw.strip()
        if not text:
            return None

        candidates: list[str] = []
        try:
            parts = self.tk.splitlist(text)
            candidates.extend([str(part) for part in parts if str(part).strip()])
        except tk.TclError:
            candidates.append(text)

        if not candidates:
            candidates.append(text)

        normalized: list[Path] = []
        for item in candidates:
            cleaned = item.strip().strip('"').strip("{}").strip()
            if not cleaned:
                continue
            normalized.append(Path(cleaned))

        if not normalized:
            return None

        for path in normalized:
            if path.exists():
                return path if path.is_dir() else path.parent

        first = normalized[0]
        return first if first.suffix == "" else first.parent

    def load_from_entry(self) -> None:
        folder = self._path_from_input(self.drop_var.get())
        if folder is None:
            messagebox.showerror(APP_NAME, "Укажите путь к папке или файлу.")
            return
        self.load_root(folder)

    def load_root(self, folder: Path) -> None:
        if folder.is_file():
            folder = folder.parent
        if not folder.exists() or not folder.is_dir():
            messagebox.showerror(APP_NAME, f"Папка не найдена:\n{folder}")
            return

        folder = folder.resolve()
        prev_root = self.root_folder.resolve() if self.root_folder else None
        if prev_root != folder:
            self.folder_states = {}
            self.selected_folder = None
            self.selected_index = 0

        self.load_token += 1
        token = self.load_token
        self.loading_frames = False
        self.pending_folder = None
        self.set_progress(0, "Ищу папки с исходниками...")
        self.root_folder = folder
        self.drop_var.set(str(folder))
        for item in self.folder_tree.get_children():
            self.folder_tree.delete(item)
        selected = self.folder_tree.selection()
        if selected:
            self.folder_tree.selection_remove(selected)
        self.clear_frames_view("Идет поиск папок...")

        threading.Thread(target=self.discover_worker, args=(token, folder), daemon=True).start()

    def discover_worker(self, token: int, folder: Path) -> None:
        start_time = time.monotonic()
        try:
            found = discover_source_folders(folder)
            elapsed = time.monotonic() - start_time
            self.worker_events.put(("discover_done", token, folder, found, elapsed))
        except Exception as exc:
            self.worker_events.put(("error", token, f"Ошибка поиска папок:\n{exc}"))

    def finish_discovery(self, token: int, folder: Path, found: list[Path], elapsed: float) -> None:
        if token != self.load_token:
            return
        if not found:
            self.set_progress(0, "Папки с исходниками не найдены")
            messagebox.showerror(APP_NAME, "Не найдено папок с исходниками")
            return

        old_states = self.folder_states
        self.folder_states = {}
        for source_folder in found:
            previous = old_states.get(source_folder)
            self.folder_states[source_folder] = previous if previous else FolderState(path=source_folder)

        self.render_folder_tree()
        self.set_progress(100, f"Найдено папок: {len(found)} за {elapsed:.1f} сек.")
        first_folder = found[0]
        self.after(0, lambda: self.select_folder(first_folder))

    def render_folder_tree(self) -> None:
        for item in self.folder_tree.get_children():
            self.folder_tree.delete(item)
        self.tree_path_by_iid.clear()
        self.tree_iid_by_path.clear()

        if not self.root_folder:
            return

        all_nodes: set[Path] = {self.root_folder}
        for folder in self.folder_states:
            current = folder
            while True:
                all_nodes.add(current)
                if current == self.root_folder:
                    break
                current = current.parent

        def sort_key(path: Path) -> tuple[int, str]:
            try:
                rel = path.relative_to(self.root_folder)
                depth = len(rel.parts)
                name = rel.parts[-1] if rel.parts else self.root_folder.name
            except ValueError:
                depth = 999
                name = str(path)
            return (depth, name.lower())

        for node in sorted(all_nodes, key=sort_key):
            parent = node.parent if node != self.root_folder else None
            parent_iid = self.tree_iid_by_path.get(parent, "")
            is_source = node in self.folder_states
            state = self.folder_states.get(node)
            check = "✓" if (state and state.checked) else (" " if is_source else "")
            count = len(direct_image_files(node)[:8]) if is_source else ""
            label = node.name if node != self.root_folder else self.root_folder.name
            iid = f"node_{len(self.tree_path_by_iid)}"
            self.folder_tree.insert(parent_iid, tk.END, iid=iid, text=label, values=(check, count), open=True)
            self.tree_path_by_iid[iid] = node
            self.tree_iid_by_path[node] = iid

    def on_folder_click(self, event: tk.Event) -> None:
        region = self.folder_tree.identify("region", event.x, event.y)
        column = self.folder_tree.identify_column(event.x)
        item = self.folder_tree.identify_row(event.y)
        if region == "cell" and column == "#1" and item:
            folder = self.tree_path_by_iid.get(item)
            if folder is None:
                return "break"
            state = self.folder_states.get(folder)
            if state:
                state.checked = not state.checked
                self.folder_tree.set(item, "check", "✓" if state.checked else " ")
            return "break"
        return None

    def on_folder_select(self, _event: tk.Event) -> None:
        selection = self.folder_tree.selection()
        if selection:
            folder = self.tree_path_by_iid.get(selection[0])
            if folder and folder in self.folder_states:
                self.select_folder(folder)

    def select_folder(self, folder: Path) -> None:
        self._save_controls_to_current()
        if folder not in self.folder_states:
            return
        if self.loading_frames:
            self.pending_folder = folder
            self.set_progress(self.progress_var.get(), f"Дождитесь загрузки. Следующая папка: {folder.name}")
            return
        self.selected_folder = folder
        iid = self.tree_iid_by_path.get(folder)
        if iid and tuple(self.folder_tree.selection()) != (iid,):
            self.folder_tree.selection_set(iid)
        state = self.folder_states[folder]
        if state.frames is None:
            self.start_load_frames(folder)
        else:
            self.selected_index = 0
            self.render_thumbnails()
            self.select_frame(0, save_previous=False)

    def start_load_frames(self, folder: Path) -> None:
        self.load_token += 1
        token = self.load_token
        self.loading_frames = True
        self.pending_folder = None
        self.clear_frames_view(f"Загружаю превью: {folder.name}")
        self.set_progress(0, f"Загружаю превью: {folder.name}")
        threading.Thread(target=self.load_frames_worker, args=(token, folder), daemon=True).start()

    def load_frames_worker(self, token: int, folder: Path) -> None:
        aspect = target_aspect(REFERENCE_DIR)
        paths = direct_image_files(folder)[:8]
        total = len(paths)
        frames: list[FrameState] = []
        start_time = time.monotonic()

        for index, path in enumerate(paths, start=1):
            elapsed = time.monotonic() - start_time
            eta = (elapsed / (index - 1) * (total - index + 1)) if index > 1 else 0.0
            self.worker_events.put(("progress", token, index - 1, total, f"Открываю {path.name}", eta))
            try:
                img = open_preview(path, max_side=WORKING_MAX_SIDE)
                frames.append(FrameState(path=path, frame=frame_id(path), image=img, crop_box=compute_auto_crop_box(path, img, aspect)))
            except Exception as exc:
                self.worker_events.put(("warning", token, f"Не удалось открыть {path.name}:\n{exc}"))

        elapsed = time.monotonic() - start_time
        self.worker_events.put(("frames_done", token, folder, frames, elapsed))

    def finish_frames(self, token: int, folder: Path, frames: list[FrameState], elapsed: float) -> None:
        if token != self.load_token or folder not in self.folder_states:
            return
        self.loading_frames = False
        self.folder_states[folder].frames = frames
        self.selected_index = 0
        self.render_thumbnails()
        self.select_frame(0, save_previous=False)
        self.set_progress(100, f"Загружено кадров: {len(frames)} за {elapsed:.1f} сек")
        if self.pending_folder and self.pending_folder != folder:
            pending = self.pending_folder
            self.pending_folder = None
            self.after(50, lambda: self.select_folder(pending))

    def load_frames_for_folder(self, folder: Path) -> list[FrameState]:
        state = self.folder_states[folder]
        if state.frames is not None:
            return state.frames

        aspect = target_aspect(REFERENCE_DIR)
        frames: list[FrameState] = []
        for path in direct_image_files(folder)[:8]:
            try:
                img = open_preview(path, max_side=WORKING_MAX_SIDE)
                frames.append(FrameState(path=path, frame=frame_id(path), image=img, crop_box=compute_auto_crop_box(path, img, aspect)))
            except Exception as exc:
                messagebox.showwarning(APP_NAME, f"Не удалось открыть {path.name}:\n{exc}")

        state.frames = frames
        return frames

    def clear_frames_view(self, message: str) -> None:
        for child in self.thumbs.winfo_children():
            child.destroy()
        self.thumb_photos = []
        self.info_var.set(message)
        self.preview.delete("all")

    def current_frames(self) -> list[FrameState]:
        if not self.selected_folder:
            return []
        return self.folder_states[self.selected_folder].frames or []

    def _highlight_selected_thumb(self) -> None:
        for i, btn in enumerate(self.thumb_btns):
            if not btn.winfo_exists():
                continue
            if i == self.selected_index:
                btn.configure(highlightbackground=FIG_ACCENT, highlightthickness=2, bd=0)
            else:
                btn.configure(highlightbackground=FIG_BORDER, highlightthickness=1, bd=0)

    def render_thumbnails(self) -> None:
        for child in self.thumbs.winfo_children():
            child.destroy()

        self.thumb_photos = []
        self.thumb_btns = []

        self.thumbs.grid_columnconfigure(0, weight=1, uniform="thumb")
        self.thumbs.grid_columnconfigure(1, weight=1, uniform="thumb")

        card_w = THUMB_SIZE[0]

        for index, state in enumerate(self.current_frames()):
            is_selected = (index == self.selected_index)

            card = tk.Frame(self.thumbs, bg=FIG_SURFACE, width=card_w)
            card.grid(row=index // 2, column=index % 2, padx=4, pady=5, sticky="n")
            card.configure(highlightthickness=1, highlightbackground=FIG_BORDER)

            badge_row = tk.Frame(card, bg=FIG_SURFACE, width=card_w)
            badge_row.pack(fill=tk.X, pady=(0, 2))
            badge_row.pack_propagate(False)
            tk.Label(badge_row, text=f"  {state.frame}", bg=FIG_ACCENT if is_selected else FIG_BTN,
                     fg="#ffffff", font=("Segoe UI", 8, "bold"),
                     padx=4, pady=1).pack(side=tk.LEFT)
            chk = self._make_check(
                badge_row,
                state.checked,
                lambda value, i=index: self.toggle_frame(i, value),
                bg=FIG_SURFACE,
                tooltip_text="Галочка включает/исключает кадр из экспорта",
            )
            chk.pack(side=tk.RIGHT, padx=(0, 2))
            chk.bind("<MouseWheel>", self._on_thumb_mousewheel)

            if state.thumb_cache is None:
                thumb = render_frame(state, THUMB_SIZE)
                if self.use_colorcor_var.get():
                    state.thumb_cache = apply_standard_look(
                        thumb,
                        contrast=state.contrast,
                        shadows=state.shadows,
                        temperature=state.temperature,
                        tint=state.tint,
                    )
                else:
                    state.thumb_cache = thumb
            photo = ImageTk.PhotoImage(state.thumb_cache)
            self.thumb_photos.append(photo)

            btn = tk.Label(
                card, image=photo, bg=FIG_SURFACE, cursor="hand2",
                highlightbackground=FIG_ACCENT if is_selected else FIG_BORDER,
                highlightthickness=2 if is_selected else 1,
            )
            btn.pack()
            self.thumb_btns.append(btn)
            btn.bind("<Button-1>", lambda _e, i=index: self.select_frame(i))
            btn.bind("<Enter>", lambda _e, b=btn, i=index: (
                b.configure(highlightbackground=FIG_ACCENT, highlightthickness=2)
                if i != self.selected_index else None
            ))
            btn.bind("<Leave>", lambda _e, b=btn, i=index: (
                b.configure(highlightbackground=FIG_BORDER, highlightthickness=1)
                if i != self.selected_index else None
            ))

            # filename below thumb
            short_name = state.path.name
            if len(short_name) > 16:
                short_name = short_name[:13] + "…"
            tk.Label(card, text=short_name, bg=FIG_SURFACE, fg=FIG_TEXT2,
                     font=("Segoe UI", 8), width=18, anchor="w").pack(anchor="w", pady=(2, 0))
            for widget in (card, badge_row, btn):
                widget.bind("<MouseWheel>", self._on_thumb_mousewheel)

        if hasattr(self, "thumb_canvas"):
            self.thumb_canvas.update_idletasks()
            self.thumb_canvas.configure(scrollregion=self.thumb_canvas.bbox("all"))
            self.thumb_canvas.yview_moveto(0)

    def toggle_frame(self, index: int, checked: bool) -> None:
        frames = self.current_frames()
        if 0 <= index < len(frames):
            frames[index].checked = checked

    def _coerce_int(self, var: tk.IntVar, fallback: int, min_value: int, max_value: int) -> int:
        try:
            value = int(var.get())
        except Exception:
            value = fallback
        value = max(min_value, min(max_value, value))
        var.set(value)
        return value

    def _save_controls_to_current(self) -> None:
        if self._updating_controls:
            return
        state = self.current()
        if not state:
            return
        state.offset_x = self.offset_x.get()
        state.offset_y = self.offset_y.get()
        state.zoom = self.zoom.get() or 1.0
        state.rotation = self.rotation.get()
        state.profile = self.profile_var.get() or STANDARD_PROFILE
        state.contrast = self._coerce_int(self.contrast_var, STANDARD_CONTRAST, -100, 100)
        state.shadows = self._coerce_int(self.shadows_var, STANDARD_SHADOWS, -100, 100)
        state.temperature = self._coerce_int(self.temperature_var, STANDARD_TEMPERATURE, 2000, 10000)
        state.tint = self._coerce_int(self.tint_var, STANDARD_TINT, -100, 100)

    def select_frame(self, index: int, *, save_previous: bool = True) -> None:
        if save_previous:
            self._save_controls_to_current()
        frames = self.current_frames()
        if not frames:
            self.info_var.set("В выбранной папке нет кадров")
            self.preview.delete("all")
            return

        self.selected_index = max(0, min(index, len(frames) - 1))
        state = frames[self.selected_index]
        self._updating_controls = True
        self.offset_x.set(state.offset_x)
        self.offset_y.set(state.offset_y)
        self.zoom.set(state.zoom)
        self.rotation.set(state.rotation)
        self.profile_var.set(state.profile)
        self.contrast_var.set(state.contrast)
        self.shadows_var.set(state.shadows)
        self.temperature_var.set(state.temperature)
        self.tint_var.set(state.tint)
        self._updating_controls = False
        folder_text = self.selected_folder.name if self.selected_folder else ""
        self.info_var.set(
            f"📁  {folder_text}\n"
            f"🖼  {state.frame} — {state.path.name}\n"
            f"⌨  Стрелки / мышь / колесо"
        )
        self.preview.focus_set()
        self._highlight_selected_thumb()
        self.render_preview()

    def current(self) -> FrameState | None:
        frames = self.current_frames()
        if not frames:
            return None
        return frames[self.selected_index]

    def update_current(self) -> None:
        if self._updating_controls:
            return
        state = self.current()
        if not state:
            return
        self._save_controls_to_current()
        state.thumb_cache = None
        self.render_preview()

    def render_preview(self) -> None:
        state = self.current()
        if not state:
            return

        img = render_frame(state, PREVIEW_SIZE)
        if self.use_colorcor_var.get():
            img = apply_standard_look(
                img,
                contrast=state.contrast,
                shadows=state.shadows,
                temperature=state.temperature,
                tint=state.tint,
            )
        self.preview_photo = ImageTk.PhotoImage(img)
        self.preview.delete("all")
        self.preview.create_image(0, 0, image=self.preview_photo, anchor=tk.NW)
        self.draw_guides(state.frame)

    def on_colorcor_toggle(self) -> None:
        if hasattr(self, "colorcor_switch"):
            self._draw_switch(self.colorcor_switch, bool(self.use_colorcor_var.get()))
        for folder_state in self.folder_states.values():
            if not folder_state.frames:
                continue
            for st in folder_state.frames:
                st.thumb_cache = None
        self.render_thumbnails()
        self.render_preview()

    def save_color_settings(self) -> None:
        self.update_current()
        current = self.current()
        if not current:
            self.set_progress(self.progress_var.get(), "Нет выбранного кадра для сохранения настроек")
            return
        current.profile = self.profile_var.get() or STANDARD_PROFILE
        current.contrast = self._coerce_int(self.contrast_var, STANDARD_CONTRAST, -100, 100)
        current.shadows = self._coerce_int(self.shadows_var, STANDARD_SHADOWS, -100, 100)
        current.temperature = self._coerce_int(self.temperature_var, STANDARD_TEMPERATURE, 2000, 10000)
        current.tint = self._coerce_int(self.tint_var, STANDARD_TINT, -100, 100)
        current.thumb_cache = None
        self.render_thumbnails()
        self.render_preview()
        self.set_progress(self.progress_var.get(), "Настройки цветокора сохранены для текущего кадра")

    def reset_color_settings(self) -> None:
        self.profile_var.set(STANDARD_PROFILE)
        self.contrast_var.set(STANDARD_CONTRAST)
        self.shadows_var.set(STANDARD_SHADOWS)
        self.temperature_var.set(STANDARD_TEMPERATURE)
        self.tint_var.set(STANDARD_TINT)
        self.update_current()
        current = self.current()
        if current:
            current.profile = STANDARD_PROFILE
            current.contrast = STANDARD_CONTRAST
            current.shadows = STANDARD_SHADOWS
            current.temperature = STANDARD_TEMPERATURE
            current.tint = STANDARD_TINT
            current.thumb_cache = None
        self.render_thumbnails()
        self.render_preview()
        self.set_progress(self.progress_var.get(), "Настройки цветокора сброшены")

    def apply_look_to_folder(self) -> None:
        self.update_current()
        current = self.current()
        frames = self.current_frames()
        if not current or not frames:
            return
        for state in frames:
            state.profile = current.profile
            state.contrast = current.contrast
            state.shadows = current.shadows
            state.temperature = current.temperature
            state.tint = current.tint
            state.thumb_cache = None
        self.render_thumbnails()
        self.render_preview()

    def draw_guides(self, frame: str) -> None:
        rule = LAYOUT_RULES.get(frame)
        if not rule or rule.manual_only:
            return

        sx = PREVIEW_SIZE[0] / CANVAS_SIZE[0]
        sy = PREVIEW_SIZE[1] / CANVAS_SIZE[1]
        blue = "#008cff"

        if rule.x_px is not None and rule.mode == "width":
            left = rule.x_px * sx
            right = (rule.x_px + rule.target_px) * sx
            self.preview.create_line(left, 0, left, PREVIEW_SIZE[1], fill=blue, width=2)
            self.preview.create_line(right, 0, right, PREVIEW_SIZE[1], fill=blue, width=2)

        if rule.y_top_px is not None:
            y = rule.y_top_px * sy
            self.preview.create_line(0, y, PREVIEW_SIZE[0], y, fill=blue, width=2)

        if rule.y_bottom_px is not None:
            y = (CANVAS_SIZE[1] - rule.y_bottom_px) * sy
            self.preview.create_line(0, y, PREVIEW_SIZE[0], y, fill=blue, width=2)

    def start_drag(self, event: tk.Event) -> None:
        state = self.current()
        if state:
            self.preview.focus_set()
            self.drag_start = (event.x, event.y, state.offset_x, state.offset_y)

    def stop_drag(self, _event: tk.Event) -> None:
        self.drag_start = None

    def drag_preview(self, event: tk.Event) -> None:
        if not self.drag_start:
            return
        start_x, start_y, base_x, base_y = self.drag_start
        # Drag conversion should match the preview render size.
        scale_x = CANVAS_SIZE[0] / PREVIEW_SIZE[0]
        scale_y = CANVAS_SIZE[1] / PREVIEW_SIZE[1]
        self.offset_x.set(base_x + (event.x - start_x) * scale_x)
        self.offset_y.set(base_y + (event.y - start_y) * scale_y)
        self.update_current()

    def mousewheel_zoom(self, event: tk.Event) -> None:
        delta = 0.04 if event.delta > 0 else -0.04
        self.zoom.set(max(0.5, min(ZOOM_MAX, self.zoom.get() + delta)))
        self.update_current()

    def nudge_current(self, dx: float, dy: float) -> str:
        state = self.current()
        if not state:
            return "break"
        state.offset_x += dx
        state.offset_y += dy
        state.thumb_cache = None
        self._updating_controls = True
        self.offset_x.set(state.offset_x)
        self.offset_y.set(state.offset_y)
        self._updating_controls = False
        self.render_preview()
        return "break"

    def reset_current(self) -> None:
        state = self.current()
        if not state:
            return
        state.offset_x = 0.0
        state.offset_y = 0.0
        state.zoom = 1.0
        state.rotation = 0.0
        state.thumb_cache = None
        self.select_frame(self.selected_index)

    def reset_folder(self) -> None:
        for state in self.current_frames():
            state.offset_x = 0.0
            state.offset_y = 0.0
            state.zoom = 1.0
            state.rotation = 0.0
            state.thumb_cache = None
        self.select_frame(self.selected_index)

    def export_checked(self) -> None:
        self._save_controls_to_current()
        if self.loading_frames:
            messagebox.showwarning(APP_NAME, "Дождитесь окончания загрузки превью")
            return
        checked_folders = [state.path for state in self.folder_states.values() if state.checked]
        if not checked_folders:
            messagebox.showerror(APP_NAME, "Нет отмеченных папок для экспорта")
            return

        self.load_token += 1
        token = self.load_token
        use_droplets = bool(self.use_droplet_var.get())
        use_colorcor = bool(self.use_colorcor_var.get())
        self.set_progress(0, "Готовлю экспорт...")
        threading.Thread(target=self.export_worker, args=(token, checked_folders, use_droplets, use_colorcor), daemon=True).start()

    def export_worker(self, token: int, checked_folders: list[Path], use_droplets: bool, use_colorcor: bool) -> None:
        exported = 0
        droplet_processed = 0
        total_units = 0
        for folder in checked_folders:
            folder_state = self.folder_states.get(folder)
            if not folder_state:
                continue
            if folder_state.frames is None:
                source_paths = direct_image_files(folder)[:8]
                total_units += len(source_paths) * 2
                if use_droplets:
                    total_units += len([path for path in source_paths if frame_id(path) in DROPLET_BY_FRAME])
            else:
                checked_frames = [frame for frame in folder_state.frames if frame.checked]
                total_units += len(checked_frames)
                if use_droplets:
                    total_units += len([frame for frame in checked_frames if frame.frame in DROPLET_BY_FRAME])
        total_units = max(1, total_units)
        done_units = 0
        start_time = time.monotonic()
        aspect = target_aspect(REFERENCE_DIR)
        exported_for_droplets: list[tuple[Path, str]] = []

        for folder in checked_folders:
            if token != self.load_token:
                return

            folder_state = self.folder_states.get(folder)
            if not folder_state:
                continue

            frames = folder_state.frames
            if frames is None:
                frames = []
                paths = direct_image_files(folder)[:8]
                for path in paths:
                    elapsed = time.monotonic() - start_time
                    eta = (elapsed / max(1, done_units) * max(0, total_units - done_units)) if done_units else 0.0
                    self.worker_events.put(("progress", token, done_units, total_units, f"Открываю {folder.name}\\{path.name}", eta))
                    try:
                        img = open_preview(path, max_side=WORKING_MAX_SIDE)
                        frames.append(FrameState(path=path, frame=frame_id(path), image=img, crop_box=compute_auto_crop_box(path, img, aspect)))
                    except Exception as exc:
                        self.worker_events.put(("warning", token, f"Не удалось открыть {path.name}:\n{exc}"))
                    done_units += 1
                folder_state.frames = frames

            checked_frames = [frame for frame in frames if frame.checked]
            if not checked_frames:
                continue

            output_dir = folder / folder.name
            output_dir.mkdir(parents=True, exist_ok=True)
            for frame in checked_frames:
                elapsed = time.monotonic() - start_time
                eta = (elapsed / max(1, done_units) * max(0, total_units - done_units)) if done_units else 0.0
                self.worker_events.put(("progress", token, done_units, total_units, f"Экспорт {folder.name}\\{frame.path.stem}.jpg", eta))
                # Экспорт в том же разрешении, что и редактор — иначе crop_box и смещения расходятся.
                export_image = frame.image
                export_crop = frame.crop_box
                output = render_frame(frame, CANVAS_SIZE, source_image=export_image, crop_box=export_crop)
                if use_colorcor:
                    output = apply_standard_look(
                        output,
                        contrast=frame.contrast,
                        shadows=frame.shadows,
                        temperature=frame.temperature,
                        tint=frame.tint,
                    )
                output_path = output_dir / f"{frame.path.stem}.jpg"
                output.save(
                    output_path,
                    format="JPEG",
                    quality=98,
                    subsampling=0,
                    optimize=False,
                    progressive=True,
                )
                exported_for_droplets.append((output_path, frame.frame))
                exported += 1
                done_units += 1

        if use_droplets and exported_for_droplets:
            grouped: dict[str, list[Path]] = {}
            for output_path, frame in exported_for_droplets:
                droplet_name = DROPLET_BY_FRAME.get(frame)
                if not droplet_name:
                    continue
                grouped.setdefault(droplet_name, []).append(output_path)

            for droplet_name, paths in grouped.items():
                droplet_exe = DROPLETS_DIR / droplet_name
                if not droplet_exe.exists():
                    self.worker_events.put(("warning", token, f"Дроплет не найден:\n{droplet_exe}"))
                    continue
                for output_path in paths:
                    if token != self.load_token:
                        return
                    elapsed = time.monotonic() - start_time
                    eta = (elapsed / max(1, done_units) * max(0, total_units - done_units)) if done_units else 0.0
                    self.worker_events.put(
                        ("progress", token, done_units, total_units, f"Дроплет {droplet_name}: {output_path.name}", eta)
                    )
                    try:
                        before_stat = output_path.stat()
                        result = subprocess.run([str(droplet_exe), str(output_path)], capture_output=True, text=True)
                        stderr_text = (result.stderr or "").strip()
                        stdout_text = (result.stdout or "").strip()

                        after_exists = output_path.exists()
                        after_stat = output_path.stat() if after_exists else None
                        changed = bool(after_stat and (after_stat.st_mtime_ns != before_stat.st_mtime_ns or after_stat.st_size != before_stat.st_size))

                        # Photoshop droplet can return code 1 even when file is processed.
                        # Treat that as soft success when there is no explicit error text.
                        soft_success = (
                            result.returncode == 1
                            and after_exists
                            and after_stat is not None
                            and after_stat.st_size > 0
                            and not stderr_text
                            and (changed or not stdout_text)
                        )

                        if result.returncode != 0 and not soft_success:
                            error_text = stderr_text or stdout_text or f"code {result.returncode}"
                            self.worker_events.put(
                                ("warning", token, f"Ошибка дроплета {droplet_name} для {output_path.name}:\n{error_text}")
                            )
                    except Exception as exc:
                        self.worker_events.put(
                            ("warning", token, f"Не удалось запустить дроплет {droplet_name}:\n{exc}")
                        )
                    droplet_processed += 1
                    done_units += 1

        elapsed = time.monotonic() - start_time
        self.worker_events.put(("export_done", token, exported, droplet_processed, elapsed))

    def set_progress(self, value: float, text: str) -> None:
        self.progress_var.set(max(0, min(100, value)))
        self.progress_label.set(text)

    def process_worker_events(self) -> None:
        while True:
            try:
                event = self.worker_events.get_nowait()
            except queue.Empty:
                break

            kind = event[0]
            if kind == "discover_done":
                _, token, folder, found, elapsed = event
                self.finish_discovery(token, folder, found, elapsed)
            elif kind == "frames_done":
                _, token, folder, frames, elapsed = event
                self.finish_frames(token, folder, frames, elapsed)
            elif kind == "progress":
                _, token, done, total, label, eta = event
                if token == self.load_token:
                    percent = (done / total * 100) if total else 0
                    eta_text = f", осталось ~{eta:.0f} сек" if eta else ""
                    self.set_progress(percent, f"{label} ({done}/{total}{eta_text})")
            elif kind == "export_done":
                _, token, exported, droplet_processed, elapsed = event
                if token == self.load_token:
                    info = f"Экспорт готов: {exported} файлов за {elapsed:.1f} сек"
                    if droplet_processed:
                        info += f" (дроплет: {droplet_processed})"
                    self.set_progress(100, info)
                    self.render_thumbnails()
                    msg = f"Экспорт готов. Файлов: {exported}"
                    if droplet_processed:
                        msg += f"\nЧерез дроплеты обработано: {droplet_processed}"
                    messagebox.showinfo(APP_NAME, msg)
            elif kind == "warning":
                _, token, text = event
                if token == self.load_token:
                    messagebox.showwarning(APP_NAME, text)
            elif kind == "error":
                _, token, text = event
                if token == self.load_token:
                    self.loading_frames = False
                    self.set_progress(0, "Ошибка")
                    messagebox.showerror(APP_NAME, text)

        self.after(100, self.process_worker_events)


def main() -> int:
    folder: Path | None = None
    if len(sys.argv) > 1:
        raw_items = [arg for arg in sys.argv[1:] if arg.strip()]
        parsed: list[Path] = []
        for item in raw_items:
            cleaned = item.strip().strip('"').strip("{}").strip()
            if cleaned:
                parsed.append(Path(cleaned))
        for path in parsed:
            if path.exists():
                folder = path if path.is_dir() else path.parent
                break
        if folder is None and parsed:
            first = parsed[0]
            folder = first if first.suffix == "" else first.parent
    app = AutoRawGui(folder)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
