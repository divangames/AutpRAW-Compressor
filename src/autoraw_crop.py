from __future__ import annotations

import argparse
import json
import math
from io import BytesIO
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw

from app_paths import resource_path


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".nef", ".dng"}


@dataclass
class Box:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    def clamp(self, width: int, height: int) -> "Box":
        return Box(
            max(0, min(self.left, width - 1)),
            max(0, min(self.top, height - 1)),
            max(1, min(self.right, width)),
            max(1, min(self.bottom, height)),
        )

    def normalized(self, width: int, height: int) -> dict[str, float]:
        return {
            "left": self.left / width,
            "top": self.top / height,
            "right": self.right / width,
            "bottom": self.bottom / height,
        }


@dataclass
class CropResult:
    source: str
    preview_size: tuple[int, int]
    frame: str
    rule: str
    object_box: dict[str, float]
    crop_box: dict[str, float]
    confidence: float
    status: str


@dataclass(frozen=True)
class LayoutRule:
    name: str
    mode: str
    target_px: int
    x_px: int | None = None
    y_top_px: int | None = None
    y_bottom_px: int | None = None
    manual_only: bool = False
    expand_left: float = 0.0
    expand_top: float = 0.0
    expand_right: float = 0.0
    expand_bottom: float = 0.0
    combine_components: bool = False


CANVAS_SIZE = (1400, 1050)

LAYOUT_RULES = {
    "01": LayoutRule(
        "rules/1.jpg",
        "width",
        target_px=965,
        x_px=223,
        y_bottom_px=185,
        expand_left=0.15,
        expand_top=0.18,
        expand_right=0.45,
        expand_bottom=0.18,
    ),
    "02": LayoutRule("rules/2-3-4-8.jpg", "width", target_px=965, x_px=223, y_bottom_px=265),
    "03": LayoutRule(
        "rules/2-3-4-8.jpg",
        "width",
        target_px=965,
        x_px=223,
        y_bottom_px=265,
        expand_left=0.10,
        expand_top=0.12,
        expand_right=0.25,
        expand_bottom=0.12,
    ),
    "04": LayoutRule(
        "rules/2-3-4-8.jpg",
        "width",
        target_px=965,
        x_px=223,
        y_bottom_px=265,
        expand_left=0.20,
        expand_top=0.12,
        expand_right=0.35,
        expand_bottom=0.12,
    ),
    "05": LayoutRule("manual: insoles top view", "manual", target_px=0, manual_only=True),
    "06": LayoutRule("rules/6.jpg", "height", target_px=897, y_top_px=76, y_bottom_px=76, combine_components=True),
    "07": LayoutRule("manual: laces/tongues", "manual", target_px=0, manual_only=True),
    "08": LayoutRule("rules/2-3-4-8.jpg", "width", target_px=965, x_px=223, y_bottom_px=265),
}


def image_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        if root.suffix.lower() in IMAGE_EXTENSIONS:
            yield root
        return

    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            yield path


def extract_embedded_jpeg(path: Path, max_side: int = 1200) -> Image.Image | None:
    data = path.read_bytes()
    starts: list[int] = []
    offset = 0
    while True:
        start = data.find(b"\xff\xd8\xff", offset)
        if start == -1:
            break
        starts.append(start)
        offset = start + 3

    best_blob: bytes | None = None
    best_area = 0

    for start in starts:
        end = data.find(b"\xff\xd9", start)
        while end != -1:
            blob = data[start : end + 2]
            try:
                img = Image.open(BytesIO(blob))
                area = img.width * img.height
            except Exception:
                end = data.find(b"\xff\xd9", end + 2)
                continue

            if area > best_area:
                best_blob = blob
                best_area = area
            break

    if not best_blob:
        return None

    img = Image.open(BytesIO(best_blob))
    if max_side:
        img.draft("RGB", (max_side, max_side))
    img.load()
    img = img.convert("RGB")
    return img


def open_preview(path: Path, max_side: int = 1200) -> Image.Image:
    if path.suffix.lower() in {".nef", ".dng"}:
        embedded = extract_embedded_jpeg(path, max_side=max_side)
        if embedded:
            img = embedded
        else:
            img = Image.open(path)
            img.load()
            img = img.convert("RGB")
    else:
        img = Image.open(path)
        img.load()
        img = img.convert("RGB")

    if max_side and max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

    return img


def estimate_background(rgb: np.ndarray) -> np.ndarray:
    h, w, _ = rgb.shape
    band = max(8, min(h, w) // 8)
    samples = np.concatenate(
        [
            rgb[:band, :].reshape(-1, 3),
            rgb[: int(h * 0.75), :band].reshape(-1, 3),
            rgb[: int(h * 0.75), -band:].reshape(-1, 3),
        ],
        axis=0,
    )
    luminance = samples @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    samples = samples[luminance >= np.percentile(luminance, 60)]
    return np.median(samples, axis=0)


def clean_mask(mask: np.ndarray) -> np.ndarray:
    h, w = mask.shape
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    neighbors = np.zeros(mask.shape, dtype=np.uint8)

    for dy in range(3):
        for dx in range(3):
            neighbors += padded[dy : dy + h, dx : dx + w]

    mask = neighbors >= 4
    padded = np.pad(mask, 1, mode="edge")
    grown = np.zeros(mask.shape, dtype=bool)

    for dy in range(3):
        for dx in range(3):
            grown |= padded[dy : dy + h, dx : dx + w]

    return grown


def component_boxes(mask: np.ndarray) -> list[tuple[Box, int]]:
    h, w = mask.shape
    visited = np.zeros(mask.shape, dtype=bool)
    components: list[tuple[Box, int]] = []

    ys, xs = np.nonzero(mask)
    for start_y, start_x in zip(ys.tolist(), xs.tolist()):
        if visited[start_y, start_x]:
            continue

        stack = [(start_y, start_x)]
        visited[start_y, start_x] = True
        count = 0
        min_x = max_x = start_x
        min_y = max_y = start_y

        while stack:
            y, x = stack.pop()
            count += 1
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)

            for ny in (y - 1, y, y + 1):
                for nx in (x - 1, x, x + 1):
                    if ny == y and nx == x:
                        continue
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((ny, nx))

        components.append((Box(min_x, min_y, max_x + 1, max_y + 1), count))

    return components


def is_product_component(candidate: Box, count: int, width: int, height: int) -> bool:
    touches_left_right = candidate.left <= 1 and candidate.right >= width - 1
    touches_top_bottom = candidate.top <= 1 and candidate.bottom >= height - 1
    too_wide = candidate.width > width * 0.88
    too_tall = candidate.height > height * 0.86
    too_low_band = candidate.top > height * 0.78 and candidate.width > width * 0.45
    too_small = count < width * height * 0.0025

    return not (touches_left_right or touches_top_bottom or too_wide or too_tall or too_low_band or too_small)


def largest_component_box(mask: np.ndarray) -> tuple[Box | None, int]:
    h, w = mask.shape
    best_count = 0
    best_box: Box | None = None

    for candidate, count in component_boxes(mask):
        touches_left_right = candidate.left <= 1 and candidate.right >= w - 1
        too_wide = candidate.width > w * 0.88
        too_low_band = candidate.top > h * 0.78 and candidate.width > w * 0.45

        if touches_left_right or too_wide or too_low_band:
            continue

        if count > best_count:
            best_count = count
            best_box = candidate

    return best_box, best_count


def combined_component_box(mask: np.ndarray) -> tuple[Box | None, int]:
    h, w = mask.shape
    selected = [
        (box, count)
        for box, count in component_boxes(mask)
        if is_product_component(box, count, w, h)
    ]
    if not selected:
        return None, 0

    left = min(box.left for box, _ in selected)
    top = min(box.top for box, _ in selected)
    right = max(box.right for box, _ in selected)
    bottom = max(box.bottom for box, _ in selected)
    pixels = sum(count for _, count in selected)
    return Box(left, top, right, bottom), pixels


def mask_bounds(mask: np.ndarray) -> tuple[Box | None, int]:
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None, 0
    return Box(int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1), int(len(xs))


def clean_bounds_mask(mask: np.ndarray) -> np.ndarray:
    cleaned = mask.copy()
    cleaned[np.mean(cleaned, axis=1) > 0.65, :] = False
    cleaned[:, np.mean(cleaned, axis=0) > 0.65] = False
    return cleaned


def detect_object(img: Image.Image, combine_components: bool = False) -> tuple[Box | None, float]:
    rgb = np.asarray(img).astype(np.float32)
    bg = estimate_background(rgb)
    distance = np.linalg.norm(rgb - bg, axis=2)
    luminance = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

    threshold = max(20.0, float(np.percentile(distance, 88)) * 0.45)
    mask = distance > threshold

    # The shooting table/shadow often touches the bottom edge. Keep it from
    # becoming the detected object by requiring a meaningful color/luma change.
    dark_or_colored = (luminance < np.percentile(luminance, 72)) | (distance > threshold * 1.8)
    mask &= dark_or_colored

    mask[:3, :] = False
    mask[int(mask.shape[0] * 0.9) :, :] = False
    mask[:, :2] = False
    mask[:, -2:] = False
    mask = clean_mask(mask)

    if combine_components:
        box, pixels = combined_component_box(clean_bounds_mask(mask))
    else:
        box, pixels = largest_component_box(mask)

    if pixels < img.width * img.height * 0.015:
        fallback = clean_bounds_mask(mask)
        fallback_box, fallback_pixels = mask_bounds(fallback)
        if fallback_box and fallback_pixels > pixels:
            box, pixels = fallback_box, fallback_pixels

    if box is None:
        return None, 0.0

    area = img.width * img.height
    coverage = pixels / max(1, area)
    confidence = min(1.0, coverage * 8.0)
    return box, confidence


def expand_box(box: Box, image_size: tuple[int, int], rule: LayoutRule | None) -> Box:
    if not rule:
        return box

    left = box.left - box.width * rule.expand_left
    top = box.top - box.height * rule.expand_top
    right = box.right + box.width * rule.expand_right
    bottom = box.bottom + box.height * rule.expand_bottom

    return Box(
        int(math.floor(left)),
        int(math.floor(top)),
        int(math.ceil(right)),
        int(math.ceil(bottom)),
    ).clamp(*image_size)


def target_aspect(reference_dir: Path | None) -> float:
    if not reference_dir:
        return 4 / 3

    aspects: list[float] = []
    for path in image_files(reference_dir):
        try:
            with Image.open(path) as img:
                aspects.append(img.width / img.height)
        except Exception:
            continue

    if not aspects:
        return 4 / 3

    return float(np.median(aspects))


def frame_id(path: Path) -> str:
    digits = "".join(ch for ch in path.stem if ch.isdigit())
    if not digits:
        return path.stem
    return f"{int(digits):02d}"


def shift_inside(left: float, top: float, width: float, height: float, image_w: int, image_h: int) -> tuple[float, float]:
    if left < 0:
        left = 0
    if top < 0:
        top = 0
    if left + width > image_w:
        left = image_w - width
    if top + height > image_h:
        top = image_h - height
    return max(0.0, left), max(0.0, top)


def crop_from_rule(box: Box, image_size: tuple[int, int], aspect: float, rule: LayoutRule) -> Box:
    image_w, image_h = image_size
    canvas_w, canvas_h = CANVAS_SIZE

    if rule.mode == "width":
        scale = rule.target_px / max(1, box.width)
        crop_w = canvas_w / scale
        crop_h = crop_w / aspect
        object_left_on_canvas = rule.x_px if rule.x_px is not None else (canvas_w - rule.target_px) / 2
        left = box.left - object_left_on_canvas / scale

        if rule.y_bottom_px is not None:
            top = box.bottom - (canvas_h - rule.y_bottom_px) / scale
        else:
            top = ((box.top + box.bottom) / 2) - (canvas_h / 2) / scale

    elif rule.mode == "height":
        scale = rule.target_px / max(1, box.height)
        crop_h = canvas_h / scale
        crop_w = crop_h * aspect
        left = ((box.left + box.right) / 2) - (canvas_w / 2) / scale
        top_margin = rule.y_top_px if rule.y_top_px is not None else (canvas_h - rule.target_px) / 2
        top = box.top - top_margin / scale

    else:
        return crop_from_object(box, image_size, aspect, padding=0.11)

    if crop_w > image_w:
        crop_w = image_w
        crop_h = crop_w / aspect
    if crop_h > image_h:
        crop_h = image_h
        crop_w = crop_h * aspect

    left, top = shift_inside(left, top, crop_w, crop_h, image_w, image_h)
    return Box(
        int(math.floor(left)),
        int(math.floor(top)),
        int(math.ceil(left + crop_w)),
        int(math.ceil(top + crop_h)),
    ).clamp(image_w, image_h)


def crop_from_object(box: Box, image_size: tuple[int, int], aspect: float, padding: float) -> Box:
    width, height = image_size
    pad_x = box.width * padding
    pad_y = box.height * padding

    left = box.left - pad_x
    top = box.top - pad_y
    right = box.right + pad_x
    bottom = box.bottom + pad_y

    crop_w = right - left
    crop_h = bottom - top
    current_aspect = crop_w / max(1.0, crop_h)

    if current_aspect < aspect:
        new_w = crop_h * aspect
        delta = (new_w - crop_w) / 2
        left -= delta
        right += delta
    else:
        new_h = crop_w / aspect
        delta = (new_h - crop_h) / 2
        top -= delta
        bottom += delta

    if left < 0:
        right -= left
        left = 0
    if top < 0:
        bottom -= top
        top = 0
    if right > width:
        left -= right - width
        right = width
    if bottom > height:
        top -= bottom - height
        bottom = height

    return Box(
        int(math.floor(left)),
        int(math.floor(top)),
        int(math.ceil(right)),
        int(math.ceil(bottom)),
    ).clamp(width, height)


def draw_debug(img: Image.Image, object_box: Box | None, crop_box: Box | None) -> Image.Image:
    debug = img.copy()
    draw = ImageDraw.Draw(debug)

    if crop_box:
        draw.rectangle(
            [crop_box.left, crop_box.top, crop_box.right - 1, crop_box.bottom - 1],
            outline=(30, 144, 255),
            width=max(2, img.width // 240),
        )

    if object_box:
        draw.rectangle(
            [object_box.left, object_box.top, object_box.right - 1, object_box.bottom - 1],
            outline=(255, 80, 40),
            width=max(2, img.width // 300),
        )

    return debug


def save_layout_preview(img: Image.Image, crop_box: Box | None, output_path: Path) -> None:
    if not crop_box:
        img.copy().resize(CANVAS_SIZE, Image.Resampling.BICUBIC).save(output_path, quality=88)
        return

    cropped = img.crop((crop_box.left, crop_box.top, crop_box.right, crop_box.bottom))
    cropped = cropped.resize(CANVAS_SIZE, Image.Resampling.BICUBIC)
    cropped.save(output_path, quality=88)


def process_file(path: Path, output_dir: Path, aspect: float, padding: float) -> CropResult:
    img = open_preview(path)
    frame = frame_id(path)
    rule = LAYOUT_RULES.get(frame)
    object_box, confidence = detect_object(img, combine_components=bool(rule and rule.combine_components))
    layout_box = expand_box(object_box, img.size, rule) if object_box else None

    if rule and rule.manual_only:
        crop_box = None
        status = "manual_only"
    elif layout_box and rule:
        crop_box = crop_from_rule(layout_box, img.size, aspect, rule)
        status = "ok" if confidence >= 0.18 else "needs_review"
    else:
        crop_box = crop_from_object(object_box, img.size, aspect, padding) if object_box else None
        status = "ok" if crop_box and confidence >= 0.18 else "needs_review"

    object_norm = object_box.normalized(*img.size) if object_box else {}
    crop_norm = crop_box.normalized(*img.size) if crop_box else {}

    output_base = path.name
    preview_name = f"{output_base}.preview.jpg"
    debug_name = f"{output_base}.debug.jpg"
    layout_name = f"{output_base}.layout.jpg"

    img.save(output_dir / preview_name, quality=88)
    draw_debug(img, layout_box or object_box, crop_box).save(output_dir / debug_name, quality=90)
    save_layout_preview(img, crop_box, output_dir / layout_name)

    return CropResult(
        source=str(path),
        preview_size=img.size,
        frame=frame,
        rule=rule.name if rule else "auto padding",
        object_box=object_norm,
        crop_box=crop_norm,
        confidence=round(confidence, 4),
        status=status,
    )


def write_photoshop_jsx(results: list[CropResult], output_path: Path) -> None:
    payload = json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2)
    output_path.write_text(
        """#target photoshop

/*
AutoRAW crop plan.
Open a source file in Photoshop, then run applyNormalizedCrop(crop_box)
from the matching JSON record. The crop values are normalized, so they scale
to the real RAW document size after Camera Raw opens it.
*/

var AUTORAW_CROP_PLAN = """
        + payload
        + """;

function applyNormalizedCrop(crop) {
    var doc = app.activeDocument;
    var w = doc.width.as("px");
    var h = doc.height.as("px");
    doc.crop([
        UnitValue(crop.left * w, "px"),
        UnitValue(crop.top * h, "px"),
        UnitValue(crop.right * w, "px"),
        UnitValue(crop.bottom * h, "px")
    ]);
}
""",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto crop sneakers from RAW previews.")
    parser.add_argument("--input", default="test", help="Input file or directory.")
    parser.add_argument(
        "--reference",
        default=None,
        help="Reference JPG directory (default: <app>/reference/Sneakers).",
    )
    parser.add_argument("--output", default="output", help="Output directory.")
    parser.add_argument("--padding", type=float, default=0.11, help="Padding around detected product.")
    args = parser.parse_args()

    root = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    reference_dir = Path(args.reference) if args.reference else resource_path("reference", "Sneakers")
    aspect = target_aspect(reference_dir)
    results: list[CropResult] = []

    for path in image_files(root):
        try:
            result = process_file(path, output_dir, aspect, args.padding)
        except Exception as exc:
            result = CropResult(
                source=str(path),
                preview_size=(0, 0),
                object_box={},
                crop_box={},
                confidence=0.0,
                status=f"error: {type(exc).__name__}: {exc}",
            )
        results.append(result)
        print(f"{Path(result.source).name}: {result.status} confidence={result.confidence}")

    plan_path = output_dir / "crop_plan.json"
    plan_path.write_text(
        json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_photoshop_jsx(results, output_dir / "crop_plan.jsx")
    print(f"Saved {plan_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
