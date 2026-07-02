from __future__ import annotations

import pytest

from updater import is_newer_version, parse_version


def test_parse_version_splits_numbers_and_codename() -> None:
    nums, codename = parse_version("0.0.2.12.Alpha")
    assert nums == (0, 0, 2, 12)
    assert codename == "Alpha"


@pytest.mark.parametrize(
    ("latest", "current", "expected"),
    [
        ("0.0.2.13.Alpha", "0.0.2.12.Alpha", True),
        ("0.0.2.12.Alpha", "0.0.2.12.Alpha", False),
        ("0.0.1.99.Alpha", "0.0.2.00.Alpha", False),
        ("1.0.0.0.Alpha", "0.9.9.99.Alpha", True),
    ],
)
def test_is_newer_version(latest: str, current: str, expected: bool) -> None:
    assert is_newer_version(latest, current) is expected
