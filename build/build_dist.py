"""Сборка portable-дистрибутива в dist/AutoRAWCompressor."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
from version import APP_NAME, VERSION, version_string  # noqa: E402

DIST_DIR = ROOT / "dist" / "AutoRAWCompressor"
WORK_DIR = ROOT / "build" / "pyinstaller"
STAGING = ROOT / "build" / "_staging"
SPEC = ROOT / "build" / "AutoRAW.spec"
CLI_SPEC = ROOT / "build" / "AutoRAW-CLI.spec"
AA_SPEC = ROOT / "build" / "AutoAction-GUI.spec"

ASSET_DIRS = ("reference", "rules", "color", "assets", "droplets")
# Не копировать в dist — нужны только при сборке MSIX / разработке.
ASSET_IGNORE_NAMES = {"icon.psd", "setup.png", "installer_banner.png", "icon_setup.ico", "icon_setup.png"}
BUILTIN_TOKEN_PATH = SRC / "builtin_github_read_token.py"


def write_builtin_github_read_token() -> None:
    """Вшивает read-only токен GitHub в dist (не коммитить файл с реальным токеном)."""
    token = os.environ.get("GITHUB_READ_TOKEN", "").strip()
    BUILTIN_TOKEN_PATH.write_text(
        "\n".join(
            [
                '"""Read-only токен для автообновления. Перезаписывается при сборке (GITHUB_READ_TOKEN)."""',
                "",
                f"BUILTIN_GITHUB_READ_TOKEN = {token!r}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    if token:
        print("builtin_github_read_token.py: GITHUB_READ_TOKEN записан (файл в .gitignore).")
    else:
        print(
            "NOTE: GITHUB_READ_TOKEN не задан — для публичного репозитория автообновление работает без токена."
        )


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller>=6.0"])


def run_pyinstaller() -> Path:
    STAGING.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        f"--distpath={STAGING}",
        f"--workpath={WORK_DIR}",
        str(SPEC),
    ]
    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)

    built = STAGING / "AutoRAWCompressor"
    if not (built / "AutoRAW-GUI.exe").exists():
        raise FileNotFoundError(f"Build output not found: {built}")

    cli_staging = STAGING / "cli_onefile"
    cli_staging.mkdir(parents=True, exist_ok=True)
    cli_cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        f"--distpath={cli_staging}",
        f"--workpath={WORK_DIR / 'cli'}",
        str(CLI_SPEC),
    ]
    print("Running CLI onefile:", " ".join(cli_cmd))
    subprocess.check_call(cli_cmd, cwd=ROOT)

    cli_exe = cli_staging / "AutoRAW-Crop.exe"
    if not cli_exe.exists():
        raise FileNotFoundError(f"CLI build not found: {cli_exe}")
    shutil.copy2(cli_exe, built / "AutoRAW-Crop.exe")

    aa_staging = STAGING / "aa_onefile"
    aa_staging.mkdir(parents=True, exist_ok=True)
    aa_cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        f"--distpath={aa_staging}",
        f"--workpath={WORK_DIR / 'autoaction'}",
        str(AA_SPEC),
    ]
    print("Running AutoAction onefile:", " ".join(aa_cmd))
    subprocess.check_call(aa_cmd, cwd=ROOT)

    aa_exe = aa_staging / "AutoAction-GUI.exe"
    if not aa_exe.exists():
        raise FileNotFoundError(f"AutoAction build not found: {aa_exe}")
    aa_dest = built / "AutoAction"
    aa_dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(aa_exe, aa_dest / "AutoAction-GUI.exe")
    print(f"Copied AutoAction-GUI.exe -> {aa_dest / 'AutoAction-GUI.exe'}")

    return built


def _ignore_assets(_dir: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        lower = name.lower()
        if (
            name in ASSET_IGNORE_NAMES
            or lower.endswith(".psd")
            or lower.endswith(".nef")
            or lower.endswith(".xmp")
            or name == "original"
        ):
            ignored.add(name)
    return ignored


def _ignore_reference(_dir: str, names: list[str]) -> set[str]:
    """Copy reference/; inside Sneakers/original keep only etalon/."""
    ignored: set[str] = set()
    for name in names:
        lower = name.lower()
        if (
            name in ASSET_IGNORE_NAMES
            or lower.endswith(".psd")
            or lower.endswith(".nef")
            or lower.endswith(".xmp")
        ):
            ignored.add(name)
    if Path(_dir).name == "original":
        for name in names:
            if name != "etalon":
                ignored.add(name)
    return ignored


def copy_assets(target: Path) -> None:
    for folder in ASSET_DIRS:
        source = ROOT / folder
        if not source.is_dir():
            print(f"Warning: asset folder missing: {source}")
            continue
        dest = target / folder
        if dest.exists():
            shutil.rmtree(dest)
        ignore = _ignore_reference if folder == "reference" else (
            _ignore_assets if folder == "assets" else None
        )
        shutil.copytree(source, dest, ignore=ignore)
        print(f"Copied {folder}/ -> {dest}")


ETALON_DIST_DIR = Path("reference") / "Sneakers" / "original" / "etalon"


def verify_etalon_assets(target: Path) -> None:
    """Эталоны GUI должны попасть в portable-сборку."""
    etalon_dir = target / ETALON_DIST_DIR
    if not etalon_dir.is_dir():
        raise FileNotFoundError(f"Etalon folder missing in dist: {etalon_dir}")
    images = sorted(
        f for f in etalon_dir.iterdir()
        if f.is_file() and f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
    )
    if not images:
        raise FileNotFoundError(f"No etalon images in dist: {etalon_dir}")
    print(f"Etalon OK: {len(images)} file(s) -> {etalon_dir}")

    changelog = ROOT / "CHANGELOG.md"
    if changelog.is_file():
        shutil.copy2(changelog, target / "CHANGELOG.md")
        print(f"Copied CHANGELOG.md -> {target / 'CHANGELOG.md'}")
    else:
        print(f"Warning: missing {changelog}")

    example_cfg = ROOT / "ui_config.example.json"
    dest_cfg = target / "ui_config.json"
    if example_cfg.is_file() and not dest_cfg.exists():
        shutil.copy2(example_cfg, dest_cfg)
        print(f"Copied ui_config.example.json -> {dest_cfg}")


def write_launchers(target: Path) -> None:
    (target / "run_gui.bat").write_text(
        "\n".join(
            [
                "@echo off",
                "setlocal",
                'cd /d "%~dp0"',
                'start "" "%~dp0AutoRAW-GUI.exe" %*',
                "",
            ]
        ),
        encoding="utf-8",
    )

    (target / "run_autocrop.bat").write_text(
        "\n".join(
            [
                "@echo off",
                "setlocal",
                'cd /d "%~dp0"',
                "set INPUT_DIR=test",
                "set REFERENCE_DIR=reference\\Sneakers",
                "set OUTPUT_DIR=output",
                f"echo {APP_NAME} {VERSION} (build)",
                "echo Input:     %INPUT_DIR%",
                "echo Reference: %REFERENCE_DIR%",
                "echo Output:    %OUTPUT_DIR%",
                "echo.",
                '"%~dp0AutoRAW-Crop.exe" --input "%INPUT_DIR%" --reference "%REFERENCE_DIR%" --output "%OUTPUT_DIR%"',
                "echo.",
                "if errorlevel 1 (echo Finished with errors.) else (echo Finished successfully.)",
                "pause",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (target / "run_autoaction.bat").write_text(
        "\n".join(
            [
                "@echo off",
                "setlocal",
                'cd /d "%~dp0"',
                'start "" "%~dp0AutoAction\\AutoAction-GUI.exe" %*',
                "",
            ]
        ),
        encoding="utf-8",
    )

    (target / "README.txt").write_text(
        "\n".join(
            [
                f"{APP_NAME} — portable build",
                f"Версия: {version_string()}",
                "",
                "Запуск:",
                "  AutoRAW-GUI.exe   — графический интерфейс",
                "  run_gui.bat       — то же (можно перетащить папку на bat)",
                "  AutoRAW-Crop.exe  — пакетная обработка (CLI)",
                "  run_autocrop.bat  — пример CLI (папки test / output)",
                "  AutoAction\\AutoAction-GUI.exe — АвтоЭкшен (дроплеты Photoshop)",
                "  run_autoaction.bat — то же (можно перетащить папку на bat)",
                "  Меню «Инструменты → АвтоЭкшен» в AutoRAW-GUI",
                "",
                "Рядом с exe должны лежать папки reference, rules, droplets.",
                "Эталоны GUI: reference\\Sneakers\\original\\etalon\\ (1.jpg … 8.jpg).",
                "CHANGELOG.md — история изменений (меню «Что изменилось»).",
                "Папку AutoRAWCompressor можно переносить на любой диск.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def publish(built: Path) -> None:
    if DIST_DIR.exists():
        try:
            shutil.rmtree(DIST_DIR)
        except PermissionError:
            print("Close AutoRAW-GUI.exe and retry build.")
            raise
    shutil.copytree(built, DIST_DIR)
    copy_assets(DIST_DIR)
    verify_etalon_assets(DIST_DIR)
    write_launchers(DIST_DIR)
    print(f"\nBuild complete: {DIST_DIR}")


def clean() -> None:
    for path in (DIST_DIR, STAGING, WORK_DIR):
        if path.exists():
            shutil.rmtree(path)
            print(f"Removed {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build AutoRAW Compressor into dist/")
    parser.add_argument("--clean-only", action="store_true", help="Remove build artifacts and dist.")
    args = parser.parse_args()

    if args.clean_only:
        clean()
        return 0

    for dep in ("PIL", "numpy"):
        try:
            __import__(dep)
        except ImportError:
            pkg = "Pillow" if dep == "PIL" else dep
            print(f"Installing runtime dependency: {pkg}")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

    ensure_pyinstaller()
    write_builtin_github_read_token()

    if STAGING.exists():
        shutil.rmtree(STAGING)

    built = run_pyinstaller()
    publish(built)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
