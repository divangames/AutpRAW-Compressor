# -*- mode: python ; coding: utf-8 -*-
"""GUI: onedir dist/AutoRAWCompressor. CLI собирается отдельно (onefile) в build_dist.py."""
from pathlib import Path

from PyInstaller.building.datastruct import TOC
from PyInstaller.utils.hooks import collect_submodules, collect_all

block_cipher = None

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"

# PIL: скрытые импорты
_pil_hidden = ["PIL._tkinter_finder", *collect_submodules("PIL")]

# numpy: collect_all захватывает Python-пакет, data-файлы И C-расширения (.pyd/.dll)
# Без этого numpy падает с "Importing the numpy C-extensions failed"
_numpy_datas, _numpy_bins, _numpy_hidden = collect_all("numpy")
_numpy_datas = [
    (src, dst)
    for src, dst in _numpy_datas
    if "\\tests\\" not in src and "/tests/" not in src and not src.endswith("tests")
]

_icon = ROOT / "assets" / "image" / "favicon.ico"
_app_datas = [(str(_icon), "assets/image")] if _icon.is_file() else []

# numba/llvmlite (~100 MB) не используются приложением — исключаем из дистрибутива.
_excludes = [
    "numba",
    "llvmlite",
    "scipy",
    "pandas",
    "matplotlib",
    "IPython",
    "pytest",
    "setuptools",
    "pkg_resources",
]

a = Analysis(
    [str(SRC / "autoraw_gui.py")],
    pathex=[str(SRC)],
    binaries=_numpy_bins,
    datas=[*_numpy_datas, *_app_datas],
    hiddenimports=[*_pil_hidden, *_numpy_hidden],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# PyInstaller всё равно добавляет pyi_rth_pkgres, хотя pkg_resources не нужен.
a.scripts = TOC([entry for entry in a.scripts if "pyi_rth_pkgres" not in entry[0]])

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AutoRAW-GUI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(_icon) if _icon.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AutoRAWCompressor",
)
