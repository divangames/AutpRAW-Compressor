"""ZIP portable-сборки для релиза на GitVerse."""
from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from version import version_string  # noqa: E402

DIST = ROOT / "dist" / "AutoRAWCompressor"
OUT = ROOT / "dist"


def ensure_dist() -> None:
    if not (DIST / "AutoRAW-GUI.exe").is_file():
        print("Dist not found — building…")
        subprocess.check_call([sys.executable, str(ROOT / "build" / "build_dist.py")], cwd=ROOT)


def build_zip() -> Path:
    ensure_dist()
    slug = version_string().replace(" ", "_")
    out = OUT / f"AutoRAWCompressor-{slug}.zip"
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(DIST.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(DIST).as_posix())
    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"Release zip: {out} ({size_mb:.1f} MB)")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Create release ZIP from dist/AutoRAWCompressor")
    parser.parse_args()
    try:
        build_zip()
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
