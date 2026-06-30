"""Общие функции для сборки установщиков (MSIX, MSI и др.)."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from version import APP_NAME, version_string  # noqa: E402

DIST_DIR = ROOT / "dist" / "AutoRAWCompressor"
CHANGELOG_SRC = ROOT / "CHANGELOG.md"
PACKAGE_OUT = ROOT / "dist"


def safe_version_slug() -> str:
    return version_string().replace(" ", "_")


def package_version() -> str:
    """Версия пакета X.Y.Z.W (без codename)."""
    parts = version_string().split(".")
    numeric = parts[:4]
    while len(numeric) < 4:
        numeric.append("0")
    return ".".join(numeric)


def extract_version_changelog() -> str:
    if not CHANGELOG_SRC.is_file():
        raise FileNotFoundError(f"CHANGELOG not found: {CHANGELOG_SRC}")

    text = CHANGELOG_SRC.read_text(encoding="utf-8")
    version = version_string()
    pattern = rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)"
    match = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL)
    if not match:
        raise ValueError(
            f"В CHANGELOG.md нет секции для версии [{version}]. "
            f"Добавьте заголовок: ## [{version}] — YYYY-MM-DD"
        )

    body = match.group(1).strip()
    return (
        f"{APP_NAME}\n"
        f"Версия: {version}\n"
        f"{'=' * 60}\n\n"
        f"Что нового в этой версии\n\n"
        f"{body}\n\n"
        f"{'=' * 60}\n"
        f"Полная история изменений — файл CHANGELOG.md в папке установки.\n"
    )


def write_release_notes(out_dir: Path | None = None) -> Path:
    target = out_dir or PACKAGE_OUT
    target.mkdir(parents=True, exist_ok=True)
    slug = safe_version_slug()
    notes_path = target / f"AutoRAWCompressor-{slug}-CHANGELOG.txt"
    notes_path.write_text(extract_version_changelog(), encoding="utf-8")
    print(f"Release notes: {notes_path}")
    return notes_path


def run_build_dist() -> None:
    print("Running portable build...")
    subprocess.check_call([sys.executable, str(ROOT / "build" / "build_dist.py")], cwd=ROOT)


def ensure_dist() -> None:
    if not (DIST_DIR / "AutoRAW-GUI.exe").exists():
        run_build_dist()
    if not (DIST_DIR / "droplets").is_dir():
        raise FileNotFoundError(f"Missing droplets in dist: {DIST_DIR / 'droplets'}")
    if not (DIST_DIR / "AutoAction" / "AutoAction-GUI.exe").is_file():
        raise FileNotFoundError(f"Missing AutoAction in dist: {DIST_DIR / 'AutoAction' / 'AutoAction-GUI.exe'}")
    if not (DIST_DIR / "CHANGELOG.md").is_file():
        raise FileNotFoundError(f"Missing CHANGELOG.md in dist: {DIST_DIR / 'CHANGELOG.md'}")
