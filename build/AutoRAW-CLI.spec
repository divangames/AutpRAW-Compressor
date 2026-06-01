# -*- mode: python ; coding: utf-8 -*-
"""CLI: onefile AutoRAW-Crop.exe."""
from pathlib import Path

from PyInstaller.building.datastruct import TOC
from PyInstaller.utils.hooks import collect_submodules, collect_all

block_cipher = None

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"

_pil_hidden = ["PIL._tkinter_finder", *collect_submodules("PIL")]
_pil_datas, _pil_bins, _pil_extra_hidden = collect_all("PIL")
_numpy_datas, _numpy_bins, _numpy_hidden = collect_all("numpy")
_numpy_datas = [
    (src, dst)
    for src, dst in _numpy_datas
    if "\\tests\\" not in src and "/tests/" not in src and not src.endswith("tests")
]

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
    "distutils",
]

a = Analysis(
    [str(SRC / "autoraw_crop.py")],
    pathex=[str(SRC)],
    binaries=[*_pil_bins, *_numpy_bins],
    datas=[*_pil_datas, *_numpy_datas],
    hiddenimports=[*_pil_hidden, *_pil_extra_hidden, *_numpy_hidden],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

a.scripts = TOC([entry for entry in a.scripts if "pyi_rth_pkgres" not in entry[0]])

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="AutoRAW-Crop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
