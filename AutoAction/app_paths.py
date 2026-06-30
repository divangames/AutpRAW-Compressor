"""Пути приложения АвтоЭкшен."""
from __future__ import annotations

import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_path(*parts: str) -> Path:
    """assets/image и др. — из _MEIPASS (onefile), рядом с exe или в корне репозитория."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidate = Path(meipass).joinpath(*parts)
            if candidate.exists():
                return candidate
    root = app_root()
    for base in (root, root.parent):
        candidate = base.joinpath(*parts)
        if candidate.exists():
            return candidate
    return root.parent.joinpath(*parts)


def droplets_root() -> Path:
    local = app_root() / "droplets"
    if local.is_dir():
        return local
    parent = app_root().parent / "droplets"
    if parent.is_dir():
        return parent
    return local


def droplets_main_dir() -> Path:
    """Основной проход: droplets/Main или корень droplets (совместимость)."""
    root = droplets_root()
    main = root / "Main"
    if main.is_dir() and any(main.glob("*.exe")):
        return main
    if any(root.glob("*.exe")):
        return root
    return main


def droplets_old_dir() -> Path:
    return droplets_root() / "Old"


def droplets_dir() -> Path:
    """Обратная совместимость."""
    return droplets_main_dir()
