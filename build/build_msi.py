"""Сборка MSI-установщика (WiX Toolset v3: heat + candle + light)."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))

from build_msix import CERT_PASSWORD, CERT_PFX, ensure_signing_cert, find_sdk_tool  # noqa: E402
from installer_common import (  # noqa: E402
    APP_NAME,
    DIST_DIR,
    PACKAGE_OUT,
    ensure_dist,
    package_version,
    run_build_dist,
    safe_version_slug,
    write_release_notes,
)

MSI_WORK = ROOT / "build" / "msi" / "work"
UPGRADE_CODE = "C8F4E2A1-9B3D-4F6E-8A2C-1D5E7F9B4A6C"
INSTALLER_ICON = ROOT / "assets" / "image" / "icon_setup.ico"
INSTALLER_BANNER_TOP = ROOT / "assets" / "image" / "icon_setup.png"
INSTALLER_BANNER_SIDE = ROOT / "assets" / "image" / "installer_banner.png"
WIXUI_BANNER_SIZE = (493, 58)
WIXUI_DIALOG_SIZE = (493, 312)
WIX_LOC = Path(__file__).resolve().parent / "msi" / "Product_ru-ru.wxl"


def find_wix_bin() -> Path:
    candidates = [
        Path(r"C:\Program Files (x86)\WiX Toolset v3.14\bin"),
        Path(r"C:\Program Files (x86)\WiX Toolset v3.11\bin"),
        Path(r"C:\Program Files\WiX Toolset v3.14\bin"),
    ]
    for base in candidates:
        if (base / "candle.exe").is_file() and (base / "light.exe").is_file() and (base / "heat.exe").is_file():
            return base

    for name in ("candle", "candle.exe"):
        found = shutil.which(name)
        if found:
            base = Path(found).parent
            if (base / "light.exe").is_file() and (base / "heat.exe").is_file():
                return base

    raise FileNotFoundError(
        "WiX Toolset v3 не найден (heat.exe, candle.exe, light.exe).\n"
        "Установите WiX 3.14:\n"
        "  https://github.com/wixtoolset/wix3/releases\n"
        "  или: winget search wix"
    )


def _ascii_ui_assets_dir() -> Path:
    """Каталог UI-ресурсов только с ASCII-путём (WiX light не принимает кириллицу в SourceFile)."""
    target = Path(tempfile.gettempdir()) / "autoraw_msi_ui"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    return target


def prepare_installer_ui_assets(work_dir: Path) -> Path:
    """Готовит BMP и ICO для WixUI (баннер сверху, боковая панель, иконка msi)."""
    from PIL import Image, ImageOps

    assets_dir = _ascii_ui_assets_dir()
    work_dir.mkdir(parents=True, exist_ok=True)

    for src, label in (
        (INSTALLER_ICON, "icon_setup.ico"),
        (INSTALLER_BANNER_TOP, "icon_setup.png"),
        (INSTALLER_BANNER_SIDE, "installer_banner.png"),
    ):
        if not src.is_file():
            raise FileNotFoundError(f"Installer asset not found: {src} ({label})")

    shutil.copy2(INSTALLER_ICON, assets_dir / "icon_setup.ico")

    top = Image.open(INSTALLER_BANNER_TOP).convert("RGB")
    ImageOps.fit(top, WIXUI_BANNER_SIZE, Image.Resampling.LANCZOS).save(assets_dir / "banner.bmp")

    side = Image.open(INSTALLER_BANNER_SIDE).convert("RGB")
    ImageOps.fit(side, WIXUI_DIALOG_SIZE, Image.Resampling.LANCZOS).save(assets_dir / "dialog.bmp")

    return assets_dir


def write_product_wxs(work_dir: Path) -> Path:
    path = work_dir / "Product.wxs"
    path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Product
    Id="*"
    Name="$(var.ProductName)"
    Language="1049"
    Codepage="65001"
    Version="$(var.ProductVersion)"
    Manufacturer="Delbraun"
    UpgradeCode="{UPGRADE_CODE}">

    <Package
      InstallerVersion="500"
      Compressed="yes"
      InstallScope="perMachine"
      Platform="x64"
      Description="$(var.ProductName)"
      Comments="$(var.ProductName)" />

    <MajorUpgrade DowngradeErrorMessage="!(loc.DowngradeErrorMessage)" />
    <MediaTemplate EmbedCab="yes" />

    <Icon Id="SetupIcon.ico" SourceFile="$(var.UiAssetsDir)\\icon_setup.ico" />
    <Property Id="ARPPRODUCTICON" Value="SetupIcon.ico" />

    <Feature Id="MainFeature" Title="$(var.ProductName)" Level="1">
      <ComponentGroupRef Id="AppFiles" />
      <ComponentRef Id="StartMenuShortcut" />
    </Feature>

    <Directory Id="TARGETDIR" Name="SourceDir">
      <Directory Id="ProgramFiles64Folder">
        <Directory Id="CompanyFolder" Name="Delbraun">
          <Directory Id="INSTALLFOLDER" Name="AutoRAWCompressor" />
        </Directory>
      </Directory>
      <Directory Id="ProgramMenuFolder">
        <Directory Id="ApplicationProgramsFolder" Name="$(var.ProductName)" />
      </Directory>
    </Directory>

    <Component Id="StartMenuShortcut" Guid="*" Directory="ApplicationProgramsFolder" Win64="yes">
      <Shortcut
        Id="ApplicationStartMenuShortcut"
        Name="$(var.ProductName)"
        Description="!(loc.ShortcutDescription)"
        Target="[INSTALLFOLDER]AutoRAW-GUI.exe"
        WorkingDirectory="INSTALLFOLDER"
        Icon="SetupIcon.ico" />
      <RemoveFolder Id="CleanUpStartMenuFolder" Directory="ApplicationProgramsFolder" On="uninstall" />
      <RegistryValue
        Root="HKCU"
        Key="Software\\Delbraun\\AutoRAWCompressor"
        Name="installed"
        Type="integer"
        Value="1"
        KeyPath="yes" />
    </Component>

    <UIRef Id="WixUI_Minimal" />
    <WixVariable Id="WixUIBannerBmp" Value="$(var.UiAssetsDir)\\banner.bmp" />
    <WixVariable Id="WixUIDialogBmp" Value="$(var.UiAssetsDir)\\dialog.bmp" />
  </Product>
</Wix>
""",
        encoding="utf-8-sig",
    )
    return path


def run_heat(heat: Path, work_dir: Path) -> Path:
    out = work_dir / "AppFiles.wxs"
    if out.exists():
        out.unlink()
    cmd = [
        str(heat),
        "dir",
        str(DIST_DIR),
        "-cg",
        "AppFiles",
        "-gg",
        "-sfrag",
        "-srd",
        "-sreg",
        "-arch",
        "x64",
        "-dr",
        "INSTALLFOLDER",
        "-var",
        "var.SourceDir",
        "-out",
        str(out),
    ]
    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)
    return out


def run_candle(
    candle: Path,
    work_dir: Path,
    product_wxs: Path,
    app_files_wxs: Path,
    ui_assets_dir: Path,
) -> list[Path]:
    defines = [
        f"-dSourceDir={DIST_DIR}",
        f"-dProductName={APP_NAME}",
        f"-dProductVersion={package_version()}",
        f"-dUiAssetsDir={ui_assets_dir}",
    ]
    objs: list[Path] = []
    for wxs in (product_wxs, app_files_wxs):
        obj = work_dir / f"{wxs.stem}.wixobj"
        cmd = [str(candle), "-nologo", "-arch", "x64", *defines, "-out", str(obj), str(wxs)]
        print("Running:", " ".join(cmd))
        subprocess.check_call(cmd, cwd=ROOT)
        objs.append(obj)
    return objs


def run_light(light: Path, objs: list[Path], output_msi: Path) -> None:
    if output_msi.exists():
        output_msi.unlink()
    cmd = [
        str(light),
        "-nologo",
        "-sice:ICE61",
        "-ext",
        "WixUIExtension",
        "-cultures:ru-ru",
        "-loc",
        str(WIX_LOC),
        "-out",
        str(output_msi),
        *[str(obj) for obj in objs],
    ]
    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)


def _windows_short_path(path: Path) -> str | None:
    if sys.platform != "win32":
        return None
    import ctypes

    resolved = str(path.resolve())
    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetShortPathNameW(resolved, buffer, len(buffer))
    if length and buffer.value and Path(buffer.value).exists():
        return buffer.value
    return None


def _ascii_safe_path(path: Path, *, allow_copy: bool = True) -> Path:
    """SignTool ломается на путях с кириллицей."""
    resolved = path.resolve()
    if str(resolved).isascii():
        return resolved
    short = _windows_short_path(resolved)
    if short and str(short).isascii():
        return Path(short)
    if not allow_copy:
        return resolved
    suffix = resolved.suffix or ".bin"
    copy = Path(tempfile.gettempdir()) / f"autoraw_sign_{abs(hash(resolved)) & 0xFFFF}{suffix}"
    shutil.copy2(resolved, copy)
    return copy


def sign_msi(signtool: Path, output_msi: Path) -> None:
    if not CERT_PFX.is_file():
        ensure_signing_cert()
    if not CERT_PFX.is_file():
        raise FileNotFoundError(f"Certificate not found: {CERT_PFX}")

    pfx = _ascii_safe_path(CERT_PFX, allow_copy=True)
    target = _ascii_safe_path(output_msi, allow_copy=False)
    if not str(target).isascii():
        target = _ascii_safe_path(output_msi, allow_copy=True)
    cleanup: list[Path] = []
    if pfx != CERT_PFX.resolve():
        cleanup.append(pfx)
    if target != output_msi.resolve():
        cleanup.append(target)

    try:
        cmd = [
            str(signtool),
            "sign",
            "/fd",
            "SHA256",
            "/f",
            str(pfx),
            "/p",
            CERT_PASSWORD,
            str(target),
        ]
        print("Running:", " ".join(cmd))
        subprocess.check_call(cmd, cwd=ROOT)
        if target != output_msi.resolve():
            shutil.copy2(target, output_msi)
    finally:
        for path in cleanup:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def report_package_size(path: Path) -> None:
    size_mb = path.stat().st_size / (1024 * 1024)
    print(f"MSI size: {size_mb:.1f} MB")


def build_msi(force_dist: bool = False, skip_sign: bool = False) -> Path:
    if force_dist:
        run_build_dist()
    ensure_dist()

    wix_bin = find_wix_bin()
    print(f"WiX: {wix_bin}")

    if MSI_WORK.exists():
        shutil.rmtree(MSI_WORK)
    MSI_WORK.mkdir(parents=True, exist_ok=True)

    ui_assets_dir = prepare_installer_ui_assets(MSI_WORK)
    product_wxs = write_product_wxs(MSI_WORK)
    app_files_wxs = run_heat(wix_bin / "heat.exe", MSI_WORK)
    objs = run_candle(wix_bin / "candle.exe", MSI_WORK, product_wxs, app_files_wxs, ui_assets_dir)

    PACKAGE_OUT.mkdir(parents=True, exist_ok=True)
    slug = safe_version_slug()
    output_msi = PACKAGE_OUT / f"AutoRAWCompressor-{slug}.msi"
    run_light(wix_bin / "light.exe", objs, output_msi)

    signed = False
    if not skip_sign:
        try:
            signtool = find_sdk_tool("signtool")
            print(f"SignTool: {signtool}")
            sign_msi(signtool, output_msi)
            signed = True
        except (FileNotFoundError, subprocess.CalledProcessError, OSError) as exc:
            print(f"WARNING: MSI собран, но подпись не удалась: {exc}")

    report_package_size(output_msi)
    write_release_notes(PACKAGE_OUT)
    print(f"\nMSI ready: {output_msi}")
    if signed:
        print("Первый запуск: build\\msix\\install_cert.bat от администратора (тот же сертификат, что для MSIX).")
    elif not skip_sign:
        print("Установщик без подписи — Windows может показать предупреждение SmartScreen.")
        print("Повторите с --skip-sign или установите сертификат вручную.")
    return output_msi


def main() -> int:
    parser = argparse.ArgumentParser(description="Build MSI installer for AutoRAW Compressor")
    parser.add_argument("--rebuild-dist", action="store_true", help="Force rebuild portable dist before MSI.")
    parser.add_argument("--skip-sign", action="store_true", help="Skip signing (installer may warn in SmartScreen).")
    args = parser.parse_args()
    try:
        build_msi(force_dist=args.rebuild_dist, skip_sign=args.skip_sign)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: command failed with code {exc.returncode}")
        return exc.returncode or 1
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
