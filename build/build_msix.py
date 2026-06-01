"""Сборка MSIX-пакета (Windows SDK: MakeAppx + SignTool)."""
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
sys.path.insert(0, str(ROOT / "build"))

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

MSIX_WORK = ROOT / "build" / "msix" / "work"
MSIX_PKG = MSIX_WORK / "package"
MSIX_ASSETS = MSIX_WORK / "assets"
ICON_SRC = ROOT / "assets" / "image" / "favicon.ico"

PACKAGE_NAME = "Delbraun.AutoRAWCompressor"
PUBLISHER = "CN=Delbraun"
PUBLISHER_DISPLAY = "Delbraun"
CERT_PFX = ROOT / "build" / "msix" / "Delbraun.pfx"
CERT_PASSWORD = "AutoRAW-MSIX"

PACKAGE_TARGET_MB = 99


def find_sdk_tool(tool_name: str) -> Path:
    """Ищет makeappx.exe / signtool.exe в Windows SDK."""
    candidates: list[Path] = []

    kits_root = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10"
    bin_root = kits_root / "bin"
    if bin_root.is_dir():
        version_dirs = sorted((p for p in bin_root.iterdir() if p.is_dir()), reverse=True)
        for ver_dir in version_dirs:
            for arch in ("x64", "x86", "arm64"):
                candidates.append(ver_dir / arch / f"{tool_name}.exe")

    ack = kits_root / "App Certification Kit" / f"{tool_name}.exe"
    candidates.append(ack)

    for path in candidates:
        if path.is_file():
            return path

    raise FileNotFoundError(
        f"{tool_name}.exe не найден (Windows SDK).\n"
        "Установите Windows 10/11 SDK:\n"
        "  winget install Microsoft.WindowsSDK.10.0.22621\n"
        "Или: https://developer.microsoft.com/windows/downloads/windows-sdk/"
    )


def prepare_logos() -> None:
    from PIL import Image, ImageOps

    if not ICON_SRC.is_file():
        raise FileNotFoundError(f"Icon not found: {ICON_SRC}")

    MSIX_ASSETS.mkdir(parents=True, exist_ok=True)
    src = Image.open(ICON_SRC).convert("RGBA")
    for name, size in (
        ("StoreLogo.png", 50),
        ("Square44x44Logo.png", 44),
        ("Square150x150Logo.png", 150),
    ):
        ImageOps.fit(src, (size, size), Image.Resampling.LANCZOS).save(MSIX_ASSETS / name, "PNG")


def write_appx_manifest() -> None:
    version = package_version()
    manifest = MSIX_PKG / "AppxManifest.xml"
    manifest.write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<Package
  xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
  xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
  xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
  IgnorableNamespaces="uap rescap">

  <Identity
    Name="{PACKAGE_NAME}"
    Publisher="{PUBLISHER}"
    Version="{version}.0" />

  <Properties>
    <DisplayName>{APP_NAME}</DisplayName>
    <PublisherDisplayName>{PUBLISHER_DISPLAY}</PublisherDisplayName>
    <Logo>Assets\\StoreLogo.png</Logo>
  </Properties>

  <Resources>
    <Resource Language="ru-ru" />
    <Resource Language="en-us" />
  </Resources>

  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.17763.0" MaxVersionTested="10.0.26100.0" />
  </Dependencies>

  <Applications>
    <Application Id="AutoRAWCompressor" Executable="AutoRAW-GUI.exe" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements
        DisplayName="{APP_NAME}"
        Description="Автокадрирование и экспорт фото кроссовок"
        BackgroundColor="#1E1E1E"
        Square150x150Logo="Assets\\Square150x150Logo.png"
        Square44x44Logo="Assets\\Square44x44Logo.png" />
    </Application>
  </Applications>

  <Capabilities>
    <rescap:Capability Name="runFullTrust" />
  </Capabilities>
</Package>
""",
        encoding="utf-8",
    )


def stage_package() -> None:
    if MSIX_WORK.exists():
        shutil.rmtree(MSIX_WORK)
    MSIX_PKG.mkdir(parents=True, exist_ok=True)

    shutil.copytree(DIST_DIR, MSIX_PKG, dirs_exist_ok=True)
    prepare_logos()
    assets_dest = MSIX_PKG / "Assets"
    assets_dest.mkdir(exist_ok=True)
    for png in MSIX_ASSETS.glob("*.png"):
        shutil.copy2(png, assets_dest / png.name)

    write_appx_manifest()


def ensure_signing_cert() -> None:
    if CERT_PFX.is_file():
        return

    CERT_PFX.parent.mkdir(parents=True, exist_ok=True)
    ps = f"""
$pwd = ConvertTo-SecureString -String '{CERT_PASSWORD}' -Force -AsPlainText
$cert = New-SelfSignedCertificate -Type Custom -Subject '{PUBLISHER}' `
  -KeyUsage DigitalSignature -FriendlyName 'AutoRAW MSIX' `
  -CertStoreLocation 'Cert:\\CurrentUser\\My' `
  -TextExtension @('2.5.29.37={{text}}1.3.6.1.5.5.7.3.3')
Export-PfxCertificate -Cert $cert -FilePath '{CERT_PFX}' -Password $pwd | Out-Null
Write-Host 'Created signing certificate:' '{CERT_PFX}'
"""
    print("Creating self-signed MSIX certificate...")
    subprocess.check_call(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        cwd=ROOT,
    )


def run_makeappx(makeappx: Path, output_msix: Path) -> None:
    if output_msix.exists():
        output_msix.unlink()
    cmd = [
        str(makeappx),
        "pack",
        "/d",
        str(MSIX_PKG),
        "/p",
        str(output_msix),
        "/o",
    ]
    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)


def run_sign(signtool: Path, output_msix: Path) -> None:
    ensure_signing_cert()
    cmd = [
        str(signtool),
        "sign",
        "/fd",
        "SHA256",
        "/f",
        str(CERT_PFX),
        "/p",
        CERT_PASSWORD,
        str(output_msix),
    ]
    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)


def report_package_size(path: Path) -> None:
    size_mb = path.stat().st_size / (1024 * 1024)
    print(f"MSIX size: {size_mb:.1f} MB (target <= {PACKAGE_TARGET_MB} MB)")
    if size_mb > PACKAGE_TARGET_MB:
        print(f"WARNING: MSIX exceeds {PACKAGE_TARGET_MB} MB.")


def build_msix(force_dist: bool = False, skip_sign: bool = False) -> Path:
    if force_dist:
        run_build_dist()
    ensure_dist()

    makeappx = find_sdk_tool("makeappx")
    print(f"MakeAppx: {makeappx}")

    PACKAGE_OUT.mkdir(parents=True, exist_ok=True)
    stage_package()

    slug = safe_version_slug()
    output_msix = PACKAGE_OUT / f"AutoRAWCompressor-{slug}.msix"
    run_makeappx(makeappx, output_msix)

    if not skip_sign:
        signtool = find_sdk_tool("signtool")
        print(f"SignTool: {signtool}")
        run_sign(signtool, output_msix)

    report_package_size(output_msix)
    write_release_notes(PACKAGE_OUT)
    print(f"\nMSIX ready: {output_msix}")
    if not skip_sign:
        print("First install: run build\\msix\\install_cert.bat as Administrator, then open the .msix file.")
    return output_msix


def main() -> int:
    parser = argparse.ArgumentParser(description="Build MSIX package for AutoRAW Compressor")
    parser.add_argument("--rebuild-dist", action="store_true", help="Force rebuild portable dist before MSIX.")
    parser.add_argument("--skip-sign", action="store_true", help="Skip signing (package will not install).")
    args = parser.parse_args()
    try:
        build_msix(force_dist=args.rebuild_dist, skip_sign=args.skip_sign)
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
