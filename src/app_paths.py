"""Корень приложения: рядом с exe в dist или корень репозитория при разработке."""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    return app_root().joinpath(*parts)


def user_config_dir() -> Path:
    """Постоянные настройки пользователя (не затираются при автообновлении exe)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    else:
        base = Path.home() / ".config"
    path = base / "AutoRAWCompressor"
    path.mkdir(parents=True, exist_ok=True)
    return path


def legacy_ui_config_path() -> Path:
    return app_root() / "ui_config.json"


def ui_config_path() -> Path:
    return user_config_dir() / "ui_config.json"


def _merge_config_dict(current: dict, other: dict) -> tuple[dict, bool]:
    merged = dict(current)
    changed = False
    for key in (
        "gitverse_token",
        "theme",
        "etalon",
        "user_name",
        "zona_chat_id",
        "zona_enabled",
    ):
        if not str(merged.get(key, "")).strip() and str(other.get(key, "")).strip():
            merged[key] = other[key]
            changed = True
    return merged, changed


def _write_config(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ensure_ui_config() -> Path:
    """Создать ui_config.json в профиле пользователя; перенести из папки exe при необходимости."""
    path = ui_config_path()
    legacy = legacy_ui_config_path()

    if path.is_file():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            current = {}
        if legacy.is_file():
            try:
                old = json.loads(legacy.read_text(encoding="utf-8"))
                merged, changed = _merge_config_dict(current, old)
                if changed:
                    _write_config(path, merged)
            except Exception:
                pass
        return path

    if legacy.is_file():
        try:
            shutil.copy2(legacy, path)
            return path
        except Exception:
            pass

    for candidate in (
        resource_path("ui_config.example.json"),
        Path(__file__).resolve().parent.parent / "ui_config.example.json",
    ):
        if candidate.is_file():
            try:
                shutil.copy2(candidate, path)
                return path
            except Exception:
                pass

    _write_config(
        path,
        {
            "theme": "system",
            "gitverse_token": "",
            "user_name": "Иван",
            "zona_chat_id": "",
            "zona_enabled": False,
        },
    )
    return path
