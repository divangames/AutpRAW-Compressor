from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from autoraw_crop import (
    Box,
    LAYOUT_RULES,
    crop_from_rule,
    detect_object,
    expand_box,
    frame_id,
    open_preview,
    process_file,
    shift_inside,
    target_aspect,
)

from conftest import REFERENCE_DIR


def test_frame_id_extracts_two_digits() -> None:
    assert frame_id(Path("IMG_01_preview.jpg")) == "01"
    assert frame_id(Path("shoot_8.NEF")) == "08"
    assert frame_id(Path("custom_name.jpg")) == "custom_name"


def test_box_clamp_keeps_positive_area() -> None:
    box = Box(-10, -5, 5000, 4000).clamp(1200, 900)
    assert box.left >= 0
    assert box.top >= 0
    assert box.right <= 1200
    assert box.bottom <= 900
    assert box.width > 0
    assert box.height > 0


def test_shift_inside_stays_within_image() -> None:
    left, top = shift_inside(-50, 20, 400, 300, 800, 600)
    assert left == 0
    assert top == 20
    left, top = shift_inside(500, 400, 400, 300, 800, 600)
    assert left == 400
    assert top == 300


def test_detect_object_on_synthetic_product() -> None:
    img = Image.new("RGB", (800, 600), (245, 245, 240))
    pixels = img.load()
    for y in range(120, 420):
        for x in range(220, 580):
            pixels[x, y] = (35, 38, 42)

    box, confidence = detect_object(img)
    assert box is not None
    assert confidence > 0.15
    assert 150 < box.left < 300
    assert 350 < box.right < 650
    assert box.bottom < int(img.height * 0.82)


def test_crop_from_rule_frame01_produces_target_aspect() -> None:
    rule = LAYOUT_RULES["01"]
    object_box = Box(300, 180, 700, 420)
    layout_box = expand_box(object_box, (1200, 900), rule)
    aspect = 4 / 3
    crop = crop_from_rule(layout_box, (1200, 900), aspect, rule, raw_box=object_box)

    assert crop.width > 0
    assert crop.height > 0
    assert abs((crop.width / crop.height) - aspect) < 0.02
    assert crop.left <= object_box.left
    assert crop.right >= object_box.right


@pytest.mark.skipif(not (REFERENCE_DIR / "1.jpg").is_file(), reason="reference image missing")
def test_reference_sneaker_detects_product() -> None:
    img = open_preview(REFERENCE_DIR / "1.jpg", max_side=1200)
    box, confidence = detect_object(img)
    assert box is not None
    assert confidence >= 0.18
    assert box.width > img.width * 0.2
    assert box.height > img.height * 0.15


@pytest.mark.skipif(not REFERENCE_DIR.is_dir(), reason="reference dir missing")
def test_target_aspect_from_reference_dir() -> None:
    aspect = target_aspect(REFERENCE_DIR)
    assert 1.2 < aspect < 1.5


@pytest.mark.skipif(not (REFERENCE_DIR / "1.jpg").is_file(), reason="reference image missing")
def test_process_file_writes_crop_result(tmp_path: Path) -> None:
    aspect = target_aspect(REFERENCE_DIR)
    result = process_file(REFERENCE_DIR / "1.jpg", tmp_path, aspect, padding=0.11)

    assert result.frame == "01"
    assert result.status in {"ok", "needs_review", "manual_only"}
    assert result.preview_size[0] > 0
    assert (tmp_path / f"{(REFERENCE_DIR / '1.jpg').name}.preview.jpg").is_file()
    assert result.crop_box
    assert 0 <= result.crop_box["left"] < result.crop_box["right"] <= 1.0
