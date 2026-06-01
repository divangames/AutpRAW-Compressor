from __future__ import annotations

import json
import sys
import queue
import subprocess
import threading

# Windows: locale cp1251 ломает чтение stdout wmic/nvidia-smi/дроплетов в _readerthread
_SUBPROC_TEXT = dict(capture_output=True, text=True, encoding="utf-8", errors="replace")
import time
import math
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import socket

try:
    import psutil as _psutil  # type: ignore[import-not-found]
except ImportError:
    _psutil = None  # type: ignore[assignment]

try:
    import pynvml as _pynvml  # type: ignore[import-not-found]
    _pynvml.nvmlInit()
    _GPU_HANDLE = _pynvml.nvmlDeviceGetHandleByIndex(0)
    _HAS_GPU = True
except Exception:
    _pynvml = None  # type: ignore[assignment]
    _GPU_HANDLE = None
    _HAS_GPU = False

try:
    import windnd  # type: ignore[import-not-found]
except Exception:
    windnd = None

from PIL import Image, ImageEnhance, ImageOps, ImageTk

from app_paths import resource_path
from version import APP_NAME, APP_TITLE, version_string
from updater import (
    RELEASES_PAGE,
    UpdateInfo,
    can_self_update,
    fetch_latest_update,
    run_update,
)
from autoraw_crop import (
    CANVAS_SIZE,
    LAYOUT_RULES,
    Box,
    compute_auto_crop_box,
    detect_object_on_image,
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
        BG="#141414", PANEL="#1e1e1e", PANEL_L="#2a2a2a",
        SURFACE="#232323", BORDER="#363636",
        TEXT="#e0e0e0", TEXT2="#7a7a7a",
        ACCENT="#4d9cf5", ACCENT_H="#70b5ff",
        SEL="#1a3d6b", INPUT="#111111", BTN="#2e2e2e",
        SL_TRACK="#0a0a0a", SL_ACTIVE="#4d9cf5",
        SL_THUMB="#9ca8b4", SL_THUMB_BD="#606878",
        PREVIEW_BG="#080808",
    ),
    "light": dict(
        BG="#f0f0f0", PANEL="#e2e2e2", PANEL_L="#d0d0d0",
        SURFACE="#e8e8e8", BORDER="#c0c0c0",
        TEXT="#1a1a1a", TEXT2="#565656",
        ACCENT="#0078d4", ACCENT_H="#0063b1",
        SEL="#cce4ff", INPUT="#fafafa", BTN="#d4d4d4",
        SL_TRACK="#b8b8b8", SL_ACTIVE="#0078d4",
        SL_THUMB="#484848", SL_THUMB_BD="#808080",
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


class JobControl:
    """Пауза / отмена фоновой задачи и учёт времени без пауз."""

    def __init__(self) -> None:
        self.cancelled = False
        self.paused = False
        self._segment_start = 0.0
        self._active_elapsed = 0.0

    def reset(self) -> None:
        self.cancelled = False
        self.paused = False
        self._segment_start = time.monotonic()
        self._active_elapsed = 0.0

    def pause(self) -> None:
        if not self.paused and not self.cancelled:
            self._active_elapsed += time.monotonic() - self._segment_start
            self.paused = True

    def resume(self) -> None:
        if self.paused and not self.cancelled:
            self.paused = False
            self._segment_start = time.monotonic()

    def cancel(self) -> None:
        self.cancelled = True
        self.paused = False

    def wait_if_paused(self) -> None:
        while self.paused and not self.cancelled:
            time.sleep(0.08)

    def active_elapsed(self) -> float:
        if self.paused:
            return self._active_elapsed
        return self._active_elapsed + (time.monotonic() - self._segment_start)

    def should_stop(self, token: int, current_token: int) -> bool:
        self.wait_if_paused()
        return self.cancelled or token != current_token


def _load_zona_data() -> dict[str, str]:
    """Parse src/zona/data.dat → {TOKEN, ID, URL, …}.

    Search order:
      1. Next to this .py file — works in development (src/zona/data.dat)
      2. app_root()/zona/data.dat  — works in PyInstaller frozen build
    """
    candidates = [
        Path(__file__).parent / "zona" / "data.dat",
        resource_path("zona", "data.dat"),
    ]
    for path in candidates:
        if path.exists():
            try:
                result: dict[str, str] = {}
                for line in path.read_text(encoding="utf-8").splitlines():
                    if ":" in line:
                        key, _, val = line.partition(":")
                        result[key.strip().upper()] = val.strip()
                return result
            except Exception:
                pass
    return {}


def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_config(data: dict) -> None:
    try:
        _CONFIG_PATH.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


def _load_theme_choice() -> str:
    v = _load_config().get("theme", "system")
    return v if v in ("dark", "light", "system") else "system"


def _save_theme_choice(choice: str) -> None:
    cfg = _load_config()
    cfg["theme"] = choice
    _save_config(cfg)


# Apply initial palette so module-level constants are set before class creation
_apply_palette("dark")
REFERENCE_DIR = resource_path("reference", "Sneakers")
SEARCH_REFERENCE_DIR = REFERENCE_DIR / "search"
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
    match_score: float | None = None
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


MATCH_SIZE = (96, 72)
_SEARCH_SIGNATURES: dict[str, tuple[list[float], list[float], tuple[float, float, float, float]]] | None = None


def _frame_label_from_path(path: Path) -> str | None:
    frame = frame_id(path)
    return frame if frame.isdigit() and 1 <= int(frame) <= 99 else None


def _fit_gray_vector(img: Image.Image) -> list[float]:
    gray = ImageOps.autocontrast(img.convert("L"))
    gray = ImageOps.fit(gray, MATCH_SIZE, Image.Resampling.LANCZOS)
    return [px / 255.0 for px in gray.tobytes()]


def _image_signature(img: Image.Image) -> tuple[list[float], list[float], tuple[float, float, float, float]]:
    oriented = ImageOps.exif_transpose(img).convert("RGB")
    full_vec = _fit_gray_vector(oriented)
    box, _ = detect_object_on_image(oriented, None)

    if box is None:
        obj = oriented
        geom = (1.0, 1.0, 0.5, 0.5)
    else:
        pad_x = int(box.width * 0.08)
        pad_y = int(box.height * 0.08)
        crop_box = Box(
            box.left - pad_x,
            box.top - pad_y,
            box.right + pad_x,
            box.bottom + pad_y,
        ).clamp(oriented.width, oriented.height)
        obj = oriented.crop((crop_box.left, crop_box.top, crop_box.right, crop_box.bottom))
        geom = (
            box.width / max(1, oriented.width),
            box.height / max(1, oriented.height),
            (box.left + box.right) / (2 * max(1, oriented.width)),
            (box.top + box.bottom) / (2 * max(1, oriented.height)),
        )

    return full_vec, _fit_gray_vector(obj), geom


def _vector_distance(a: list[float], b: list[float]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / max(1, min(len(a), len(b)))


def _signature_distance(
    a: tuple[list[float], list[float], tuple[float, float, float, float]],
    b: tuple[list[float], list[float], tuple[float, float, float, float]],
) -> float:
    full_a, obj_a, geom_a = a
    full_b, obj_b, geom_b = b
    geom = sum(abs(x - y) for x, y in zip(geom_a, geom_b)) / 4.0
    return _vector_distance(full_a, full_b) * 0.35 + _vector_distance(obj_a, obj_b) * 0.55 + geom * 0.10


def _load_search_signatures() -> dict[str, tuple[list[float], list[float], tuple[float, float, float, float]]]:
    global _SEARCH_SIGNATURES
    if _SEARCH_SIGNATURES is not None:
        return _SEARCH_SIGNATURES

    signatures: dict[str, tuple[list[float], list[float], tuple[float, float, float, float]]] = {}
    if SEARCH_REFERENCE_DIR.is_dir():
        for path in sorted(SEARCH_REFERENCE_DIR.iterdir(), key=frame_sort_key):
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            frame = _frame_label_from_path(path)
            if not frame:
                continue
            try:
                with Image.open(path) as img:
                    signatures[frame] = _image_signature(img)
            except Exception:
                continue

    _SEARCH_SIGNATURES = signatures
    return signatures


def assign_frames_by_search(
    loaded: list[tuple[Path, Image.Image]],
) -> list[tuple[Path, Image.Image, str, float | None]]:
    """Assign source images to frame numbers using reference/Sneakers/search."""
    refs = _load_search_signatures()
    if not refs:
        return [(path, img, frame_id(path), None) for path, img in loaded]

    source_sigs: list[tuple[int, tuple[list[float], list[float], tuple[float, float, float, float]]]] = []
    for index, (_path, img) in enumerate(loaded):
        try:
            source_sigs.append((index, _image_signature(img)))
        except Exception:
            continue

    pairs: list[tuple[float, int, str]] = []
    for index, sig in source_sigs:
        for frame, ref_sig in refs.items():
            pairs.append((_signature_distance(sig, ref_sig), index, frame))
    pairs.sort(key=lambda item: item[0])

    assigned_by_index: dict[int, tuple[str, float]] = {}
    used_frames: set[str] = set()
    for score, index, frame in pairs:
        if index in assigned_by_index or frame in used_frames:
            continue
        assigned_by_index[index] = (frame, score)
        used_frames.add(frame)
        if len(assigned_by_index) == min(len(loaded), len(refs)):
            break

    fallback_frames = [frame for frame in sorted(refs, key=lambda f: int(f)) if frame not in used_frames]
    result: list[tuple[Path, Image.Image, str, float | None]] = []
    for index, (path, img) in enumerate(loaded):
        if index in assigned_by_index:
            frame, score = assigned_by_index[index]
        elif fallback_frames:
            frame, score = fallback_frames.pop(0), None
        else:
            frame, score = frame_id(path), None
        result.append((path, img, frame, score))

    return sorted(result, key=lambda item: (int(item[2]) if item[2].isdigit() else 999, item[0].name.lower()))


def crop_box_for_assigned_frame(path: Path, img: Image.Image, aspect: float, frame: str) -> Box:
    fake_path = Path(f"{frame}{path.suffix}")
    return compute_auto_crop_box(fake_path, img, aspect)


def export_name_for_frame(frame: FrameState) -> str:
    if frame.frame.isdigit():
        return f"{int(frame.frame)}.jpg"
    return f"{frame.path.stem}.jpg"


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
        # (px, py, base_offset_x, base_offset_y, base_rotation)
        self.drag_start: tuple[int, int, float, float, float] | None = None
        self._updating_controls = False
        self.worker_events: queue.Queue[tuple] = queue.Queue()
        self.load_token = 0
        self.loading_frames = False
        self.pending_folder: Path | None = None
        self.tree_path_by_iid: dict[str, Path] = {}
        self.tree_iid_by_path: dict[Path, str] = {}
        self.drop_window: tk.Toplevel | None = None
        self._menu_popups: list[tk.Toplevel] = []
        self.thumb_btns: list[tk.Label] = []
        self._export_job = JobControl()
        self._export_running = False
        self._export_token = 0
        self._update_skipped_session: set[str] = set()

        # Theme – must be set before _build_ui() applies palette
        self._theme_choice: str = _load_theme_choice()
        dark = self._resolve_dark(self._theme_choice)
        _apply_palette("dark" if dark else "light")

        self._etalon_path: str | None = _load_config().get("etalon")

        self._build_ui()
        self._set_window_icon()
        self.bind("<Map>", lambda _e: self._schedule_dark_titlebar(), add="+")
        self.after_idle(self._schedule_dark_titlebar)
        self.after(50, self._enable_drop_target)
        self.after(100, self.process_worker_events)
        self.after(500, self._start_sysmon)
        self.after(2000, self._startup_update_check)

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
        self._schedule_dark_titlebar()

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

    def _set_window_icon(self, window: tk.Tk | tk.Toplevel | None = None) -> None:
        """Apply app icon to root or any child dialog."""
        target = window or self
        icon_path = resource_path("assets", "image", "favicon.ico")
        if not icon_path.is_file():
            return
        try:
            target.iconbitmap(str(icon_path))
        except tk.TclError:
            pass

    def _prepare_dialog_window(self, window: tk.Toplevel) -> None:
        """Apply common dark-window integration to Toplevel dialogs."""
        self._set_window_icon(window)
        self._schedule_dark_titlebar(window)
        window.bind("<Map>", lambda _e, w=window: self._schedule_dark_titlebar(w), add="+")
        window.after_idle(lambda w=window: self._schedule_dark_titlebar(w))

    def _setup_theme(self) -> None:
        self.configure(bg=FIG_BG)

        # Kill ALL native tk highlight/border artifacts globally
        self.option_add("*highlightThickness",   0)
        self.option_add("*highlightBackground",  FIG_BG)
        self.option_add("*highlightColor",       FIG_ACCENT)
        self.option_add("*borderWidth",          0)
        self.option_add("*relief",               "flat")
        self.option_add("*Background",           FIG_PANEL)
        self.option_add("*Foreground",           FIG_TEXT)
        self.option_add("*selectBackground",     FIG_SEL)
        self.option_add("*selectForeground",     "#ffffff")
        self.option_add("*insertBackground",     FIG_TEXT)
        self.option_add("*activeBackground",     FIG_PANEL_L)
        self.option_add("*activeForeground",     "#ffffff")

        # ── Force dark theme on ALL tk.Menu instances ─────────────
        self.option_add("*Menu.background",          FIG_PANEL,  "widgetDefault")
        self.option_add("*Menu.foreground",          FIG_TEXT,   "widgetDefault")
        self.option_add("*Menu.activeBackground",    FIG_PANEL_L, "widgetDefault")
        self.option_add("*Menu.activeForeground",    "#ffffff",  "widgetDefault")
        self.option_add("*Menu.disabledForeground",  FIG_TEXT2,  "widgetDefault")
        self.option_add("*Menu.selectColor",         FIG_ACCENT, "widgetDefault")
        self.option_add("*Menu.relief",              "flat",     "widgetDefault")
        self.option_add("*Menu.borderWidth",         0,          "widgetDefault")
        self.option_add("*Menu.activeBorderWidth",   0,          "widgetDefault")
        self.option_add("*Menu.font",     ("Segoe UI", 10),      "widgetDefault")
        self.option_add("*Menu.tearOff",             0,          "widgetDefault")

        # Tk/ttk dropdown popups use a hidden Listbox on Windows.
        self.option_add("*Listbox.background",          FIG_PANEL,   "widgetDefault")
        self.option_add("*Listbox.foreground",          FIG_TEXT,    "widgetDefault")
        self.option_add("*Listbox.selectBackground",    FIG_PANEL_L, "widgetDefault")
        self.option_add("*Listbox.selectForeground",    "#ffffff",   "widgetDefault")
        self.option_add("*Listbox.highlightThickness",  0,           "widgetDefault")
        self.option_add("*Listbox.borderWidth",         1,           "widgetDefault")
        self.option_add("*Listbox.relief",              "flat",      "widgetDefault")
        self.option_add("*TCombobox*Listbox.background",       FIG_PANEL,   "widgetDefault")
        self.option_add("*TCombobox*Listbox.foreground",       FIG_TEXT,    "widgetDefault")
        self.option_add("*TCombobox*Listbox.selectBackground", FIG_PANEL_L, "widgetDefault")
        self.option_add("*TCombobox*Listbox.selectForeground", "#ffffff",   "widgetDefault")

        st = ttk.Style(self)
        st.theme_use("clam")

        # ── Global reset — kill all borders/highlights ─────────────
        st.configure(".",
            background=FIG_PANEL,
            foreground=FIG_TEXT,
            font=("Segoe UI", 10),
            borderwidth=0,
            relief="flat",
            bordercolor=FIG_BORDER,
            lightcolor=FIG_PANEL,
            darkcolor=FIG_PANEL,
            highlightthickness=0,
            highlightbackground=FIG_BG,
            highlightcolor=FIG_ACCENT,
            focuscolor="",
        )
        st.configure("TFrame",  background=FIG_PANEL,
                     borderwidth=0, relief="flat",
                     lightcolor=FIG_PANEL, darkcolor=FIG_PANEL)
        st.configure("TLabel",  background=FIG_PANEL, foreground=FIG_TEXT,
                     borderwidth=0)

        # ── Buttons ────────────────────────────────────────────────
        st.configure("TButton",
            background=FIG_BTN,
            foreground=FIG_TEXT,
            padding=(10, 5),
            relief="flat",
            borderwidth=0,
            focuscolor="",
            lightcolor=FIG_BTN,
            darkcolor=FIG_BTN,
        )
        st.map("TButton",
            background=[("active", FIG_PANEL_L), ("pressed", "#222222")],
            foreground=[("active", "#ffffff"),   ("pressed", "#ffffff")],
            lightcolor=[("active", FIG_PANEL_L)],
            darkcolor= [("active", FIG_PANEL_L)],
        )
        st.configure("Accent.TButton",
            background=FIG_ACCENT,
            foreground="#ffffff",
            padding=(12, 5),
            relief="flat",
            borderwidth=0,
            focuscolor="",
            lightcolor=FIG_ACCENT,
            darkcolor=FIG_ACCENT,
        )
        st.map("Accent.TButton",
            background=[("active", FIG_ACCENT_H), ("pressed", "#2a6dbf")],
            lightcolor=[("active", FIG_ACCENT_H)],
            darkcolor= [("active", FIG_ACCENT_H)],
        )
        st.configure("Ghost.TButton",
            background=FIG_PANEL,
            foreground=FIG_TEXT2,
            padding=(10, 5),
            relief="flat",
            borderwidth=1,
            focuscolor="",
            lightcolor=FIG_BORDER,
            darkcolor=FIG_BORDER,
        )
        st.map("Ghost.TButton",
            background=[("active", FIG_PANEL_L), ("pressed", FIG_PANEL_L)],
            foreground=[("active", FIG_TEXT), ("pressed", FIG_TEXT)],
            lightcolor=[("active", FIG_BORDER)],
            darkcolor=[("active", FIG_BORDER)],
        )

        # ── Treeview — Win11 Explorer dark style ───────────────────
        _TV_BG = FIG_BG          # dark background like Win11 explorer
        _TV_SEL = FIG_ACCENT     # accent-blue row selection
        st.configure("Treeview",
            background=_TV_BG,
            foreground=FIG_TEXT,
            fieldbackground=_TV_BG,
            borderwidth=0,
            relief="flat",
            rowheight=28,
            lightcolor=_TV_BG,
            darkcolor=_TV_BG,
            bordercolor=_TV_BG,
            padding=(2, 0),
        )
        st.configure("Treeview.Heading",
            background=_TV_BG,
            foreground=FIG_TEXT2,
            borderwidth=0,
            relief="flat",
            font=("Segoe UI", 9),
            lightcolor=_TV_BG,
            darkcolor=_TV_BG,
            bordercolor=_TV_BG,
        )
        st.map("Treeview",
            background=[
                ("selected", "focus",   _TV_SEL),
                ("selected", "!focus",  FIG_PANEL_L),
                ("active",              FIG_PANEL_L),
            ],
            foreground=[
                ("selected", "#ffffff"),
            ],
            lightcolor=[("selected", _TV_SEL)],
            darkcolor= [("selected", _TV_SEL)],
        )
        st.map("Treeview.Heading",
            background=[("active", FIG_PANEL_L)],
            relief=[("active", "flat")],
        )
        # Remove focus dashed rectangle and separator lines
        st.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

        # ── Progress bar ───────────────────────────────────────────
        st.configure("TProgressbar",
            background=FIG_ACCENT,
            troughcolor=FIG_INPUT,
            borderwidth=0,
            thickness=4,
            lightcolor=FIG_ACCENT,
            darkcolor=FIG_ACCENT,
        )

        # ── Entry ──────────────────────────────────────────────────
        st.configure("TEntry",
            fieldbackground=FIG_INPUT,
            foreground=FIG_TEXT,
            insertcolor=FIG_TEXT,
            borderwidth=1,
            relief="flat",
            bordercolor=FIG_BORDER,
            lightcolor=FIG_INPUT,
            darkcolor=FIG_INPUT,
        )
        st.map("TEntry",
            fieldbackground=[("focus", FIG_PANEL_L)],
            bordercolor=[("focus", FIG_ACCENT)],
            lightcolor=[("focus", FIG_ACCENT)],
        )

        # ── Spinbox ────────────────────────────────────────────────
        st.configure("TSpinbox",
            fieldbackground=FIG_INPUT,
            foreground=FIG_TEXT,
            insertcolor=FIG_TEXT,
            background=FIG_BTN,
            arrowcolor=FIG_TEXT2,
            borderwidth=1,
            relief="flat",
            bordercolor=FIG_BORDER,
            lightcolor=FIG_INPUT,
            darkcolor=FIG_INPUT,
        )
        st.map("TSpinbox",
            fieldbackground=[("focus", FIG_PANEL_L)],
            bordercolor=[("focus", FIG_ACCENT)],
        )

        # ── Combobox ───────────────────────────────────────────────
        st.configure("TCombobox",
            fieldbackground=FIG_INPUT,
            foreground=FIG_TEXT,
            background=FIG_BTN,
            selectbackground=FIG_SEL,
            arrowcolor=FIG_TEXT2,
            borderwidth=1,
            relief="flat",
            bordercolor=FIG_BORDER,
            lightcolor=FIG_INPUT,
            darkcolor=FIG_INPUT,
        )
        st.map("TCombobox",
            fieldbackground=[("readonly", FIG_INPUT)],
            background=[("active", FIG_PANEL_L)],
            bordercolor=[("focus", FIG_ACCENT), ("readonly", FIG_BORDER)],
            selectbackground=[("readonly", "")],
            selectforeground=[("readonly", FIG_TEXT)],
        )

        # ── Checkbuttons ───────────────────────────────────────────
        st.configure("TCheckbutton",
            background=FIG_PANEL,
            foreground=FIG_TEXT,
            indicatorcolor=FIG_INPUT,
            focuscolor="",
        )
        st.map("TCheckbutton",
            background=[("active", FIG_PANEL)],
            indicatorcolor=[("selected", FIG_ACCENT)],
        )
        st.configure("Dark.TCheckbutton",
            background=FIG_BG,
            foreground=FIG_TEXT,
            indicatorcolor=FIG_INPUT,
            focuscolor="",
        )
        st.map("Dark.TCheckbutton",
            background=[("active", FIG_BG)],
            indicatorcolor=[("selected", FIG_ACCENT)],
        )

        # ── Scrollbar — Win11 Explorer style ──────────────────────
        # Slim (idle): 4 px, no arrows, semi-transparent thumb
        # Wide (hover): 12 px, arrows appear, thumb becomes solid
        _SB_SLIM_W  = 4
        _SB_WIDE_W  = 12
        _SB_THUMB   = "#505050"   # idle thumb
        _SB_THUMB_H = "#787878"   # hover/active thumb
        _SB_TROUGH  = FIG_BG      # slim trough — blends into bg
        _SB_TROUGH_W = FIG_PANEL_L  # wide trough — slightly visible

        # --- Slim layouts (no arrows) --------------------------------
        for _orient, _sticky in [("Vertical", "ns"), ("Horizontal", "ew")]:
            st.layout(f"Win11Slim.{_orient}.TScrollbar", [
                (f"{_orient}.Scrollbar.trough", {
                    "sticky": _sticky,
                    "children": [
                        (f"{_orient}.Scrollbar.thumb", {
                            "expand": "1", "sticky": "nswe",
                        }),
                    ],
                }),
            ])
            st.configure(f"Win11Slim.{_orient}.TScrollbar",
                background=_SB_THUMB,
                troughcolor=_SB_TROUGH,
                bordercolor=_SB_TROUGH,
                lightcolor=_SB_TROUGH,
                darkcolor=_SB_TROUGH,
                gripcount=0, relief="flat", borderwidth=0, width=_SB_SLIM_W,
            )
            st.map(f"Win11Slim.{_orient}.TScrollbar",
                background=[("active", _SB_THUMB_H), ("pressed", FIG_ACCENT)],
            )

        # --- Wide layouts (with up/down arrows) ----------------------
        st.layout("Win11Wide.Vertical.TScrollbar", [
            ("Vertical.Scrollbar.trough", {
                "sticky": "ns",
                "children": [
                    ("Vertical.Scrollbar.uparrow",   {"side": "top",    "sticky": ""}),
                    ("Vertical.Scrollbar.thumb",      {"expand": "1",    "sticky": "nswe"}),
                    ("Vertical.Scrollbar.downarrow",  {"side": "bottom", "sticky": ""}),
                ],
            }),
        ])
        st.configure("Win11Wide.Vertical.TScrollbar",
            background=_SB_THUMB_H,
            troughcolor=_SB_TROUGH_W,
            bordercolor=_SB_TROUGH_W,
            lightcolor=_SB_TROUGH_W,
            darkcolor=_SB_TROUGH_W,
            arrowcolor=FIG_TEXT2,
            arrowsize=11,
            gripcount=0, relief="flat", borderwidth=0, width=_SB_WIDE_W,
        )
        st.map("Win11Wide.Vertical.TScrollbar",
            background=[("active", FIG_ACCENT), ("pressed", FIG_ACCENT_H)],
            arrowcolor=[("active", FIG_TEXT)],
        )

        st.layout("Win11Wide.Horizontal.TScrollbar", [
            ("Horizontal.Scrollbar.trough", {
                "sticky": "ew",
                "children": [
                    ("Horizontal.Scrollbar.leftarrow",  {"side": "left",  "sticky": ""}),
                    ("Horizontal.Scrollbar.thumb",       {"expand": "1",   "sticky": "nswe"}),
                    ("Horizontal.Scrollbar.rightarrow",  {"side": "right", "sticky": ""}),
                ],
            }),
        ])
        st.configure("Win11Wide.Horizontal.TScrollbar",
            background=_SB_THUMB_H,
            troughcolor=_SB_TROUGH_W,
            bordercolor=_SB_TROUGH_W,
            lightcolor=_SB_TROUGH_W,
            darkcolor=_SB_TROUGH_W,
            arrowcolor=FIG_TEXT2,
            arrowsize=11,
            gripcount=0, relief="flat", borderwidth=0, width=_SB_WIDE_W,
        )
        st.map("Win11Wide.Horizontal.TScrollbar",
            background=[("active", FIG_ACCENT), ("pressed", FIG_ACCENT_H)],
            arrowcolor=[("active", FIG_TEXT)],
        )

        # Keep legacy Vertical/Horizontal.TScrollbar as slim aliases
        for _orient, _sticky in [("Vertical", "ns"), ("Horizontal", "ew")]:
            st.layout(f"{_orient}.TScrollbar", [
                (f"{_orient}.Scrollbar.trough", {
                    "sticky": _sticky,
                    "children": [
                        (f"{_orient}.Scrollbar.thumb", {
                            "expand": "1", "sticky": "nswe",
                        }),
                    ],
                }),
            ])
            st.configure(f"{_orient}.TScrollbar",
                background=_SB_THUMB,
                troughcolor=_SB_TROUGH,
                bordercolor=_SB_TROUGH,
                lightcolor=_SB_TROUGH,
                darkcolor=_SB_TROUGH,
                gripcount=0, relief="flat", borderwidth=0, width=_SB_SLIM_W,
            )

        # ── Apply Windows dark title bar (also after window is mapped) ──
        self._schedule_dark_titlebar()

    def _schedule_dark_titlebar(self, window: tk.Tk | tk.Toplevel | None = None) -> None:
        """Re-apply DWM title bar when HWND is ready (Map / idle / short delay)."""
        target = window or self
        self._apply_dark_titlebar(target)
        target.after(50, lambda w=target: self._apply_dark_titlebar(w))

    def _apply_dark_titlebar(self, window: tk.Tk | tk.Toplevel | None = None) -> None:
        """Force Windows dark-mode title bar via DWM API."""
        if sys.platform != "win32":
            return
        target = window or self
        dark = self._resolve_dark(self._theme_choice)
        try:
            import ctypes

            user32 = ctypes.windll.user32
            dwmapi = ctypes.windll.dwmapi
            target.update_idletasks()
            hwnd = user32.GetParent(target.winfo_id())
            if not hwnd:
                hwnd = target.winfo_id()
            val = ctypes.c_int(1 if dark else 0)
            for attr in (20, 19):  # Win10 20H1+ / older preview builds
                dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(val), ctypes.sizeof(val),
                )
            # Title bar / border tint (BGR) — matches current app palette.
            if dark:
                caption_bgr = 0x00141414
                text_bgr = 0x00f0f0f0
            else:
                caption_bgr = 0x00f0f0f0
                text_bgr = 0x00141414
            caption = ctypes.c_int(caption_bgr)
            text = ctypes.c_int(text_bgr)
            for attr, value in ((34, caption), (35, caption), (36, text)):
                dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value), ctypes.sizeof(value),
                )
        except Exception:
            pass

    def _style_all_menus(self, menu: tk.Menu | None = None) -> None:
        """Apply current palette to menubar and every cascade submenu."""
        root_menu = menu
        if root_menu is None:
            try:
                menu_name = self.cget("menu")
                if not menu_name:
                    return
                root_menu = self.nametowidget(menu_name)
            except (tk.TclError, KeyError):
                return
        if not isinstance(root_menu, tk.Menu):
            return

        opts: dict[str, object] = dict(
            bg=FIG_PANEL,
            fg=FIG_TEXT,
            activebackground=FIG_PANEL_L,
            activeforeground="#ffffff",
            disabledforeground=FIG_TEXT2,
            selectcolor=FIG_ACCENT,
            relief="flat",
            bd=0,
            borderwidth=0,
            activeborderwidth=0,
        )
        try:
            root_menu.configure(**opts)  # type: ignore[arg-type]
        except tk.TclError:
            pass
        try:
            last = root_menu.index("end")
        except tk.TclError:
            return
        if last is None:
            return
        for i in range(last + 1):
            try:
                if root_menu.type(i) != "cascade":
                    continue
                sub = root_menu.nametowidget(root_menu.entrycget(i, "menu"))
                if isinstance(sub, tk.Menu):
                    self._style_all_menus(sub)
            except tk.TclError:
                continue

    def _close_custom_menus(self, from_level: int = 0) -> None:
        """Close custom dropdown popups from the requested nesting level."""
        popups = getattr(self, "_menu_popups", [])
        for popup in popups[from_level:]:
            try:
                popup.destroy()
            except tk.TclError:
                pass
        self._menu_popups = popups[:from_level]

    def _widget_inside_menu_popup(self, widget: tk.Widget) -> bool:
        while widget is not None:
            if widget in getattr(self, "_menu_popups", []):
                return True
            if bool(getattr(widget, "_autoraw_menubar_item", False)):
                return True
            widget = widget.master  # type: ignore[assignment]
        return False

    def _show_custom_menu(
        self,
        anchor: tk.Widget,
        items: list[dict[str, object]],
        *,
        x: int | None = None,
        y: int | None = None,
        level: int = 0,
    ) -> tk.Toplevel:
        """Cursor-like dark dropdown without native Windows white borders."""
        self._close_custom_menus(level)

        popup = tk.Toplevel(self)
        popup.overrideredirect(True)
        popup.configure(bg=FIG_BORDER)
        popup.transient(self)

        body = tk.Frame(popup, bg=FIG_PANEL, bd=0, highlightthickness=0)
        body.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        row_width = 262

        def set_row_active(row: tk.Frame, active: bool) -> None:
            bg = FIG_PANEL_L if active else FIG_PANEL
            row.configure(bg=bg)
            for child in row.winfo_children():
                if isinstance(child, tk.Widget):
                    child.configure(bg=bg)

        for item in items:
            if item.get("separator"):
                tk.Frame(body, bg=FIG_BORDER, height=1, bd=0).pack(
                    fill=tk.X, padx=0, pady=4
                )
                continue

            label = str(item.get("label", ""))
            shortcut = str(item.get("shortcut", ""))
            children = item.get("children")
            command = item.get("command")

            row = tk.Frame(body, bg=FIG_PANEL, height=26, width=row_width,
                           bd=0, highlightthickness=0, cursor="hand2")
            row.pack(fill=tk.X, padx=4, pady=0)
            row.pack_propagate(False)

            tk.Label(row, text=label, bg=FIG_PANEL, fg=FIG_TEXT,
                     font=("Segoe UI", 9), anchor=tk.W, padx=10).pack(
                side=tk.LEFT, fill=tk.BOTH, expand=True
            )
            if children:
                tk.Label(row, text="›", bg=FIG_PANEL, fg=FIG_TEXT2,
                         font=("Segoe UI", 12), padx=10).pack(side=tk.RIGHT)
            elif shortcut:
                tk.Label(row, text=shortcut, bg=FIG_PANEL, fg=FIG_TEXT2,
                         font=("Segoe UI", 8), padx=10).pack(side=tk.RIGHT)

            def on_enter(_event: tk.Event, row=row, children=children) -> None:
                set_row_active(row, True)
                if isinstance(children, list):
                    self._show_custom_menu(
                        row,
                        children,  # type: ignore[arg-type]
                        x=row.winfo_rootx() + row.winfo_width() - 2,
                        y=row.winfo_rooty() - 1,
                        level=level + 1,
                    )
                else:
                    self._close_custom_menus(level + 1)

            def on_leave(_event: tk.Event, row=row, children=children) -> None:
                if not children:
                    set_row_active(row, False)

            def on_click(_event: tk.Event, command=command) -> str:
                if callable(command):
                    self._close_custom_menus()
                    command()
                return "break"

            for widget in (row, *row.winfo_children()):
                widget.bind("<Enter>", on_enter)
                widget.bind("<Leave>", on_leave)
                widget.bind("<Button-1>", on_click)

        if x is None:
            x = anchor.winfo_rootx()
        if y is None:
            y = anchor.winfo_rooty() + anchor.winfo_height()

        popup.geometry(f"+{x}+{y}")
        popup.update_idletasks()
        popup.lift(self)
        try:
            popup.attributes("-topmost", True)
            popup.after(120, lambda: popup.attributes("-topmost", False))
        except tk.TclError:
            pass
        try:
            popup.focus_force()
        except tk.TclError:
            pass
        popup.bind("<Escape>", lambda _e: self._close_custom_menus())

        self._menu_popups.append(popup)
        return popup

    def _make_menubar_item(self, parent: tk.Widget, text: str, items: list[dict[str, object]]) -> tk.Label:
        """Dark custom menubar item; native Windows menubar cannot be recolored."""
        item = tk.Label(
            parent,
            text=text,
            bg=FIG_BG,
            fg=FIG_TEXT,
            padx=10,
            pady=3,
            font=("Segoe UI", 9),
            cursor="hand2",
        )
        item._autoraw_menubar_item = True  # type: ignore[attr-defined]

        def set_active(active: bool) -> None:
            item.configure(bg=FIG_PANEL_L if active else FIG_BG,
                           fg="#ffffff" if active else FIG_TEXT)

        def show_menu(_event: tk.Event | None = None) -> str:
            set_active(True)
            self._show_custom_menu(item, items)
            self.after(120, lambda: set_active(False))
            return "break"

        item.bind("<Enter>", lambda _e: set_active(True))
        item.bind("<Leave>", lambda _e: set_active(False))
        item.bind("<Button-1>", show_menu)
        item.bind("<Return>", show_menu)
        item.bind("<space>", show_menu)
        item.configure(takefocus=1)
        item.pack(side=tk.LEFT, padx=(2, 0))
        return item

    def _win11_sb(
        self,
        parent: tk.Widget,
        orient: str = tk.VERTICAL,
        **kw: object,
    ) -> ttk.Scrollbar:
        """Win11-style scrollbar: 4 px idle, expands to 12 px with arrows on hover."""
        o = "Vertical" if orient == tk.VERTICAL else "Horizontal"
        slim = f"Win11Slim.{o}.TScrollbar"
        wide = f"Win11Wide.{o}.TScrollbar"

        sb = ttk.Scrollbar(parent, orient=orient, style=slim, **kw)  # type: ignore[arg-type]
        sb.bind("<Enter>", lambda _e: sb.configure(style=wide))
        sb.bind("<Leave>", lambda _e: sb.configure(style=slim))
        return sb

    def _section_label(self, parent: tk.Widget, text: str) -> None:
        bg = str(parent.cget("bg"))
        row = tk.Frame(parent, bg=bg)
        row.pack(fill=tk.X, padx=10, pady=(10, 6))
        # accent pip
        tk.Frame(row, bg=FIG_ACCENT, width=3, height=14).pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(row, text=text.upper(), bg=bg,
                 fg=FIG_TEXT2, font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, anchor=tk.W)

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

    def _draw_modern_switch(self, canvas: tk.Canvas, enabled: bool, *, hover: bool = False) -> None:
        """Компактный переключатель в стиле Win11 / iOS."""
        canvas.delete("all")
        track_off = "#404040" if not hover else "#4a4a4a"
        track_on = FIG_ACCENT_H if hover else FIG_ACCENT
        track = track_on if enabled else track_off
        outline = track_on if enabled else FIG_BORDER
        self._rounded_rect(canvas, 1, 2, 45, 22, 11, fill=track, outline=outline, width=1)
        knob_x = 33 if enabled else 13
        canvas.create_oval(knob_x - 8, 4, knob_x + 8, 20, fill="#ffffff", outline="", tags="knob")
        if enabled:
            canvas.create_oval(knob_x - 7, 5, knob_x + 7, 19, fill="#ffffff", outline=FIG_ACCENT, width=1)

    def _make_switch(
        self,
        parent: tk.Widget,
        variable: tk.BooleanVar,
        command,
        *,
        modern: bool = False,
    ) -> tk.Canvas:
        w, h = (46, 24) if modern else (92, 26)
        canvas = tk.Canvas(parent, width=w, height=h, bg=FIG_PANEL, highlightthickness=0, bd=0, cursor="hand2")
        canvas._hover = False  # type: ignore[attr-defined]

        def redraw() -> None:
            if modern:
                self._draw_modern_switch(canvas, bool(variable.get()), hover=bool(canvas._hover))
            else:
                self._draw_switch(canvas, bool(variable.get()))

        redraw()

        def toggle(_event: tk.Event | None = None) -> str:
            variable.set(not bool(variable.get()))
            redraw()
            command()
            return "break"

        canvas.bind("<Button-1>", toggle)
        canvas.bind("<Return>", toggle)
        canvas.bind("<space>", toggle)
        canvas.bind("<Enter>", lambda _e: (setattr(canvas, "_hover", True), redraw()))
        canvas.bind("<Leave>", lambda _e: (setattr(canvas, "_hover", False), redraw()))
        canvas.configure(takefocus=1)
        return canvas

    def _build_menubar(self) -> None:
        """Dark custom menubar — native Windows menubar ignores Tk colors."""
        try:
            self.config(menu="")
        except tk.TclError:
            pass

        menubar = tk.Frame(self, bg=FIG_BG, height=25, bd=0, highlightthickness=0)
        menubar.pack(fill=tk.X)
        menubar.pack_propagate(False)
        inner = tk.Frame(menubar, bg=FIG_BG, bd=0, highlightthickness=0)
        inner.pack(side=tk.LEFT, fill=tk.Y, padx=(4, 0))
        tk.Frame(menubar, bg=FIG_BORDER, height=1, bd=0).pack(side=tk.BOTTOM, fill=tk.X)

        # ── Вид ─────────────────────────────────────────────────────
        theme_items: list[dict[str, object]] = []
        for _lbl, _mode in (
            ("☀  Светлая", "light"),
            ("🌙  Тёмная",  "dark"),
            ("⚙  Как в системе", "system"),
        ):
            _is_cur = (self._theme_choice == _mode)
            theme_items.append(
                dict(
                    label=("✓  " if _is_cur else "    ") + _lbl,
                    command=lambda m=_mode: self._change_theme(m),
                )
            )
        view_items: list[dict[str, object]] = [
            dict(label="Тема", children=theme_items),
        ]
        self._make_menubar_item(inner, "Вид", view_items)

        # ── Настройки ────────────────────────────────────────────────
        settings_items: list[dict[str, object]] = [
            dict(label="Уведомления от Zona…", command=self.show_zona_settings),
        ]
        self._make_menubar_item(inner, "Настройки", settings_items)

        # ── О программе ─────────────────────────────────────────────
        about_items: list[dict[str, object]] = [
            dict(label="Управление и горячие клавиши", shortcut="F1", command=self.show_hotkeys),
            dict(separator=True),
            dict(label="Проверить обновление…", command=self.check_updates),
            dict(separator=True),
            dict(label="Инструкция", command=self.show_manual),
            dict(label="Что изменилось", command=self.show_changelog),
            dict(label="О программе", command=self.show_about),
        ]
        self._make_menubar_item(inner, "О программе", about_items)

    def _build_ui(self) -> None:
        self._setup_theme()
        self._build_menubar()

        # F1 hotkey — show hotkeys dialog
        self.bind("<F1>", lambda _e: self.show_hotkeys())

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

        self._export_actions = tk.Frame(bar_inner, bg=FIG_PANEL)
        self._export_actions.pack(side=tk.LEFT, padx=(2, 12))
        self.export_action_btn = ttk.Button(
            self._export_actions,
            text="Экспорт",
            style="Accent.TButton",
            width=11,
            command=self._on_export_action,
        )
        self.export_action_btn.pack(side=tk.LEFT)
        self.export_cancel_btn = ttk.Button(
            self._export_actions,
            text="Отмена",
            style="Ghost.TButton",
            width=9,
            command=self._cancel_export,
        )

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

        # ── System status bar (bottom) ───────────────────────────────
        tk.Frame(self, bg=FIG_BORDER, height=1).pack(side=tk.BOTTOM, fill=tk.X)
        sysbar = tk.Frame(self, bg=FIG_PANEL, height=24)
        sysbar.pack(side=tk.BOTTOM, fill=tk.X)
        sysbar.pack_propagate(False)
        self._build_sysbar(sysbar)

        # ── Main body ────────────────────────────────────────────────
        body = tk.Frame(self, bg=FIG_BG)
        body.pack(fill=tk.BOTH, expand=True)

        # ── Left: folder tree ─────────────────────────────────────
        left = tk.Frame(body, bg=FIG_BG, width=240)
        left.pack(side=tk.LEFT, fill=tk.Y)
        left.pack_propagate(False)
        self._section_label(left, "Папки")

        # Container: tree + thin scrollbar side-by-side
        _tree_frame = tk.Frame(left, bg=FIG_BG)
        _tree_frame.pack(fill=tk.BOTH, expand=True, padx=(6, 2), pady=(0, 6))

        self.folder_tree = ttk.Treeview(_tree_frame, columns=("check", "count"),
                                         show="tree headings", height=30)
        self.folder_tree.heading("#0", text="Имя")
        self.folder_tree.heading("check", text="✓")
        self.folder_tree.heading("count", text="")
        self.folder_tree.column("#0", width=155, stretch=True)
        self.folder_tree.column("check", width=26, anchor=tk.CENTER, stretch=False)
        self.folder_tree.column("count", width=28, anchor=tk.CENTER, stretch=False)

        _folder_sb = self._win11_sb(
            _tree_frame, orient=tk.VERTICAL,
            command=self.folder_tree.yview,
        )
        self.folder_tree.configure(yscrollcommand=_folder_sb.set)
        _folder_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.folder_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.folder_tree.bind("<<TreeviewSelect>>", self.on_folder_select)
        self.folder_tree.bind("<Button-1>", self.on_folder_click)

        # left separator
        tk.Frame(body, bg=FIG_BORDER, width=1).pack(side=tk.LEFT, fill=tk.Y)

        # ── Right: thumbnails + info — pack RIGHT before center ───
        # (RIGHT items must be packed before the LEFT+expand center)
        right = tk.Frame(body, bg=FIG_BG, width=RIGHT_PANEL_W)
        right.pack(side=tk.RIGHT, fill=tk.Y)
        right.pack_propagate(False)

        # right separator
        tk.Frame(body, bg=FIG_BORDER, width=1).pack(side=tk.RIGHT, fill=tk.Y)

        self.info_var = tk.StringVar(value="Папка не загружена")

        # ── Etalon reference widget ──────────────────────────────────────
        _ref_w = RIGHT_PANEL_W - 16          # 8 px padding each side
        _ref_h = _ref_w * 3 // 4             # 4:3 to match output aspect
        self._ref_w = _ref_w
        self._ref_h = _ref_h
        self._ref_photo: ImageTk.PhotoImage | None = None

        # Header row for etalon — icon + label, clean flat Win11 style
        _ref_hdr = tk.Frame(right, bg=FIG_BG)
        _ref_hdr.pack(fill=tk.X, padx=8, pady=(8, 4))
        tk.Frame(_ref_hdr, bg=FIG_ACCENT, width=3, height=14).pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(_ref_hdr, text="ЭТАЛОН", bg=FIG_BG, fg=FIG_TEXT2,
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT)

        # Canvas — no outer border frame, border is drawn by the canvas bg contrast
        self.ref_canvas = tk.Canvas(
            right, width=_ref_w, height=_ref_h,
            bg=FIG_PANEL, highlightthickness=1,
            highlightbackground=FIG_BORDER, cursor="hand2",
        )
        self.ref_canvas.pack(padx=8, pady=(0, 6))
        self.ref_canvas.create_text(
            _ref_w // 2, _ref_h // 2 - 10,
            text="Эталон не загружен", fill=FIG_TEXT2,
            font=("Segoe UI", 10),
        )
        self.ref_canvas.create_text(
            _ref_w // 2, _ref_h // 2 + 10,
            text="Нажмите для выбора", fill=FIG_TEXT2,
            font=("Segoe UI", 8),
        )
        self.ref_canvas.bind("<Button-1>", lambda _e: self._pick_etalon())

        self._hsep(right)

        thumb_wrap = tk.Frame(right, bg=FIG_BG)
        thumb_wrap.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.thumb_canvas = tk.Canvas(thumb_wrap, bg=FIG_BG, highlightthickness=0, bd=0)
        thumb_scroll = self._win11_sb(
            thumb_wrap, orient=tk.VERTICAL, command=self.thumb_canvas.yview,
        )
        self.thumb_canvas.configure(yscrollcommand=thumb_scroll.set)
        thumb_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.thumb_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.thumbs = tk.Frame(self.thumb_canvas, bg=FIG_BG)
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

        # row 1 — position
        row1 = tk.Frame(ctrl_wrap, bg=FIG_PANEL)
        row1.pack(fill=tk.X)
        self.offset_x = self._slider(row1, "X",       -450,  450,     self.update_current, "{:.0f}")
        self.offset_y = self._slider(row1, "Y",       -350,  350,     self.update_current, "{:.0f}")
        # row 2 — transform
        row2 = tk.Frame(ctrl_wrap, bg=FIG_PANEL)
        row2.pack(fill=tk.X, pady=(6, 0))
        self.zoom     = self._slider(row2, "Масштаб",  0.5,  ZOOM_MAX, self.update_current, "{:.2f}")
        self.rotation = self._slider(row2, "Поворот", -20,   20,      self.update_current, "{:.1f}°")
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

        # mini accent pip + label
        pip_row = tk.Frame(cc_head, bg=FIG_PANEL)
        pip_row.pack(side=tk.LEFT)
        tk.Frame(pip_row, bg=FIG_ACCENT, width=3, height=12).pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(pip_row, text="ЦВЕТОКОР", bg=FIG_PANEL, fg=FIG_TEXT2,
                 font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT)

        # switch + action buttons on the right
        cc_right = tk.Frame(cc_head, bg=FIG_PANEL)
        cc_right.pack(side=tk.RIGHT)
        self.colorcor_switch = self._make_switch(
            cc_right, self.use_colorcor_var, self.on_colorcor_toggle, modern=True
        )
        self.colorcor_switch.pack(side=tk.LEFT, padx=(0, 14))
        ttk.Button(cc_right, text="Сохранить",
                   command=self.save_color_settings).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(cc_right, text="Сбросить",
                   command=self.reset_color_settings).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Button(cc_right, text="Применить к папке",
                   command=self.apply_look_to_folder).pack(side=tk.LEFT)

        # ── compact sliders (2 × 2) ───────────────────────────────────
        cc_fields = tk.Frame(cc_wrap, bg=FIG_PANEL)
        cc_fields.pack(fill=tk.X, pady=(4, 0))

        cc_row1 = tk.Frame(cc_fields, bg=FIG_PANEL)
        cc_row1.pack(fill=tk.X)
        cc_row2 = tk.Frame(cc_fields, bg=FIG_PANEL)
        cc_row2.pack(fill=tk.X, pady=(4, 0))

        self._slider(cc_row1, "Контраст",    -100,  100,   self.update_current,
                     "{:.0f}",  compact=True, existing_var=self.contrast_var, editable=True)
        self._slider(cc_row1, "Тени",        -100,  100,   self.update_current,
                     "{:.0f}",  compact=True, existing_var=self.shadows_var, editable=True)
        self._slider(cc_row2, "Температура", 2000, 10000,  self.update_current,
                     "{:.0f}K", compact=True, existing_var=self.temperature_var, editable=True)
        self._slider(cc_row2, "Оттенок",     -100,  100,   self.update_current,
                     "{:.0f}",  compact=True, existing_var=self.tint_var, editable=True)

        self.after_idle(self._sync_export_ui)

    def _on_export_action(self) -> None:
        if self._export_running:
            self._toggle_export_pause()
        else:
            self.export_checked()

    def _sync_export_ui(self) -> None:
        if not hasattr(self, "export_action_btn"):
            return
        if not self._export_running:
            self.export_action_btn.config(text="Экспорт", style="Accent.TButton")
            self.export_cancel_btn.pack_forget()
            return
        label = "Продолжить" if self._export_job.paused else "Пауза"
        self.export_action_btn.config(text=label, style="Accent.TButton")
        if not self.export_cancel_btn.winfo_ismapped():
            self.export_cancel_btn.pack(side=tk.LEFT, padx=(6, 0))

    def _toggle_export_pause(self) -> None:
        if not self._export_running:
            return
        if self._export_job.paused:
            self._export_job.resume()
            self.set_progress(self.progress_var.get(), "Экспорт продолжен")
        else:
            self._export_job.pause()
            self.set_progress(self.progress_var.get(), "Экспорт на паузе")
        self._sync_export_ui()

    def _cancel_export(self) -> None:
        if not self._export_running:
            return
        self._export_job.cancel()
        self.set_progress(self.progress_var.get(), "Отмена экспорта…")

    def _set_export_controls(self, running: bool) -> None:
        self._export_running = running
        self._sync_export_ui()

    def _slider(
        self,
        parent: tk.Frame,
        label: str,
        start: float,
        end: float,
        command,
        fmt: str = "{:.0f}",
        compact: bool = False,
        existing_var: tk.Variable | None = None,
        editable: bool = False,
    ) -> tk.DoubleVar:
        """Canvas slider — thin track, accent fill, round thumb.
        compact=True → smaller (used for colour-correction row).
        existing_var → reuse an existing IntVar/DoubleVar instead of creating a new one.
        editable=True → поле ввода числа справа от подписи.
        """
        TRACK_H  = 2 if compact else 3
        THUMB_R  = 5 if compact else 7
        CANVAS_H = 14 if compact else 20
        FONT_SZ  = 8 if compact else 9
        BG = FIG_PANEL
        fmt_suffix = "K" if fmt.rstrip().endswith("K") else ""

        col = tk.Frame(parent, bg=BG)
        col.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 12 if compact else 16))

        hdr = tk.Frame(col, bg=BG)
        hdr.pack(fill=tk.X, pady=(0, 1))
        tk.Label(hdr, text=label, bg=BG, fg=FIG_TEXT2,
                 font=("Segoe UI", FONT_SZ)).pack(side=tk.LEFT)
        val_str = tk.StringVar()
        var: tk.Variable = existing_var if existing_var is not None else tk.DoubleVar(value=0.0)
        syncing: dict[str, bool] = {"entry": False}

        def format_value() -> str:
            return fmt.format(var.get())

        val_str.set(format_value())

        if editable:
            value_entry = tk.Entry(
                hdr,
                textvariable=val_str,
                width=7 if fmt_suffix else 5,
                justify="right",
                bg=FIG_INPUT,
                fg=FIG_ACCENT,
                insertbackground=FIG_ACCENT,
                relief="flat",
                highlightthickness=1,
                highlightbackground=FIG_BORDER,
                highlightcolor=FIG_ACCENT,
                font=("Segoe UI", FONT_SZ, "bold"),
            )
            value_entry.pack(side=tk.RIGHT, ipady=1)

            def parse_entry(text: str) -> float | None:
                raw = text.strip().replace(",", ".")
                if not raw:
                    return None
                if fmt_suffix and raw.upper().endswith(fmt_suffix.upper()):
                    raw = raw[: -len(fmt_suffix)].strip()
                try:
                    return float(raw)
                except ValueError:
                    return None

            def commit_entry(_event: tk.Event | None = None) -> None:
                if syncing["entry"]:
                    return
                parsed = parse_entry(val_str.get())
                if parsed is None:
                    val_str.set(format_value())
                    return
                clamped = max(start, min(end, parsed))
                if isinstance(var, tk.IntVar):
                    var.set(int(round(clamped)))
                else:
                    var.set(clamped)
                val_str.set(format_value())
                command()

            value_entry.bind("<Return>", commit_entry)
            value_entry.bind("<FocusOut>", commit_entry)
            value_entry.bind("<FocusIn>", lambda _e: value_entry.after_idle(lambda: value_entry.select_range(0, tk.END)))
        else:
            tk.Label(hdr, textvariable=val_str, bg=BG, fg=FIG_ACCENT,
                     font=("Segoe UI", FONT_SZ, "bold"),
                     width=6 if compact else 7, anchor="e").pack(side=tk.RIGHT)

        c = tk.Canvas(col, height=CANVAS_H, bg=BG,
                      highlightthickness=0, bd=0, cursor="hand2")
        c.pack(fill=tk.X, pady=(1, 3 if compact else 4))

        resolution = 0.01 if abs(end - start) <= 10 else 1.0

        def _redraw(*_: object) -> None:
            w = c.winfo_width()
            if w < 6:
                return
            c.delete("all")
            cy  = CANVAS_H // 2
            r   = THUMB_R
            c.create_rectangle(r, cy - TRACK_H // 2,
                                w - r, cy + TRACK_H // 2 + 1,
                                fill=SL_TRACK, outline="", tags="track")
            ratio = max(0.0, min(1.0, (var.get() - start) / (end - start)))
            tx = r + ratio * (w - 2 * r)
            if tx > r + 1:
                c.create_rectangle(r, cy - TRACK_H // 2,
                                   tx, cy + TRACK_H // 2 + 1,
                                   fill=SL_ACTIVE, outline="", tags="active")
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
            step  = resolution * (10 if event.state & 0x1 else 1)
            delta = step if event.delta > 0 else -step
            var.set(max(start, min(end, var.get() + delta)))
            command()

        def _on_var_change(*_: object) -> None:
            syncing["entry"] = True
            val_str.set(format_value())
            syncing["entry"] = False
            c.after_idle(_redraw)

        c.bind("<Configure>",     _redraw)
        c.bind("<ButtonPress-1>", lambda e: _set(e.x))
        c.bind("<B1-Motion>",     lambda e: _set(e.x))
        c.bind("<MouseWheel>",    _on_scroll)
        var.trace_add("write", _on_var_change)

        return var  # type: ignore[return-value]

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
        self._prepare_dialog_window(win)
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
        loaded: list[tuple[Path, Image.Image]] = []
        start_time = time.monotonic()

        for index, path in enumerate(paths, start=1):
            elapsed = time.monotonic() - start_time
            eta = (elapsed / (index - 1) * (total - index + 1)) if index > 1 else 0.0
            self.worker_events.put(("progress", token, index - 1, total, f"Открываю {path.name}", eta))
            try:
                img = open_preview(path, max_side=WORKING_MAX_SIDE)
                loaded.append((path, img))
            except Exception as exc:
                self.worker_events.put(("warning", token, f"Не удалось открыть {path.name}:\n{exc}"))

        self.worker_events.put(("progress", token, total, total, "Определяю порядок кадров по search-эталонам", 0.0))
        frames = [
            FrameState(
                path=path,
                frame=frame,
                image=img,
                crop_box=crop_box_for_assigned_frame(path, img, aspect, frame),
                match_score=score,
            )
            for path, img, frame, score in assign_frames_by_search(loaded)
        ]

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
        loaded: list[tuple[Path, Image.Image]] = []
        for path in direct_image_files(folder)[:8]:
            try:
                img = open_preview(path, max_side=WORKING_MAX_SIDE)
                loaded.append((path, img))
            except Exception as exc:
                messagebox.showwarning(APP_NAME, f"Не удалось открыть {path.name}:\n{exc}")

        frames = [
            FrameState(
                path=path,
                frame=frame,
                image=img,
                crop_box=crop_box_for_assigned_frame(path, img, aspect, frame),
                match_score=score,
            )
            for path, img, frame, score in assign_frames_by_search(loaded)
        ]
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

    def _refresh_single_thumb(self, index: int) -> None:
        """Re-render one thumbnail in-place without rebuilding the whole panel."""
        frames = self.current_frames()
        if not frames or not (0 <= index < len(frames)):
            return
        if not hasattr(self, "thumb_btns") or index >= len(self.thumb_btns):
            return
        btn = self.thumb_btns[index]
        if not btn.winfo_exists():
            return

        state = frames[index]
        state.thumb_cache = None  # force re-render
        thumb = render_frame(state, THUMB_SIZE)
        if self.use_colorcor_var.get():
            thumb = apply_standard_look(
                thumb,
                contrast=state.contrast,
                shadows=state.shadows,
                temperature=state.temperature,
                tint=state.tint,
            )
        state.thumb_cache = thumb
        photo = ImageTk.PhotoImage(thumb)
        btn.configure(image=photo)
        # Keep strong reference so GC doesn't collect it
        btn.image = photo  # type: ignore[attr-defined]
        if hasattr(self, "thumb_photos") and index < len(self.thumb_photos):
            self.thumb_photos[index] = photo

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

            badge_row = tk.Frame(card, bg=FIG_SURFACE)
            badge_row.pack(fill=tk.X, pady=(0, 2))
            score_text = ""
            if state.match_score is not None:
                confidence = max(0, min(99, int(round((1.0 - state.match_score) * 100))))
                score_text = f" · {confidence}%"
            tk.Label(badge_row, text=f"  {state.frame}{score_text}", bg=FIG_ACCENT if is_selected else FIG_BTN,
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
        prev_index = self.selected_index
        if save_previous:
            self._save_controls_to_current()
            # Update the thumbnail we're leaving so it reflects any edits
            if prev_index != index:
                self.after_idle(lambda i=prev_index: self._refresh_single_thumb(i))
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
        match_text = ""
        if state.match_score is not None:
            confidence = max(0, min(99, int(round((1.0 - state.match_score) * 100))))
            match_text = f" · авто {confidence}%"
        self.info_var.set(
            f"📁  {folder_text}\n"
            f"🖼  {state.frame}{match_text} — {state.path.name}\n"
            f"⌨  Стрелки / мышь / колесо"
        )
        self.preview.focus_set()
        self._highlight_selected_thumb()
        self.render_preview()
        self._auto_load_etalon()

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
            self._draw_modern_switch(
                self.colorcor_switch,
                bool(self.use_colorcor_var.get()),
                hover=bool(getattr(self.colorcor_switch, "_hover", False)),
            )
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

    # ── hotkeys dialog ───────────────────────────────────────────────
    # ── image extensions for reference scanning ───────────────────────
    _IMG_EXTS: frozenset[str] = frozenset(
        {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"}
    )

    def _auto_load_etalon(self) -> None:
        """Auto-select the matching reference image for the current frame.

        Looks for:  <root_folder>/reference/<selected_folder_name>/<images sorted>
        and picks the image matching the assigned frame number (1.jpg..8.jpg).
        Falls back to the manually saved etalon path if no reference folder is found.
        """
        if not self.root_folder or not self.selected_folder:
            self._display_etalon(self._etalon_path)
            return
        state = self.current()
        if state is None:
            self._display_etalon(self._etalon_path)
            return

        # Candidate locations for the reference root folder
        ref_root: Path | None = None
        for candidate in (
            self.root_folder / "reference",
            self.root_folder.parent / "reference",
        ):
            if candidate.is_dir():
                ref_root = candidate
                break

        if ref_root is None:
            self._display_etalon(self._etalon_path)
            return

        # Find subfolder matching selected_folder name (case-insensitive)
        target_name = self.selected_folder.name.lower()
        ref_subdir: Path | None = None
        for d in ref_root.iterdir():
            if d.is_dir() and d.name.lower() == target_name:
                ref_subdir = d
                break

        if ref_subdir is None:
            self._display_etalon(self._etalon_path)
            return

        candidates: list[Path] = []
        if state.frame.isdigit():
            n = int(state.frame)
            for stem in (str(n), f"{n:02d}"):
                candidates.extend(ref_subdir / f"{stem}{ext}" for ext in self._IMG_EXTS)

        for candidate in candidates:
            if candidate.is_file():
                self._display_etalon(str(candidate))
                return

        # Fallback for old reference packs where only sorted files exist.
        images = sorted(
            f for f in ref_subdir.iterdir()
            if f.is_file() and f.suffix.lower() in self._IMG_EXTS
        )
        if images:
            idx = min(self.selected_index, len(images) - 1)
            self._display_etalon(str(images[idx]))
        else:
            self._display_etalon(self._etalon_path)

    # ══════════════════════════════════════════════════════════════
    #  System status bar
    # ══════════════════════════════════════════════════════════════

    @staticmethod
    def _sys_color(pct: float) -> str:
        if pct < 40: return "#22c55e"
        if pct < 65: return "#eab308"
        if pct < 80: return "#f97316"
        return "#ef4444"

    @staticmethod
    def _temp_color(deg: float, *, gpu: bool = False) -> str:
        warn  = 75 if gpu else 65
        crit  = 90 if gpu else 80
        if deg < warn:  return "#22c55e"
        if deg < crit:  return "#f97316"
        return "#ef4444"

    @staticmethod
    def _check_net_ms() -> float | None:
        """TCP connect to well-known hosts on port 80; return round-trip ms or None."""
        targets = [
            ("8.8.8.8",      80),   # Google DNS via HTTP port
            ("1.1.1.1",      80),   # Cloudflare
            ("www.google.com", 80),
        ]
        for host, port in targets:
            try:
                t0 = time.perf_counter()
                with socket.create_connection((host, port), timeout=2.0):
                    pass
                return (time.perf_counter() - t0) * 1000
            except OSError:
                continue
        return None

    @staticmethod
    def _net_bars_info(ms: float | None) -> tuple[int, str]:
        if ms is None:  return 0, "#6b7280"
        if ms < 50:     return 5, "#22c55e"
        if ms < 100:    return 4, "#84cc16"
        if ms < 200:    return 3, "#eab308"
        if ms < 500:    return 2, "#f97316"
        return 1, "#ef4444"

    def _build_sysbar(self, parent: tk.Frame) -> None:
        """Populate the system status bar widgets."""
        def _sep() -> None:
            tk.Label(parent, text="│", bg=FIG_PANEL, fg=FIG_BORDER,
                     font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=4)

        # ── User name ──────────────────────────────────────────────
        user_name = _load_config().get("user_name", "Иван")
        self._sysbar_user_var = tk.StringVar(value=f"👤  {user_name}")
        user_lbl = tk.Label(
            parent, textvariable=self._sysbar_user_var,
            bg=FIG_PANEL, fg=FIG_TEXT, font=("Segoe UI", 8),
            cursor="hand2", padx=10,
        )
        user_lbl.pack(side=tk.LEFT)
        user_lbl.bind("<Button-1>", lambda _e: self._change_username())

        _sep()

        # ── Internet signal bars ────────────────────────────────────
        tk.Label(parent, text="🌐", bg=FIG_PANEL, fg=FIG_TEXT2,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(2, 3))
        self._sysbar_net_canvas = tk.Canvas(
            parent, width=29, height=14, bg=FIG_PANEL, highlightthickness=0,
        )
        self._sysbar_net_canvas.pack(side=tk.LEFT, padx=(0, 6))
        self._draw_signal_bars(0, "#6b7280")

        _sep()

        # ── CPU ────────────────────────────────────────────────────
        tk.Label(parent, text="CPU", bg=FIG_PANEL, fg=FIG_TEXT2,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(6, 2))
        self._sysbar_cpu_var = tk.StringVar(value="—")
        self._sysbar_cpu_lbl = tk.Label(
            parent, textvariable=self._sysbar_cpu_var,
            bg=FIG_PANEL, fg=FIG_TEXT2, font=("Segoe UI", 8, "bold"), width=4,
        )
        self._sysbar_cpu_lbl.pack(side=tk.LEFT)
        self._sysbar_cpu_temp_var = tk.StringVar(value="")
        self._sysbar_cpu_temp_lbl = tk.Label(
            parent, textvariable=self._sysbar_cpu_temp_var,
            bg=FIG_PANEL, fg=FIG_TEXT2, font=("Segoe UI", 8), width=5,
        )
        self._sysbar_cpu_temp_lbl.pack(side=tk.LEFT)

        _sep()

        # ── GPU ────────────────────────────────────────────────────
        tk.Label(parent, text="GPU", bg=FIG_PANEL, fg=FIG_TEXT2,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(6, 2))
        self._sysbar_gpu_var = tk.StringVar(value="—")
        self._sysbar_gpu_lbl = tk.Label(
            parent, textvariable=self._sysbar_gpu_var,
            bg=FIG_PANEL, fg=FIG_TEXT2, font=("Segoe UI", 8, "bold"), width=4,
        )
        self._sysbar_gpu_lbl.pack(side=tk.LEFT)
        self._sysbar_gpu_temp_var = tk.StringVar(value="")
        self._sysbar_gpu_temp_lbl = tk.Label(
            parent, textvariable=self._sysbar_gpu_temp_var,
            bg=FIG_PANEL, fg=FIG_TEXT2, font=("Segoe UI", 8), width=5,
        )
        self._sysbar_gpu_temp_lbl.pack(side=tk.LEFT)

        _sep()

        # ── RAM ────────────────────────────────────────────────────
        tk.Label(parent, text="RAM", bg=FIG_PANEL, fg=FIG_TEXT2,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(6, 2))
        self._sysbar_ram_var = tk.StringVar(value="—  ")
        self._sysbar_ram_lbl = tk.Label(
            parent, textvariable=self._sysbar_ram_var,
            bg=FIG_PANEL, fg=FIG_TEXT2, font=("Segoe UI", 8, "bold"), width=5,
        )
        self._sysbar_ram_lbl.pack(side=tk.LEFT)

    def _draw_signal_bars(self, bars: int, color: str) -> None:
        """Draw 5-bar WiFi-style signal indicator on the net canvas."""
        if not hasattr(self, "_sysbar_net_canvas"):
            return
        c = self._sysbar_net_canvas
        c.delete("all")
        bar_w, gap, max_h = 3, 2, 12
        for i in range(5):
            h = max(2, int(max_h * (i + 1) / 5))
            x1 = i * (bar_w + gap)
            y1 = max_h - h
            x2 = x1 + bar_w
            y2 = max_h
            fill = color if i < bars else FIG_BORDER
            c.create_rectangle(x1, y1, x2, y2, fill=fill, outline="")

    def _update_sysbar(
        self,
        cpu: float,
        cpu_temp: float | None,
        gpu: float | None,
        gpu_temp: float | None,
        ram: float,
        net_ms: float | None,
    ) -> None:
        """Apply fresh monitoring values to the status bar (called on main thread)."""
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return

        col  = self._sys_color
        tcol = self._temp_color

        # CPU
        if hasattr(self, "_sysbar_cpu_var"):
            if cpu >= 0:
                self._sysbar_cpu_var.set(f"{cpu:.0f}%")
                self._sysbar_cpu_lbl.configure(fg=col(cpu))
            else:
                self._sysbar_cpu_var.set("N/I")
                self._sysbar_cpu_lbl.configure(fg=FIG_TEXT2)
        if hasattr(self, "_sysbar_cpu_temp_var"):
            if cpu_temp is not None:
                self._sysbar_cpu_temp_var.set(f"{cpu_temp:.0f}°C")
                self._sysbar_cpu_temp_lbl.configure(fg=tcol(cpu_temp, gpu=False))
            else:
                self._sysbar_cpu_temp_var.set("")

        # GPU
        if hasattr(self, "_sysbar_gpu_var"):
            if gpu is not None:
                self._sysbar_gpu_var.set(f"{gpu:.0f}%")
                self._sysbar_gpu_lbl.configure(fg=col(gpu))
            else:
                self._sysbar_gpu_var.set("N/A")
                self._sysbar_gpu_lbl.configure(fg=FIG_TEXT2)
        if hasattr(self, "_sysbar_gpu_temp_var"):
            if gpu_temp is not None:
                self._sysbar_gpu_temp_var.set(f"{gpu_temp:.0f}°C")
                self._sysbar_gpu_temp_lbl.configure(fg=tcol(gpu_temp, gpu=True))
            else:
                self._sysbar_gpu_temp_var.set("")

        # RAM
        if hasattr(self, "_sysbar_ram_var"):
            if ram >= 0:
                self._sysbar_ram_var.set(f"{ram:.0f}%")
                self._sysbar_ram_lbl.configure(fg=col(ram))
            else:
                self._sysbar_ram_var.set("N/I")
                self._sysbar_ram_lbl.configure(fg=FIG_TEXT2)

        bars, net_color = self._net_bars_info(net_ms)
        self._draw_signal_bars(bars, net_color)

    def _start_sysmon(self) -> None:
        """Launch background daemon thread for system monitoring."""
        t = threading.Thread(target=self._run_sysmon, daemon=True)
        t.start()

    def _run_sysmon(self) -> None:
        """Background loop: read CPU/GPU/RAM/net, schedule UI update every ~4 s."""

        # ── One-time GPU detection ─────────────────────────────────
        _use_pynvml    = _HAS_GPU and _pynvml is not None
        _use_nvidiasmi = False
        if not _use_pynvml:
            try:
                r = subprocess.run(
                    ["nvidia-smi",
                     "--query-gpu=utilization.gpu",
                     "--format=csv,noheader,nounits"],
                    timeout=4,
                    creationflags=0x08000000,   # CREATE_NO_WINDOW on Windows
                    **_SUBPROC_TEXT,
                )
                if r.returncode == 0:
                    _use_nvidiasmi = True
            except Exception:
                pass

        while True:
            try:
                alive = self.winfo_exists()
            except Exception:
                break
            if not alive:
                break

            # CPU — interval=1 blocks 1 sec but gives accurate reading every call
            if _psutil is not None:
                cpu = float(_psutil.cpu_percent(interval=1))
                ram = float(_psutil.virtual_memory().percent)
            else:
                cpu = -1.0
                ram = -1.0

            # CPU temperature
            cpu_temp: float | None = None
            if _psutil is not None:
                try:
                    temps = _psutil.sensors_temperatures()  # works on some Windows
                    if temps:
                        for key in ("coretemp", "cpu_thermal", "k10temp", "acpitz"):
                            if key in temps and temps[key]:
                                cpu_temp = float(temps[key][0].current)
                                break
                except Exception:
                    pass
            if cpu_temp is None:
                # Fallback: wmic (works on most Windows without extra packages)
                try:
                    r = subprocess.run(
                        ["wmic", "/namespace:\\\\root\\wmi", "PATH",
                         "MSAcpi_ThermalZoneTemperature", "get", "CurrentTemperature"],
                        timeout=3,
                        creationflags=0x08000000,
                        **_SUBPROC_TEXT,
                    )
                    nums = [l.strip() for l in r.stdout.splitlines()
                            if l.strip().isdigit()]
                    if nums:
                        cpu_temp = (int(nums[0]) - 2732) / 10.0
                except Exception:
                    pass

            # GPU load + temperature
            gpu: float | None = None
            gpu_temp: float | None = None
            if _use_pynvml:
                try:
                    util = _pynvml.nvmlDeviceGetUtilizationRates(_GPU_HANDLE)
                    gpu  = float(util.gpu)
                    gpu_temp = float(
                        _pynvml.nvmlDeviceGetTemperature(
                            _GPU_HANDLE, _pynvml.NVML_TEMPERATURE_GPU
                        )
                    )
                except Exception:
                    pass
            elif _use_nvidiasmi:
                try:
                    r = subprocess.run(
                        ["nvidia-smi",
                         "--query-gpu=utilization.gpu,temperature.gpu",
                         "--format=csv,noheader,nounits"],
                        timeout=4,
                        creationflags=0x08000000,
                        **_SUBPROC_TEXT,
                    )
                    if r.returncode == 0:
                        parts = r.stdout.strip().splitlines()[0].split(",")
                        gpu      = float(parts[0].strip())
                        gpu_temp = float(parts[1].strip())
                except Exception:
                    pass

            # Internet — try multiple hosts on port 80 (TCP, not blocked by firewall)
            net_ms = self._check_net_ms()

            try:
                self.after(
                    0,
                    lambda c=cpu, ct=cpu_temp, g=gpu, gt=gpu_temp, r=ram, n=net_ms:
                        self._update_sysbar(c, ct, g, gt, r, n),
                )
            except Exception:
                break

            time.sleep(2)

    def _change_username(self) -> None:
        """Prompt to rename the user shown in the status bar."""
        from tkinter import simpledialog
        current = _load_config().get("user_name", "Иван")
        name = simpledialog.askstring(
            "Имя пользователя", "Введите имя:", initialvalue=current, parent=self,
        )
        if name and name.strip():
            name = name.strip()
            cfg = _load_config()
            cfg["user_name"] = name
            _save_config(cfg)
            if hasattr(self, "_sysbar_user_var"):
                self._sysbar_user_var.set(f"👤  {name}")

    def _pick_etalon(self) -> None:
        """Open file dialog to manually choose a fallback etalon image."""
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Выберите эталонное изображение",
            filetypes=[
                ("Изображения", "*.jpg *.jpeg *.png *.tiff *.tif *.bmp *.webp"),
                ("Все файлы", "*.*"),
            ],
        )
        if not path:
            return
        self._etalon_path = path
        cfg = _load_config()
        cfg["etalon"] = path
        _save_config(cfg)
        self._display_etalon(path)

    def _display_etalon(self, path: str | None) -> None:
        """Render the etalon image (or placeholder) in ref_canvas."""
        if not hasattr(self, "ref_canvas"):
            return
        self.ref_canvas.delete("all")
        if not path:
            self.ref_canvas.create_text(
                self._ref_w // 2, self._ref_h // 2 - 10,
                text="Эталон не загружен", fill=FIG_TEXT2,
                font=("Segoe UI", 10),
            )
            self.ref_canvas.create_text(
                self._ref_w // 2, self._ref_h // 2 + 10,
                text="Нажмите для выбора", fill=FIG_TEXT2,
                font=("Segoe UI", 8),
            )
            return
        try:
            img = Image.open(path)
            img = ImageOps.fit(img, (self._ref_w, self._ref_h), Image.LANCZOS)
            self._ref_photo = ImageTk.PhotoImage(img)
            self.ref_canvas.create_image(0, 0, image=self._ref_photo, anchor=tk.NW)
            # Small "×" button to clear etalon
            self.ref_canvas.create_rectangle(
                self._ref_w - 20, 0, self._ref_w, 20,
                fill="#00000088", outline="",
            )
            self.ref_canvas.create_text(
                self._ref_w - 10, 10,
                text="×", fill="white", font=("Segoe UI", 11, "bold"),
                tags="clear_btn",
            )
            self.ref_canvas.tag_bind("clear_btn", "<Button-1>", lambda _e: self._clear_etalon())
        except Exception:
            self._display_etalon(None)

    def _clear_etalon(self) -> None:
        self._etalon_path = None
        cfg = _load_config()
        cfg.pop("etalon", None)
        _save_config(cfg)
        self._display_etalon(None)

    # ══════════════════════════════════════════════════════════════
    #  Zona (Telegram) notifications
    # ══════════════════════════════════════════════════════════════

    def _zona_ok(self) -> bool:
        """Return True if Zona notifications are enabled and configured."""
        cfg  = _load_config()
        zona = _load_zona_data()
        return bool(
            cfg.get("zona_enabled")
            and zona.get("TOKEN", "").strip()
            and cfg.get("zona_chat_id", "").strip()
        )

    def _send_zona(self, text: str) -> None:
        """Send a Telegram message in a daemon thread (fire-and-forget)."""
        if not self._zona_ok():
            return
        zona    = _load_zona_data()
        token   = zona["TOKEN"].strip()
        cfg     = _load_config()
        chat_id = cfg.get("zona_chat_id", "").strip()
        user    = cfg.get("user_name", "").strip()
        full_text = f"{text}\n\n<i>От: {user}</i>" if user else text

        def _post() -> None:
            import urllib.request, urllib.parse, json as _json
            try:
                url  = f"https://api.telegram.org/bot{token}/sendMessage"
                body = _json.dumps({
                    "chat_id": chat_id,
                    "text": full_text,
                    "parse_mode": "HTML",
                }).encode()
                req = urllib.request.Request(
                    url, data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=8)
            except Exception:
                pass  # silent — don't disturb the user on network failure

        threading.Thread(target=_post, daemon=True).start()

    def show_zona_settings(self) -> None:
        """Open Zona notification settings dialog."""
        cfg  = _load_config()
        zona = _load_zona_data()

        bot_url   = zona.get("URL",   "@ZonaDeck_bot")
        has_token = bool(zona.get("TOKEN", "").strip())
        default_chat = zona.get("ID", "")  # default group from data.dat

        win = tk.Toplevel(self)
        win.title("Уведомления от Zona")
        win.geometry("480x370")
        win.resizable(False, False)
        win.configure(bg=FIG_BG)
        win.transient(self)
        win.grab_set()
        win.focus_set()
        self._prepare_dialog_window(win)

        pad = dict(padx=20)

        # ── Bot info block (read-only) ──────────────────────────────
        bot_frame = tk.Frame(win, bg=FIG_PANEL, padx=12, pady=10)
        bot_frame.grid(row=0, column=0, columnspan=2, sticky="ew", **pad, pady=(16, 0))
        tk.Label(bot_frame, text="Бот Zona", bg=FIG_PANEL, fg=FIG_TEXT,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        tk.Label(bot_frame,
                 text=f"{bot_url}  —  {'токен загружен ✓' if has_token else '⚠ data.dat не найден'}",
                 bg=FIG_PANEL, fg=FIG_ACCENT if has_token else "#ef4444",
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))
        tk.Label(bot_frame,
                 text=f"Добавьте {bot_url} в свою группу и скопируйте ID группы ниже.",
                 bg=FIG_PANEL, fg=FIG_TEXT2,
                 font=("Segoe UI", 8), wraplength=420).pack(anchor="w", pady=(4, 0))

        # ── Group ID (editable) ────────────────────────────────────
        tk.Label(win, text="ID вашей группы / чата:", bg=FIG_BG, fg=FIG_TEXT,
                 font=("Segoe UI", 9), anchor="w").grid(
            row=1, column=0, sticky="w", pady=(14, 2), **pad)
        current_chat = cfg.get("zona_chat_id", "") or default_chat
        e_chat = ttk.Entry(win, font=("Segoe UI", 10), width=42)
        e_chat.grid(row=2, column=0, columnspan=2, sticky="ew", **pad)
        e_chat.insert(0, current_chat)

        # ── Enable checkbox ────────────────────────────────────────
        enabled_var = tk.BooleanVar(value=bool(cfg.get("zona_enabled", False)))
        chk_frame = tk.Frame(win, bg=FIG_BG)
        chk_frame.grid(row=3, column=0, columnspan=2, sticky="w", pady=(14, 0), **pad)
        self._make_check(
            chk_frame, bool(cfg.get("zona_enabled", False)),
            lambda v: enabled_var.set(v),
            bg=FIG_BG,
        ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(chk_frame, text="Получать уведомления", bg=FIG_BG, fg=FIG_TEXT,
                 font=("Segoe UI", 10)).pack(side=tk.LEFT)

        # ── Status ─────────────────────────────────────────────────
        status_var = tk.StringVar(value="")
        tk.Label(win, textvariable=status_var, bg=FIG_BG, fg=FIG_TEXT2,
                 font=("Segoe UI", 9)).grid(row=4, column=0, columnspan=2,
                                            sticky="w", pady=(8, 0), **pad)

        def _save() -> None:
            new_cfg = _load_config()
            new_cfg["zona_chat_id"] = e_chat.get().strip()
            new_cfg["zona_enabled"] = enabled_var.get()
            _save_config(new_cfg)
            win.destroy()

        def _test() -> None:
            chat_id = e_chat.get().strip()
            token   = zona.get("TOKEN", "").strip()
            if not token:
                status_var.set("⚠  data.dat не найден или пуст")
                return
            if not chat_id:
                status_var.set("⚠  Введите ID группы")
                return
            status_var.set("Отправляю тестовое сообщение…")
            win.update_idletasks()
            import urllib.request, json as _json

            def _worker() -> None:
                try:
                    url  = f"https://api.telegram.org/bot{token}/sendMessage"
                    body = _json.dumps({
                        "chat_id": chat_id,
                        "text": (
                            f"✅ <b>Zona подключена!</b>\n"
                            f"AutoRAW Compressor будет присылать уведомления в эту группу."
                        ),
                        "parse_mode": "HTML",
                    }).encode()
                    req = urllib.request.Request(
                        url, data=body,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=8) as r:
                        resp = _json.loads(r.read())
                    if resp.get("ok"):
                        self.after(0, lambda: status_var.set("✅  Сообщение отправлено успешно"))
                    else:
                        err = resp.get("description", "неизвестная ошибка")
                        self.after(0, lambda e=err: status_var.set(f"❌  Ошибка: {e}"))
                except Exception as ex:
                    self.after(0, lambda e=str(ex): status_var.set(f"❌  {e}"))

            threading.Thread(target=_worker, daemon=True).start()

        # ── Test button (full width, separate row) ─────────────────
        ttk.Button(win, text="📨  Отправить тестовое сообщение",
                   command=_test).grid(row=5, column=0, columnspan=2,
                                       sticky="ew", pady=(14, 0), **pad)

        # ── Save / Cancel ──────────────────────────────────────────
        btn_frame = tk.Frame(win, bg=FIG_BG)
        btn_frame.grid(row=6, column=0, columnspan=2, pady=(10, 16), sticky="e", **pad)
        ttk.Button(btn_frame, text="Сохранить", style="Accent.TButton",
                   command=_save).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_frame, text="Отмена",    command=win.destroy).pack(side=tk.LEFT)

        win.columnconfigure(0, weight=1)

    # ══════════════════════════════════════════════════════════════
    #  About-menu dialogs
    # ══════════════════════════════════════════════════════════════

    @staticmethod
    def _info_window(master: tk.Tk, title: str, w: int = 680, h: int = 520) -> tk.Toplevel:
        """Create a styled modal-like Toplevel."""
        win = tk.Toplevel(master)
        win.title(title)
        win.geometry(f"{w}x{h}")
        win.resizable(True, True)
        win.configure(bg=FIG_BG)
        win.transient(master)
        win.grab_set()
        win.focus_set()
        if hasattr(master, "_prepare_dialog_window"):
            master._prepare_dialog_window(win)  # type: ignore[attr-defined]
        return win

    def _scrolled_text(self, parent: tk.Widget, **kw: object) -> tk.Text:
        """Text widget + vertical scrollbar packed inside parent."""
        frame = tk.Frame(parent, bg=FIG_BG)
        frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(8, 0))
        sb = self._win11_sb(frame, orient=tk.VERTICAL)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        t = tk.Text(
            frame,
            wrap=tk.WORD,
            yscrollcommand=sb.set,
            bg=FIG_PANEL, fg=FIG_TEXT,
            insertbackground=FIG_TEXT,
            relief="flat", borderwidth=0,
            padx=14, pady=10,
            font=("Segoe UI", 10),
            cursor="arrow",
            **kw,
        )
        t.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=t.yview)
        return t

    def _apply_md_tags(self, t: tk.Text) -> None:
        """Define Text tags used by the markdown renderer."""
        t.tag_configure("h1",   font=("Segoe UI", 16, "bold"), foreground=FIG_ACCENT,  spacing3=6)
        t.tag_configure("h2",   font=("Segoe UI", 13, "bold"), foreground=FIG_TEXT,    spacing3=4, spacing1=10)
        t.tag_configure("h3",   font=("Segoe UI", 10, "bold"), foreground=FIG_ACCENT,  spacing3=2, spacing1=6)
        t.tag_configure("body", font=("Segoe UI", 10),         foreground=FIG_TEXT)
        t.tag_configure("li",   font=("Segoe UI", 10),         foreground=FIG_TEXT,    lmargin1=20, lmargin2=28)
        t.tag_configure("code", font=("Consolas", 9),          foreground="#e5c07b",   background=FIG_BG)
        t.tag_configure("bold", font=("Segoe UI", 10, "bold"), foreground=FIG_TEXT)
        t.tag_configure("dim",  font=("Segoe UI", 9),          foreground=FIG_TEXT2)

    def _insert_md(self, t: tk.Text, md: str) -> None:
        """Minimal markdown → Text-widget renderer."""
        import re
        self._apply_md_tags(t)
        t.configure(state=tk.NORMAL)
        t.delete("1.0", tk.END)

        for raw_line in md.splitlines():
            line = raw_line.rstrip()

            if line.startswith("### "):
                t.insert(tk.END, line[4:] + "\n", "h3")
            elif line.startswith("## "):
                t.insert(tk.END, line[3:] + "\n", "h2")
            elif line.startswith("# "):
                t.insert(tk.END, line[2:] + "\n", "h1")
            elif line.startswith("- ") or line.startswith("* "):
                self._insert_inline(t, "• " + line[2:], "li")
                t.insert(tk.END, "\n")
            elif line == "" or line == "---":
                t.insert(tk.END, "\n")
            else:
                self._insert_inline(t, line, "body")
                t.insert(tk.END, "\n")

        t.configure(state=tk.DISABLED)

    @staticmethod
    def _insert_inline(t: tk.Text, text: str, base_tag: str) -> None:
        """Insert a line applying **bold** and `code` spans."""
        import re
        pattern = re.compile(r"`([^`]+)`|\*\*([^*]+)\*\*")
        pos = 0
        for m in pattern.finditer(text):
            if m.start() > pos:
                t.insert(tk.END, text[pos:m.start()], base_tag)
            if m.group(1) is not None:
                t.insert(tk.END, m.group(1), "code")
            else:
                t.insert(tk.END, m.group(2), "bold")
            pos = m.end()
        if pos < len(text):
            t.insert(tk.END, text[pos:], base_tag)

    # ── About ──────────────────────────────────────────────────────

    def show_about(self) -> None:
        from version import APP_NAME, VERSION
        win = self._info_window(self, "О программе", 560, 400)
        t = self._scrolled_text(win)
        self._insert_md(t, f"""\
# {APP_NAME}

**Версия:** {VERSION}

## Описание

AutoRAW Compressor — инструмент пакетной обработки фотографий товаров.
Позволяет загрузить папку с RAW/JPEG-съёмками, настроить кадрирование
каждого снимка вручную и экспортировать результат в заданное разрешение.

## Основные возможности

- Загрузка папки с изображениями (RAW, JPEG, PNG, TIFF)
- Предпросмотр кадра в реальном времени
- Настройка позиции (X/Y), масштаба и поворота
- Автодетекция товара на снимке
- Цветокоррекция: контраст, тени, температура, оттенок
- Эталонный референс для сравнения с образцом
- Пакетный экспорт выбранных кадров
- Тёмная / светлая / системная тема
- Мониторинг CPU / GPU / RAM / сети

## Репозиторий

`gitverse.ru/delbraun/AutoRAWCompressor`
""")
        ttk.Button(win, text="Закрыть", command=win.destroy).pack(pady=10)

    # ── Manual ─────────────────────────────────────────────────────

    def show_manual(self) -> None:
        win = self._info_window(self, "Инструкция", 700, 580)
        t = self._scrolled_text(win)
        self._insert_md(t, """\
# Инструкция пользователя

## 1. Загрузка папки

Введите путь в поле вверху или нажмите `📂` для выбора.
Перетащите папку или файл прямо в окно программы.
В дереве слева появится список подпапок — выберите нужную.

## 2. Выбор кадра

Миниатюры отображаются в правой панели.
Нажмите на миниатюру для выбора кадра.
Галочка на миниатюре включает / исключает кадр из экспорта.
Стрелки клавиатуры переключают между кадрами.

## 3. Настройка кадра

**Мышь на холсте превью:**

- Зажатая ЛКМ — свободное перемещение по X и Y
- `Alt` + ЛКМ — движение строго по оси X
- `Shift` + ЛКМ — движение строго по оси Y
- `Ctrl` + ЛКМ — поворот фотографии
- Колесо мыши — масштаб ±4%
- `Alt` + колесо — масштаб ±1% (точная настройка)

**Слайдеры панели управления:**

- **X / Y** — смещение кадра в пикселях холста
- **Масштаб** — зум от 0.5× до 3.0×
- **Поворот** — угол от −20° до +20°

**Кнопки:**
- `Сбросить кадр` — обнуляет все параметры текущего кадра
- `Сбросить папку` — обнуляет параметры всех кадров папки

## 4. Эталон (референс)

В правой панели вверху — виджет эталона.
Он автоматически подгружает изображение из папки `reference/<имя_папки>/`
в зависимости от выбранного кадра.

Структура папок:
```
Корень/
  Sneakers/       <- рабочие кадры
  reference/
    Sneakers/     <- эталоны (1.jpg = кадр 1, и т.д.)
```

Нажмите на виджет чтобы выбрать эталон вручную.
Нажмите `×` в углу виджета для сброса.

## 5. Цветокоррекция

Включите переключатель **Цветокор** в нижней панели.
Настройте параметры слайдерами:
- **Контраст** — от −100 до +100
- **Тени** — от −100 до +100
- **Температура** — от 2000 К до 10000 К
- **Оттенок** — от −100 до +100

`Сохранить` — применить настройки к текущему кадру.
`Применить к папке` — скопировать настройки на все кадры папки.

## 6. Экспорт

Нажмите `Экспорт` в верхней панели.
Экспортируются только кадры с активной галочкой.
""")
        ttk.Button(win, text="Закрыть", command=win.destroy).pack(pady=10)

    # ── Changelog ──────────────────────────────────────────────────

    def show_changelog(self) -> None:
        win = self._info_window(self, "Что изменилось", 700, 560)
        t = self._scrolled_text(win)
        try:
            text = resource_path("CHANGELOG.md").read_text(encoding="utf-8")
        except Exception:
            text = "_Файл CHANGELOG.md не найден._"
        self._insert_md(t, text)
        ttk.Button(win, text="Закрыть", command=win.destroy).pack(pady=10)

    # ── Check updates ──────────────────────────────────────────────

    def _startup_update_check(self) -> None:
        def _worker() -> None:
            try:
                info = fetch_latest_update()
            except Exception:
                return
            if info is None or info.version in self._update_skipped_session:
                return
            self.after(0, lambda: self._prompt_startup_update(info))

        threading.Thread(target=_worker, daemon=True).start()

    def _prompt_startup_update(self, info: UpdateInfo) -> None:
        if info.version in self._update_skipped_session:
            return
        size_hint = f" ({info.size // (1024 * 1024)} МБ)" if info.size else ""
        install = messagebox.askyesno(
            "Доступно обновление",
            f"Найдена новая версия {info.version}{size_hint}.\n"
            f"Текущая: {version_string()}\n\n"
            f"Установить сейчас?\n\n"
            f"«Нет» — напомнить при следующем запуске программы.",
            parent=self,
        )
        if install:
            self._begin_update_install(info)
        else:
            self._update_skipped_session.add(info.version)

    def _begin_update_install(self, info: UpdateInfo) -> None:
        ok, reason = can_self_update()
        if not ok:
            messagebox.showinfo(
                "Обновление",
                f"Доступна версия {info.version}.\n\n{reason}\n\nСкачать: {RELEASES_PAGE}",
                parent=self,
            )
            return

        win = self._info_window(self, "Обновление", 480, 200)
        win.resizable(False, False)

        stage_var = tk.StringVar(value="Подготовка…")
        tk.Label(win, textvariable=stage_var, bg=FIG_BG, fg=FIG_TEXT, font=("Segoe UI", 10)).pack(pady=(20, 8))
        progress_var = tk.DoubleVar(value=0)
        ttk.Progressbar(win, variable=progress_var, maximum=100, length=420).pack(pady=(0, 6))
        detail_var = tk.StringVar(value="")
        tk.Label(win, textvariable=detail_var, bg=FIG_BG, fg=FIG_TEXT2, font=("Segoe UI", 9)).pack()

        def on_progress(stage_key: str, pct: float, detail: str) -> None:
            labels = {
                "download": "Скачивание обновления",
                "extract": "Распаковка архива",
                "apply": "Установка файлов",
            }
            label = labels.get(stage_key, "Обновление")

            def _ui() -> None:
                stage_var.set(label)
                progress_var.set(max(0, min(100, pct)))
                detail_var.set(detail)

            self.after(0, _ui)

        def _worker() -> None:
            try:
                run_update(info, on_progress=on_progress)
            except Exception as exc:
                err = str(exc)

                def _fail() -> None:
                    try:
                        win.destroy()
                    except Exception:
                        pass
                    messagebox.showerror("Обновление", err, parent=self)

                self.after(0, _fail)

        threading.Thread(target=_worker, daemon=True).start()

    def check_updates(self) -> None:
        """Проверка, скачивание и автоустановка обновления с GitVerse."""
        win = self._info_window(self, "Обновление", 480, 200)
        win.resizable(False, False)

        tk.Label(
            win,
            text="Проверка обновлений",
            bg=FIG_BG,
            fg=FIG_TEXT,
            font=("Segoe UI", 11, "bold"),
        ).pack(pady=(16, 4))

        stage_var = tk.StringVar(value="Подключаемся к GitVerse…")
        tk.Label(win, textvariable=stage_var, bg=FIG_BG, fg=FIG_TEXT2, font=("Segoe UI", 10)).pack(pady=(0, 8))

        progress_var = tk.DoubleVar(value=0)
        bar = ttk.Progressbar(win, variable=progress_var, maximum=100, length=420)
        bar.pack(pady=(0, 6))

        detail_var = tk.StringVar(value="")
        tk.Label(win, textvariable=detail_var, bg=FIG_BG, fg=FIG_TEXT2, font=("Segoe UI", 9)).pack()

        btn_row = tk.Frame(win, bg=FIG_BG)
        btn_row.pack(pady=(14, 10))
        close_btn = ttk.Button(btn_row, text="Закрыть", command=win.destroy, state=tk.DISABLED)
        close_btn.pack()

        state: dict[str, object] = {"busy": True, "cancelled": False}

        def set_ui(stage: str, pct: float, detail: str) -> None:
            stage_var.set(stage)
            progress_var.set(max(0, min(100, pct)))
            detail_var.set(detail)

        def enable_close() -> None:
            state["busy"] = False
            close_btn.config(state=tk.NORMAL)

        def ask_yes_no(title: str, message: str) -> bool:
            box: dict[str, bool | None] = {"value": None}
            done = threading.Event()

            def _ask() -> None:
                try:
                    win.grab_release()
                except Exception:
                    pass
                box["value"] = messagebox.askyesno(title, message, parent=self)
                try:
                    win.grab_set()
                except Exception:
                    pass
                done.set()

            self.after(0, _ask)
            done.wait(timeout=300)
            return bool(box["value"])

        def on_progress(stage_key: str, pct: float, detail: str) -> None:
            labels = {
                "download": "Скачивание обновления",
                "extract": "Распаковка архива",
                "apply": "Установка файлов",
            }
            label = labels.get(stage_key, "Обновление")
            self.after(0, lambda: set_ui(label, pct, detail))

        def _worker() -> None:
            try:
                self.after(0, lambda: set_ui("Проверка обновлений", 0, "Запрос к GitVerse…"))
                info = fetch_latest_update()
                if info is None:
                    self.after(
                        0,
                        lambda: set_ui(
                            "Актуальная версия",
                            100,
                            f"Установлено: {version_string()}",
                        ),
                    )
                    self.after(0, enable_close)
                    return

                ok, reason = can_self_update()
                if not ok:
                    self.after(
                        0,
                        lambda: set_ui(
                            "Доступно обновление",
                            0,
                            f"{info.version} — {info.asset_name}\n{reason}",
                        ),
                    )
                    self.after(
                        0,
                        lambda: messagebox.showinfo(
                            "Обновление",
                            f"Доступна версия {info.version}.\n\n{reason}\n\nСкачать: {RELEASES_PAGE}",
                            parent=self,
                        ),
                    )
                    self.after(0, enable_close)
                    return

                size_hint = f" ({info.size // (1024 * 1024)} МБ)" if info.size else ""
                if ask_yes_no(
                    "Доступно обновление",
                    f"Найдена версия {info.version}{size_hint}.\n"
                    f"Текущая: {version_string()}\n\n"
                    f"Скачать и установить сейчас?\n"
                    f"Приложение закроется и откроется снова после распаковки.",
                ):
                    try:
                        win.destroy()
                    except Exception:
                        pass
                    self._begin_update_install(info)
                    return

                self.after(0, lambda: set_ui("Отменено", 0, "Обновление не установлено."))
                self.after(0, enable_close)
                return

            except Exception as exc:
                err = str(exc)

                def _fail() -> None:
                    set_ui("Ошибка", 0, err)
                    messagebox.showerror("Обновление", err, parent=self)
                    enable_close()

                self.after(0, _fail)

        def _on_close() -> None:
            if state["busy"]:
                return
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", _on_close)
        threading.Thread(target=_worker, daemon=True).start()

    def show_hotkeys(self) -> None:
        win = tk.Toplevel(self)
        win.title("Управление и горячие клавиши")
        win.geometry("560x460")
        win.resizable(False, False)
        win.configure(bg=FIG_BG)
        win.transient(self)
        win.grab_set()
        self._prepare_dialog_window(win)

        # ── Header ────────────────────────────────────────────────────
        hdr = tk.Frame(win, bg=FIG_PANEL)
        hdr.pack(fill=tk.X)
        tk.Frame(hdr, bg=FIG_ACCENT, width=4).pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(hdr, text="Управление и горячие клавиши",
                 bg=FIG_PANEL, fg=FIG_TEXT,
                 font=("Segoe UI", 11, "bold"),
                 padx=16, pady=12).pack(side=tk.LEFT)
        tk.Frame(win, bg=FIG_BORDER, height=1).pack(fill=tk.X)

        # ── Content ───────────────────────────────────────────────────
        scroll_frame = tk.Frame(win, bg=FIG_BG)
        scroll_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=12)

        SECTIONS: list[tuple[str | None, list[tuple[str, str]]]] = [
            ("Холст — перемещение", [
                ("ЛКМ (тянуть)",        "Свободное перемещение объекта"),
                ("Alt + ЛКМ",           "Движение строго по оси X"),
                ("Shift + ЛКМ",         "Движение строго по оси Y"),
                ("Ctrl + ЛКМ",          "Поворот фотографии"),
                ("← → ↑ ↓",            "Сдвиг на 1 px"),
            ]),
            ("Холст — масштаб", [
                ("Колесо мыши",         "Зум  ±4%"),
                ("Alt + колесо мыши",   "Точный зум  ±1%"),
            ]),
            ("Миниатюры", [
                ("Клик по миниатюре",   "Выбрать кадр"),
                ("Колесо мыши",         "Прокрутка списка кадров"),
            ]),
            ("Прочее", [
                ("F1",                  "Эта справка"),
            ]),
        ]

        for section_title, rows in SECTIONS:
            # section header
            sec_row = tk.Frame(scroll_frame, bg=FIG_BG)
            sec_row.pack(fill=tk.X, pady=(10, 4))
            tk.Frame(sec_row, bg=FIG_ACCENT, width=3, height=13).pack(side=tk.LEFT, padx=(0, 7))
            tk.Label(sec_row, text=(section_title or "").upper(),
                     bg=FIG_BG, fg=FIG_TEXT2,
                     font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, anchor="w")

            for key_text, desc_text in rows:
                row = tk.Frame(scroll_frame, bg=FIG_BG)
                row.pack(fill=tk.X, pady=2)

                # Key badge
                badge = tk.Frame(row, bg=FIG_PANEL,
                                 highlightthickness=1, highlightbackground=FIG_BORDER)
                badge.pack(side=tk.LEFT)
                tk.Label(badge, text=key_text, bg=FIG_PANEL, fg=FIG_TEXT,
                         font=("Segoe UI", 9, "bold"),
                         padx=10, pady=3, width=22, anchor="w").pack()

                # Description
                tk.Label(row, text=desc_text, bg=FIG_BG, fg=FIG_TEXT2,
                         font=("Segoe UI", 9), padx=14).pack(side=tk.LEFT, anchor="w")

        # ── Footer ────────────────────────────────────────────────────
        tk.Frame(win, bg=FIG_BORDER, height=1).pack(fill=tk.X)
        foot = tk.Frame(win, bg=FIG_PANEL)
        foot.pack(fill=tk.X, padx=20, pady=10)
        ttk.Button(foot, text="Закрыть", command=win.destroy).pack(side=tk.RIGHT)

    # ── modifier helpers ──────────────────────────────────────────────
    @staticmethod
    def _mod_alt(state: int)   -> bool: return bool(state & 0x20000)   # Windows Alt
    @staticmethod
    def _mod_shift(state: int) -> bool: return bool(state & 0x0001)
    @staticmethod
    def _mod_ctrl(state: int)  -> bool: return bool(state & 0x0004)

    def start_drag(self, event: tk.Event) -> None:
        state = self.current()
        if not state:
            return
        self.preview.focus_set()
        self.drag_start = (event.x, event.y, state.offset_x, state.offset_y, state.rotation)

    def stop_drag(self, _event: tk.Event) -> None:
        self.drag_start = None

    def drag_preview(self, event: tk.Event) -> None:
        if not self.drag_start:
            return
        start_x, start_y, base_x, base_y, base_rot = self.drag_start
        scale_x = CANVAS_SIZE[0] / PREVIEW_SIZE[0]
        scale_y = CANVAS_SIZE[1] / PREVIEW_SIZE[1]
        dx = (event.x - start_x) * scale_x
        dy = (event.y - start_y) * scale_y

        if self._mod_ctrl(event.state):
            # Ctrl + drag → rotate (horizontal distance = degrees)
            rot_delta = (event.x - start_x) * 40.0 / max(1, self.preview.winfo_width())
            self.rotation.set(max(-20.0, min(20.0, base_rot + rot_delta)))
        elif self._mod_alt(event.state):
            # Alt + drag → X-axis only
            self.offset_x.set(base_x + dx)
            self.offset_y.set(base_y)
        elif self._mod_shift(event.state):
            # Shift + drag → Y-axis only
            self.offset_x.set(base_x)
            self.offset_y.set(base_y + dy)
        else:
            # Plain drag → free XY
            self.offset_x.set(base_x + dx)
            self.offset_y.set(base_y + dy)
        self.update_current()

    def mousewheel_zoom(self, event: tk.Event) -> None:
        # Alt + wheel → fine step (1%); plain wheel → normal step (4%)
        if self._mod_alt(event.state):
            delta = 0.01 if event.delta > 0 else -0.01
        else:
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
        self.select_frame(self.selected_index, save_previous=False)

    def reset_folder(self) -> None:
        for state in self.current_frames():
            state.offset_x = 0.0
            state.offset_y = 0.0
            state.zoom = 1.0
            state.rotation = 0.0
            state.thumb_cache = None
        self.select_frame(self.selected_index, save_previous=False)

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
        self._export_token = token
        self._export_job.reset()
        self._set_export_controls(True)
        use_droplets = bool(self.use_droplet_var.get())
        use_colorcor = bool(self.use_colorcor_var.get())
        self.set_progress(0, "Готовлю экспорт...")
        n_folders = len(checked_folders)
        self._send_zona(
            f"🚀 <b>Экспорт запущен</b>\n"
            f"Папок: {n_folders}"
        )
        threading.Thread(target=self.export_worker, args=(token, checked_folders, use_droplets, use_colorcor), daemon=True).start()

    def export_worker(self, token: int, checked_folders: list[Path], use_droplets: bool, use_colorcor: bool) -> None:
        exported = 0
        droplet_processed = 0
        job = self._export_job
        total_units = 0
        for folder in checked_folders:
            folder_state = self.folder_states.get(folder)
            if not folder_state:
                continue
            if folder_state.frames is None:
                source_paths = direct_image_files(folder)[:8]
                total_units += len(source_paths) * 2
                if use_droplets:
                    total_units += len(source_paths)
            else:
                checked_frames = [frame for frame in folder_state.frames if frame.checked]
                total_units += len(checked_frames)
                if use_droplets:
                    total_units += len([frame for frame in checked_frames if frame.frame in DROPLET_BY_FRAME])
        total_units = max(1, total_units)
        done_units = 0
        aspect = target_aspect(REFERENCE_DIR)
        exported_for_droplets: list[tuple[Path, str]] = []

        def stop_now() -> bool:
            return job.should_stop(token, self.load_token)

        def report_progress(label: str) -> None:
            active = job.active_elapsed()
            eta = (active / max(1, done_units) * max(0, total_units - done_units)) if done_units else 0.0
            pause_note = " · пауза" if job.paused else ""
            self.worker_events.put(("progress", token, done_units, total_units, f"{label}{pause_note}", eta))

        for folder in checked_folders:
            if stop_now():
                break

            folder_state = self.folder_states.get(folder)
            if not folder_state:
                continue

            frames = folder_state.frames
            if frames is None:
                loaded: list[tuple[Path, Image.Image]] = []
                paths = direct_image_files(folder)[:8]
                for path in paths:
                    if stop_now():
                        break
                    report_progress(f"Открываю {folder.name}\\{path.name}")
                    try:
                        img = open_preview(path, max_side=WORKING_MAX_SIDE)
                        loaded.append((path, img))
                    except Exception as exc:
                        self.worker_events.put(("warning", token, f"Не удалось открыть {path.name}:\n{exc}"))
                    done_units += 1
                if stop_now():
                    break
                frames = [
                    FrameState(
                        path=path,
                        frame=frame,
                        image=img,
                        crop_box=crop_box_for_assigned_frame(path, img, aspect, frame),
                        match_score=score,
                    )
                    for path, img, frame, score in assign_frames_by_search(loaded)
                ]
                folder_state.frames = frames

            checked_frames = [frame for frame in frames if frame.checked]
            if not checked_frames:
                continue

            output_dir = folder / folder.name
            output_dir.mkdir(parents=True, exist_ok=True)
            for frame in checked_frames:
                if stop_now():
                    break
                export_name = export_name_for_frame(frame)
                report_progress(f"Экспорт {folder.name}\\{export_name}")
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
                output_path = output_dir / export_name
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
            if stop_now():
                break

        if not stop_now() and use_droplets and exported_for_droplets:
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
                    if stop_now():
                        break
                    report_progress(f"Дроплет {droplet_name}: {output_path.name}")
                    try:
                        before_stat = output_path.stat()
                        result = subprocess.run(
                            [str(droplet_exe), str(output_path)],
                            **_SUBPROC_TEXT,
                        )
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
                if stop_now():
                    break

        active_elapsed = job.active_elapsed()
        cancelled = job.cancelled
        self.worker_events.put(("export_done", token, exported, droplet_processed, active_elapsed, cancelled))

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
                _, token, exported, droplet_processed, active_elapsed, cancelled = event
                if token != getattr(self, "_export_token", token):
                    continue
                self._set_export_controls(False)
                if cancelled:
                    info = f"Экспорт отменён: {exported} файлов, рабочее время {active_elapsed:.1f} сек"
                    msg = f"Экспорт отменён.\nФайлов успело сохраниться: {exported}\nРабочее время: {active_elapsed:.1f} сек (без пауз)"
                    zona_title = "⏹ <b>Экспорт отменён</b>"
                else:
                    info = f"Экспорт готов: {exported} файлов, рабочее время {active_elapsed:.1f} сек"
                    msg = f"Экспорт готов.\nФайлов: {exported}\nРабочее время: {active_elapsed:.1f} сек (без пауз)"
                    zona_title = "✅ <b>Экспорт завершён</b>"
                if droplet_processed:
                    info += f" (дроплет: {droplet_processed})"
                    msg += f"\nЧерез дроплеты обработано: {droplet_processed}"
                self.set_progress(100 if not cancelled else self.progress_var.get(), info)
                self.render_thumbnails()
                messagebox.showinfo(APP_NAME, msg)
                zona_text = f"{zona_title}\nФайлов: {exported}  |  Рабочее время: {active_elapsed:.1f} сек"
                if droplet_processed:
                    zona_text += f"\nДроплет: {droplet_processed}"
                self._send_zona(zona_text)
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
                    self._send_zona(f"❌ <b>Ошибка экспорта</b>\n{text}")

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
