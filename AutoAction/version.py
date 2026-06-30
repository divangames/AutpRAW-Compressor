"""Версия АвтоЭкшен — синхронизируется с корневым VERSION / src/version.py."""
from __future__ import annotations

import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_version() -> str:
    vfile = _repo_root() / "VERSION"
    if vfile.is_file():
        text = vfile.read_text(encoding="utf-8").strip()
        if text:
            return text
    src = _repo_root() / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        from version import VERSION as parent_version  # type: ignore[import-not-found]

        return parent_version
    except Exception:
        return "0.0.2.00.Alpha"


APP_NAME = "АвтоЭкшен"
VERSION = _load_version()
APP_TITLE = f"{APP_NAME} — {VERSION}"
