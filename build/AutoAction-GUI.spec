# -*- mode: python ; coding: utf-8 -*-
"""АвтоЭкшен: onefile AutoAction-GUI.exe (кладётся в dist/AutoRAWCompressor/AutoAction/)."""
from pathlib import Path

from PyInstaller.building.datastruct import TOC
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

ROOT = Path(SPECPATH).resolve().parent
AA = ROOT / "AutoAction"
_VERSION_INFO = ROOT / "build" / "version_info.txt"
_icon = ROOT / "assets" / "image" / "icon_AutoAction.ico"

_pil_hidden = ["PIL._tkinter_finder", *collect_submodules("PIL")]
_pil_datas, _pil_bins, _pil_extra_hidden = collect_all("PIL")

_excludes = [
    "numba",
    "llvmlite",
    "scipy",
    "pandas",
    "matplotlib",
    "numpy",
    "IPython",
    "pytest",
    "setuptools",
    "pkg_resources",
]

_assets = ROOT / "assets" / "image"
_aa_datas: list[tuple[str, str]] = []
for _name in ("icon_AutoAction.ico", "icon_AutoAction.png", "MSG_Good.png"):
    _p = _assets / _name
    if _p.is_file():
        _aa_datas.append((str(_p), "assets/image"))

a = Analysis(
    [str(AA / "autoaction_gui.py")],
    pathex=[str(AA)],
    binaries=_pil_bins,
    datas=[*_pil_datas, *_aa_datas],
    hiddenimports=[
        *_pil_hidden,
        *_pil_extra_hidden,
        "processor",
        "app_paths",
        "safe_dnd",
        "windnd",
        "win_chrome",
        "ui_theme",
        "ui_widgets",
        "ps_window",
        "banner_toast",
    ],
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
    name="AutoAction-GUI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(_icon) if _icon.is_file() else None,
    version=str(_VERSION_INFO) if _VERSION_INFO.is_file() else None,
)
