from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from autoraw_gui import (
    ALL_FRAME_NUMBERS,
    LoadProfile,
    _frames_unambiguous_from_names,
    assign_frame_numbers,
    assign_frame_to_index,
    assign_frames_by_search,
    missing_frame_numbers,
)
from conftest import SEARCH_DIR


def _solid(path: Path, color: tuple[int, int, int]) -> tuple[Path, Image.Image]:
    img = Image.new("RGB", (400, 300), color)
    return path, img


def test_missing_frame_numbers_detects_gaps() -> None:
    assert missing_frame_numbers(["01", "02", "04", "05", "06", "08"]) == ["03", "07"]
    assert missing_frame_numbers(ALL_FRAME_NUMBERS) == []


def test_assign_frame_numbers_uses_search_for_incomplete_set() -> None:
    profile = LoadProfile(
        preview_max_side=1200,
        parallel_workers=1,
        skip_search_match_if_named=True,
        lazy_crop=True,
        fast_nef_read=True,
    )
    loaded = [
        _solid(Path("IMG_001.jpg"), (200, 0, 0)),
        _solid(Path("IMG_002.jpg"), (0, 200, 0)),
        _solid(Path("IMG_003.jpg"), (0, 0, 200)),
    ]
    assert _frames_unambiguous_from_names(loaded)
    assignments = assign_frame_numbers(loaded, profile)
    frames = [frame for _path, _img, frame, _score in assignments]
    assert frames != ["01", "02", "03"]


def test_assign_frame_numbers_uses_names_for_full_set() -> None:
    profile = LoadProfile(
        preview_max_side=1200,
        parallel_workers=1,
        skip_search_match_if_named=True,
        lazy_crop=True,
        fast_nef_read=True,
    )
    loaded = [_solid(Path(f"shoot_{index:02d}.jpg"), (index * 10, 0, 0)) for index in range(1, 9)]
    assignments = assign_frame_numbers(loaded, profile)
    frames = [frame for _path, _img, frame, _score in assignments]
    assert frames == [f"{index:02d}" for index in range(1, 9)]


@pytest.mark.skipif(not SEARCH_DIR.is_dir(), reason="search reference dir missing")
def test_assign_frames_by_search_maps_six_of_eight_references() -> None:
    """Six photos that match refs 01,02,04,05,06,08 must keep gaps 03 and 07."""
    ref_frames = ["01", "02", "04", "05", "06", "08"]
    loaded: list[tuple[Path, Image.Image]] = []
    for index, frame in enumerate(ref_frames):
        ref_path = SEARCH_DIR / f"{int(frame)}.jpg"
        if not ref_path.is_file():
            pytest.skip(f"missing reference {ref_path}")
        with Image.open(ref_path) as img:
            loaded.append((Path(f"wrong_name_{index}.jpg"), img.copy()))

    assignments = assign_frames_by_search(loaded)
    got = sorted(frame for _path, _img, frame, _score in assignments)
    assert got == sorted(ref_frames)
    assert missing_frame_numbers(got) == ["03", "07"]


@pytest.mark.skipif(not SEARCH_DIR.is_dir(), reason="search reference dir missing")
def test_assign_frames_by_search_does_not_fill_missing_slots() -> None:
    """Six arbitrary colors must not be forced into sequential 01..06."""
    colors = [
        (220, 20, 20),
        (20, 220, 20),
        (20, 20, 220),
        (220, 220, 20),
        (220, 20, 220),
        (20, 220, 220),
    ]
    loaded = [_solid(Path(f"random_{index}.jpg"), color) for index, color in enumerate(colors)]
    assignments = assign_frames_by_search(loaded)
    frames = sorted(frame for _path, _img, frame, _score in assignments if frame.isdigit())
    assert len(frames) == 6
    assert frames != [f"{index:02d}" for index in range(1, 7)]


def test_assign_frame_to_index_swaps_on_conflict() -> None:
    from autoraw_crop import Box
    from autoraw_gui import FrameState

    aspect = 4 / 3
    states = [
        FrameState(path=Path("a.jpg"), frame="03", image=Image.new("RGB", (100, 100)), crop_box=Box(0, 0, 100, 100)),
        FrameState(path=Path("b.jpg"), frame="06", image=Image.new("RGB", (100, 100)), crop_box=Box(0, 0, 100, 100)),
    ]
    other = assign_frame_to_index(states, 0, "06", aspect)
    assert other == 1
    assert states[0].frame == "06"
    assert states[1].frame == "03"
    assert states[0].match_score is None
    assert states[1].match_score is None
