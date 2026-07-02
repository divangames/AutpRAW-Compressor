from __future__ import annotations

from pathlib import Path

from PIL import Image

from autoraw_crop import Box
from autoraw_gui import (
    EXPORT_STATE_FILE,
    FrameState,
    _format_stage_timings,
    _format_stage_timings_short,
    _has_export_checkpoint,
    _load_export_state,
    _save_export_state,
    export_name_for_frame,
    scale_crop_box,
)

from conftest import ROOT


def test_scale_crop_box_scales_preview_to_full_frame() -> None:
    preview_box = Box(100, 50, 500, 400)
    preview_size = (1200, 800)
    full_size = (6016, 4016)

    scaled = scale_crop_box(preview_box, preview_size, full_size)

    sx = full_size[0] / preview_size[0]
    sy = full_size[1] / preview_size[1]
    assert scaled.left == int(preview_box.left * sx)
    assert scaled.top == int(preview_box.top * sy)
    assert scaled.right >= int(preview_box.right * sx) - 1
    assert scaled.bottom >= int(preview_box.bottom * sy) - 1
    assert scaled.width > preview_box.width
    assert scaled.height > preview_box.height


def test_export_name_for_frame() -> None:
    frame = FrameState(
        path=Path("folder/IMG_03.jpg"),
        frame="03",
        image=Image.new("RGB", (10, 10)),
        crop_box=Box(0, 0, 10, 10),
    )
    assert export_name_for_frame(frame) == "3.jpg"


def test_format_stage_timings_outputs_only_nonzero_stages() -> None:
    lines = _format_stage_timings({"raw": 12.3, "crop": 0.0, "droplet": 4.5})
    assert lines == ["RAW: 12.3 сек", "Дроплеты: 4.5 сек"]
    assert _format_stage_timings_short({"raw": 12.3, "crop": 4.1, "droplet": 0.0}) == "R 12.3 · C 4.1"


def test_export_checkpoint_roundtrip(tmp_path: Path) -> None:
    folder = tmp_path / "shoot_A"
    output_dir = folder / folder.name
    output_dir.mkdir(parents=True)

    state = {
        "raw_outputs": {str((folder / "a.nef").resolve()).lower(): str(output_dir / "a.png")},
        "exported_outputs": ["1.jpg"],
        "droplet_outputs": [],
    }
    _save_export_state(output_dir, state)
    (output_dir / "1.jpg").write_bytes(b"jpg")
    (output_dir / "a.png").write_bytes(b"png")

    loaded = _load_export_state(output_dir)
    assert loaded["exported_outputs"] == ["1.jpg"]
    assert _has_export_checkpoint(folder)
    assert (output_dir / EXPORT_STATE_FILE).is_file()


def test_version_file_matches_module() -> None:
    from version import version_string

    version_text = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert version_text == version_string()
