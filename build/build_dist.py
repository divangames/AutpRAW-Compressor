"""Сборка portable-дистрибутива в dist/AutoRAWCompressor."""
from __future__ import annotations

import argparse
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

ASSET_DIRS = ("reference", "rules", "color", "assets", "droplets")
# Не копировать в dist — нужны только при сборке MSIX / разработке.
ASSET_IGNORE_NAMES = {"icon.psd", "setup.png", "installer_banner.png"}


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
    return built


def _ignore_assets(_dir: str, names: list[str]) -> set[str]:
    return {name for name in names if name in ASSET_IGNORE_NAMES or name.lower().endswith(".psd")}


def copy_assets(target: Path) -> None:
    for folder in ASSET_DIRS:
        source = ROOT / folder
        if not source.is_dir():
            print(f"Warning: asset folder missing: {source}")
            continue
        dest = target / folder
        if dest.exists():
            shutil.rmtree(dest)
        ignore = _ignore_assets if folder == "assets" else None
        shutil.copytree(source, dest, ignore=ignore)
        print(f"Copied {folder}/ -> {dest}")

    changelog = ROOT / "CHANGELOG.md"
    if changelog.is_file():
        shutil.copy2(changelog, target / "CHANGELOG.md")
        print(f"Copied CHANGELOG.md -> {target / 'CHANGELOG.md'}")
    else:
        print(f"Warning: missing {changelog}")


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
                "",
                "Рядом с exe должны лежать папки reference, rules, droplets.",
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

    if STAGING.exists():
        shutil.rmtree(STAGING)

    built = run_pyinstaller()
    publish(built)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
