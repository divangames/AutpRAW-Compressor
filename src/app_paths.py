"""Корень приложения: рядом с exe в dist или корень репозитория при разработке."""
from __future__ import annotations

import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    return app_root().joinpath(*parts)


def ui_config_path() -> Path:
    return resource_path("ui_config.json")


def ensure_ui_config() -> Path:
    """Создать ui_config.json из примера рядом с exe, если файла ещё нет."""
    path = ui_config_path()
    if path.is_file():
        return path
    for candidate in (
        resource_path("ui_config.example.json"),
        Path(__file__).resolve().parent.parent / "ui_config.example.json",
    ):
        if candidate.is_file():
            path.write_text(candidate.read_text(encoding="utf-8"), encoding="utf-8")
            return path
    path.write_text(
        '{\n  "theme": "system",\n  "gitverse_token": "",\n  "user_name": "Иван"\n}\n',
        encoding="utf-8",
    )
    return path
