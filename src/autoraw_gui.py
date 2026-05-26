from __future__ import annotations

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

from PIL import Image, ImageEnhance, ImageOps, ImageTk

from app_paths import resource_path
from autoraw_crop import (
    CANVAS_SIZE,
    LAYOUT_RULES,
    Box,
    crop_from_object,
    crop_from_rule,
    detect_object,
    expand_box,
    frame_id,
    image_files,
    open_preview,
    target_aspect,
)


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".nef", ".dng"}
PREVIEW_SIZE = (700, 525)
THUMB_SIZE = (182, 137)
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


def auto_crop(path: Path, img: Image.Image, aspect: float) -> Box:
    frame = frame_id(path)
    rule = LAYOUT_RULES.get(frame)
    analysis = img.copy()
    analysis.thumbnail((360, 360), Image.Resampling.LANCZOS)
    detected_box, _ = detect_object(analysis, combine_components=bool(rule and rule.combine_components))
    object_box = scale_box(detected_box, analysis.size, img.size) if detected_box else None

    if object_box and rule and not rule.manual_only:
        layout_box = expand_box(object_box, img.size, rule)
        return crop_from_rule(layout_box, img.size, aspect, rule)

    if object_box:
        return crop_from_object(object_box, img.size, aspect, padding=0.11)

    return Box(0, 0, img.width, img.height)


def scale_box(box: Box, source_size: tuple[int, int], target_size: tuple[int, int]) -> Box:
    sx = target_size[0] / source_size[0]
    sy = target_size[1] / source_size[1]
    return Box(
        int(box.left * sx),
        int(box.top * sy),
        int(box.right * sx),
        int(box.bottom * sy),
    ).clamp(*target_size)


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

    # For rotation we keep at least 1.0 base zoom, then auto-zoom in so
    # corners stay inside the source image (no black/white fillers).
    if rotation:
        zoom = max(1.0, zoom)
        rot_factor_x = (cos_t * float(size[0]) + sin_t * float(size[1])) / max(1.0, float(size[0]))
        rot_factor_y = (sin_t * float(size[0]) + cos_t * float(size[1])) / max(1.0, float(size[1]))
        zoom *= max(rot_factor_x, rot_factor_y)

    # If source is still too small for rotated viewport, zoom in further.
    while True:
        viewport_w = max(1.0, box.width / zoom)
        viewport_h = max(1.0, box.height / zoom)
        rot_bbox_w = cos_t * viewport_w + sin_t * viewport_h
        rot_bbox_h = sin_t * viewport_w + cos_t * viewport_h
        need = max(
            rot_bbox_w / max(1.0, float(source.width)),
            rot_bbox_h / max(1.0, float(source.height)),
        )
        if need <= 1.0 + 1e-6:
            break
        zoom *= need

    viewport_w = max(1.0, box.width / zoom)
    viewport_h = max(1.0, box.height / zoom)
    scale_src_x = viewport_w / size[0]
    scale_src_y = viewport_h / size[1]

    base_cx = (box.left + box.right) / 2.0
    base_cy = (box.top + box.bottom) / 2.0
    cx = base_cx - (state.offset_x * scale_src_x)
    cy = base_cy - (state.offset_y * scale_src_y)

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

    viewport_left = cx - viewport_w / 2.0
    viewport_top = cy - viewport_h / 2.0

    frame = source.transform(
        size,
        Image.Transform.AFFINE,
        (scale_src_x, 0.0, viewport_left, 0.0, scale_src_y, viewport_top),
        resample=Image.Resampling.BICUBIC,
    )

    if rotation:
        frame = frame.rotate(rotation, resample=Image.Resampling.BICUBIC, expand=False)

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
        self.title("AutoRAW Compressor")
        self.geometry("1320x820")
        self.minsize(1180, 760)

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

        self._build_ui()
        self.after(100, self.process_worker_events)

        if initial_folder:
            self.load_root(initial_folder)

    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=10)
        top.pack(fill=tk.X)

        self.drop_var = tk.StringVar(value="Перетащите папку на run_gui.bat или вставьте путь сюда")
        self.drop_entry = ttk.Entry(top, textvariable=self.drop_var, font=("Segoe UI", 10))
        self.drop_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(top, text="Загрузить папку", command=self.load_from_entry).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(top, text="...", width=3, command=self.pick_folder).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(top, text="Экспорт отмеченных", command=self.export_checked).pack(side=tk.LEFT, padx=(12, 0))
        self.use_droplet_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Использовать дроплет", variable=self.use_droplet_var).pack(side=tk.LEFT, padx=(12, 0))

        progress = ttk.Frame(self, padding=(10, 0, 10, 8))
        progress.pack(fill=tk.X)
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(progress, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.progress_label = tk.StringVar(value="Готово")
        ttk.Label(progress, textvariable=self.progress_label, width=58).pack(side=tk.LEFT, padx=(10, 0))

        body = ttk.Frame(self, padding=(10, 0, 10, 10))
        body.pack(fill=tk.BOTH, expand=True)

        left_panel = ttk.Frame(body, width=310)
        left_panel.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Label(left_panel, text="Папки").pack(anchor=tk.W)
        self.folder_tree = ttk.Treeview(left_panel, columns=("check", "count"), show="tree headings", height=25)
        self.folder_tree.heading("#0", text="Папка")
        self.folder_tree.heading("check", text="✓")
        self.folder_tree.heading("count", text="Кадры")
        self.folder_tree.column("#0", width=210, stretch=True)
        self.folder_tree.column("check", width=36, anchor=tk.CENTER, stretch=False)
        self.folder_tree.column("count", width=48, anchor=tk.CENTER, stretch=False)
        self.folder_tree.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self.folder_tree.bind("<<TreeviewSelect>>", self.on_folder_select)
        self.folder_tree.bind("<Button-1>", self.on_folder_click)

        center = ttk.Frame(body)
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 0))

        self.preview = tk.Canvas(center, width=PREVIEW_SIZE[0], height=PREVIEW_SIZE[1], bg="#f7f7f7", highlightthickness=1)
        self.preview.pack(fill=tk.BOTH, expand=True)
        self.preview.bind("<ButtonPress-1>", self.start_drag)
        self.preview.bind("<B1-Motion>", self.drag_preview)
        self.preview.bind("<MouseWheel>", self.mousewheel_zoom)
        self.preview.bind("<Left>", lambda _e: self.nudge_current(-1, 0))
        self.preview.bind("<Right>", lambda _e: self.nudge_current(1, 0))
        self.preview.bind("<Up>", lambda _e: self.nudge_current(0, -1))
        self.preview.bind("<Down>", lambda _e: self.nudge_current(0, 1))

        controls = ttk.Frame(center, padding=(0, 10, 0, 0))
        controls.pack(fill=tk.X)
        self.offset_x = self._slider(controls, "X", -450, 450, self.update_current)
        self.offset_y = self._slider(controls, "Y", -350, 350, self.update_current)
        self.zoom = self._slider(controls, "Масштаб", 0.5, 2.0, self.update_current)
        self.rotation = self._slider(controls, "Поворот", -20, 20, self.update_current)
        self.zoom.set(1.0)

        buttons = ttk.Frame(center)
        buttons.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(buttons, text="Сбросить кадр", command=self.reset_current).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Сбросить папку", command=self.reset_folder).pack(side=tk.LEFT, padx=8)

        standard = ttk.LabelFrame(center, text="Настройки JPG (экспорт)", padding=(8, 6))
        standard.pack(fill=tk.X, pady=(10, 0))
        self.profile_var = tk.StringVar(value=STANDARD_PROFILE)
        self.contrast_var = tk.IntVar(value=STANDARD_CONTRAST)
        self.shadows_var = tk.IntVar(value=STANDARD_SHADOWS)
        self.temperature_var = tk.IntVar(value=STANDARD_TEMPERATURE)
        self.tint_var = tk.IntVar(value=STANDARD_TINT)

        row0 = ttk.Frame(standard)
        row0.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(row0, text="Профиль").pack(side=tk.LEFT)
        profile_combo = ttk.Combobox(
            row0,
            textvariable=self.profile_var,
            values=[STANDARD_PROFILE],
            state="readonly",
            width=20,
        )
        profile_combo.pack(side=tk.LEFT, padx=(8, 0))
        profile_combo.bind("<<ComboboxSelected>>", lambda _e: self.update_current())

        row1 = ttk.Frame(standard)
        row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="Контрастность").pack(side=tk.LEFT)
        contrast_spin = ttk.Spinbox(row1, from_=-100, to=100, textvariable=self.contrast_var, width=8, command=self.update_current)
        contrast_spin.pack(side=tk.LEFT, padx=(8, 0))
        contrast_spin.bind("<KeyRelease>", lambda _e: self.update_current())

        row2 = ttk.Frame(standard)
        row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="Тени").pack(side=tk.LEFT)
        shadows_spin = ttk.Spinbox(row2, from_=-100, to=100, textvariable=self.shadows_var, width=8, command=self.update_current)
        shadows_spin.pack(side=tk.LEFT, padx=(8, 0))
        shadows_spin.bind("<KeyRelease>", lambda _e: self.update_current())

        row3 = ttk.Frame(standard)
        row3.pack(fill=tk.X, pady=2)
        ttk.Label(row3, text="Температура").pack(side=tk.LEFT)
        temperature_spin = ttk.Spinbox(row3, from_=2000, to=10000, textvariable=self.temperature_var, width=8, command=self.update_current)
        temperature_spin.pack(side=tk.LEFT, padx=(8, 0))
        temperature_spin.bind("<KeyRelease>", lambda _e: self.update_current())

        row4 = ttk.Frame(standard)
        row4.pack(fill=tk.X, pady=2)
        ttk.Label(row4, text="Оттенок").pack(side=tk.LEFT)
        tint_spin = ttk.Spinbox(row4, from_=-100, to=100, textvariable=self.tint_var, width=8, command=self.update_current)
        tint_spin.pack(side=tk.LEFT, padx=(8, 0))
        tint_spin.bind("<KeyRelease>", lambda _e: self.update_current())

        row5 = ttk.Frame(standard)
        row5.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(row5, text="Применить ко всем в папке", command=self.apply_look_to_folder).pack(side=tk.LEFT)

        right = ttk.Frame(body, width=410)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(12, 0))
        self.info_var = tk.StringVar(value="Папка не загружена")
        ttk.Label(right, textvariable=self.info_var, wraplength=380).pack(anchor=tk.W, pady=(0, 8))
        ttk.Label(right, text="Кадры").pack(anchor=tk.W)
        self.thumbs = ttk.Frame(right)
        self.thumbs.pack(fill=tk.Y)

    def _slider(self, parent: ttk.Frame, label: str, start: float, end: float, command) -> tk.DoubleVar:
        row = ttk.Frame(parent)
        row.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        ttk.Label(row, text=label).pack(anchor=tk.W)
        var = tk.DoubleVar()
        scale = ttk.Scale(row, from_=start, to=end, orient=tk.HORIZONTAL, variable=var, command=lambda _: command())
        scale.pack(fill=tk.X)
        return var

    def pick_folder(self) -> None:
        folder = filedialog.askdirectory(title="Выберите корневую папку")
        if folder:
            self.load_root(Path(folder))

    def load_from_entry(self) -> None:
        self.load_root(Path(self.drop_var.get().strip('" ')))

    def load_root(self, folder: Path) -> None:
        if not folder.exists() or not folder.is_dir():
            messagebox.showerror("AutoRAW", f"Папка не найдена:\n{folder}")
            return

        self.load_token += 1
        token = self.load_token
        self.loading_frames = False
        self.pending_folder = None
        self.set_progress(0, "Ищу папки с исходниками...")
        self.root_folder = folder
        self.drop_var.set(str(folder))
        for item in self.folder_tree.get_children():
            self.folder_tree.delete(item)
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
            messagebox.showerror("AutoRAW", "Не найдено папок с исходниками")
            return

        old_states = self.folder_states
        self.folder_states = {}
        for source_folder in found:
            previous = old_states.get(source_folder)
            self.folder_states[source_folder] = previous if previous else FolderState(path=source_folder)

        self.render_folder_tree()
        self.set_progress(100, f"Найдено папок: {len(found)} за {elapsed:.1f} сек. Выберите папку слева.")
        self.clear_frames_view("Выберите папку слева, чтобы загрузить ее превью")

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
        self.update_current()
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
            self.select_frame(0)

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
                frames.append(FrameState(path=path, frame=frame_id(path), image=img, crop_box=auto_crop(path, img, aspect)))
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
        self.select_frame(0)
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
                frames.append(FrameState(path=path, frame=frame_id(path), image=img, crop_box=auto_crop(path, img, aspect)))
            except Exception as exc:
                messagebox.showwarning("AutoRAW", f"Не удалось открыть {path.name}:\n{exc}")

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

    def render_thumbnails(self) -> None:
        for child in self.thumbs.winfo_children():
            child.destroy()

        self.thumb_photos = []
        for index, state in enumerate(self.current_frames()):
            card = ttk.Frame(self.thumbs)
            card.grid(row=index // 2, column=index % 2, padx=4, pady=4, sticky="n")
            checked = tk.BooleanVar(value=state.checked)
            check = ttk.Checkbutton(card, text=f"{state.frame} {state.path.name}", variable=checked)
            check.pack(anchor=tk.W)
            check.configure(command=lambda i=index, var=checked: self.toggle_frame(i, var.get()))

            if state.thumb_cache is None:
                thumb = render_frame(state, THUMB_SIZE)
                state.thumb_cache = apply_standard_look(
                    thumb,
                    contrast=state.contrast,
                    shadows=state.shadows,
                    temperature=state.temperature,
                    tint=state.tint,
                )
            preview = state.thumb_cache
            photo = ImageTk.PhotoImage(preview)
            self.thumb_photos.append(photo)
            button = ttk.Button(card, image=photo, command=lambda i=index: self.select_frame(i))
            button.pack()

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

    def select_frame(self, index: int) -> None:
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
            f"Папка: {folder_text}\n"
            f"Кадр {state.frame}: {state.path.name}\n"
            "Мышью двигайте товар, колесом меняйте масштаб."
        )
        self.preview.focus_set()
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
        state.offset_x = self.offset_x.get()
        state.offset_y = self.offset_y.get()
        state.zoom = self.zoom.get() or 1.0
        state.rotation = self.rotation.get()
        state.profile = self.profile_var.get() or STANDARD_PROFILE
        state.contrast = self._coerce_int(self.contrast_var, STANDARD_CONTRAST, -100, 100)
        state.shadows = self._coerce_int(self.shadows_var, STANDARD_SHADOWS, -100, 100)
        state.temperature = self._coerce_int(self.temperature_var, STANDARD_TEMPERATURE, 2000, 10000)
        state.tint = self._coerce_int(self.tint_var, STANDARD_TINT, -100, 100)
        state.thumb_cache = None
        self.render_preview()

    def render_preview(self) -> None:
        state = self.current()
        if not state:
            return

        img = render_frame(state, PREVIEW_SIZE)
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

    def drag_preview(self, event: tk.Event) -> None:
        if not self.drag_start:
            return
        start_x, start_y, base_x, base_y = self.drag_start
        scale_x = CANVAS_SIZE[0] / PREVIEW_SIZE[0]
        scale_y = CANVAS_SIZE[1] / PREVIEW_SIZE[1]
        self.offset_x.set(base_x + (event.x - start_x) * scale_x)
        self.offset_y.set(base_y + (event.y - start_y) * scale_y)
        self.update_current()

    def mousewheel_zoom(self, event: tk.Event) -> None:
        delta = 0.04 if event.delta > 0 else -0.04
        self.zoom.set(max(0.5, min(2.0, self.zoom.get() + delta)))
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
        self.update_current()
        if self.loading_frames:
            messagebox.showwarning("AutoRAW", "Дождитесь окончания загрузки превью")
            return
        checked_folders = [state.path for state in self.folder_states.values() if state.checked]
        if not checked_folders:
            messagebox.showerror("AutoRAW", "Нет отмеченных папок для экспорта")
            return

        self.load_token += 1
        token = self.load_token
        use_droplets = bool(self.use_droplet_var.get())
        self.set_progress(0, "Готовлю экспорт...")
        threading.Thread(target=self.export_worker, args=(token, checked_folders, use_droplets), daemon=True).start()

    def export_worker(self, token: int, checked_folders: list[Path], use_droplets: bool) -> None:
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
                        frames.append(FrameState(path=path, frame=frame_id(path), image=img, crop_box=auto_crop(path, img, aspect)))
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
                # Export from full-size source for maximum JPG quality while
                # preserving editor adjustments by scaling crop box.
                try:
                    export_image = open_preview(frame.path, max_side=None)
                except Exception:
                    export_image = frame.image

                export_crop = scale_box(frame.crop_box, frame.image.size, export_image.size)
                output = render_frame(frame, CANVAS_SIZE, source_image=export_image, crop_box=export_crop)
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
                    messagebox.showinfo("AutoRAW", msg)
            elif kind == "warning":
                _, token, text = event
                if token == self.load_token:
                    messagebox.showwarning("AutoRAW", text)
            elif kind == "error":
                _, token, text = event
                if token == self.load_token:
                    self.loading_frames = False
                    self.set_progress(0, "Ошибка")
                    messagebox.showerror("AutoRAW", text)

        self.after(100, self.process_worker_events)


def main() -> int:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    app = AutoRawGui(folder)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
