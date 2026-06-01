"""Проверка и установка обновлений с GitVerse."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app_paths import app_root, resource_path
from version import VERSION, version_string

GITVERSE_OWNER = "delbraun"
GITVERSE_REPO = "AutoRAWCompressor"
RELEASES_PAGE = f"https://gitverse.ru/{GITVERSE_OWNER}/{GITVERSE_REPO}/releases"
API_RELEASES = f"https://api.gitverse.ru/repos/{GITVERSE_OWNER}/{GITVERSE_REPO}/releases"

ProgressCallback = Callable[[str, float, str], None]
# (stage, percent 0-100, detail text)


@dataclass
class UpdateInfo:
    version: str
    release_name: str
    download_url: str
    asset_name: str
    size: int


def _config_path() -> Path:
    return resource_path("ui_config.json")


def gitverse_token() -> str:
    token = os.environ.get("GITVERSE_TOKEN", "").strip()
    if token:
        return token
    try:
        cfg = json.loads(_config_path().read_text(encoding="utf-8"))
        return str(cfg.get("gitverse_token", "")).strip()
    except Exception:
        return ""


def _api_headers(token: str) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.gitverse.object+json;version=1",
        "User-Agent": "AutoRAWCompressor",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def parse_version(value: str) -> tuple[tuple[int, ...], str]:
    raw = value.strip().lstrip("vV")
    if not raw:
        return (0, 0, 0, 0), ""
    parts = raw.split(".")
    nums: list[int] = []
    codename = ""
    for i, part in enumerate(parts):
        if i < 4:
            digits = re.match(r"^(\d+)", part)
            nums.append(int(digits.group(1)) if digits else 0)
        else:
            codename = ".".join(parts[i:])
            break
    while len(nums) < 4:
        nums.append(0)
    if len(parts) == 5 and not codename and not parts[4].isdigit():
        codename = parts[4]
    return tuple(nums[:4]), codename


def is_newer_version(latest: str, current: str) -> bool:
    ln, _ = parse_version(latest)
    cn, _ = parse_version(current)
    return ln > cn


def _pick_zip_asset(release: dict) -> dict | None:
    assets = release.get("assets") or []
    zips = [a for a in assets if str(a.get("name", "")).lower().endswith(".zip")]
    if not zips:
        return None

    def score(asset: dict) -> tuple[int, int]:
        name = str(asset.get("name", "")).lower()
        pref = 2 if "autoraw" in name else 1 if "compressor" in name else 0
        return pref, int(asset.get("size") or 0)

    return max(zips, key=score)


def _version_from_release(release: dict, asset: dict | None) -> str:
    tag = str(release.get("tag_name") or "").strip().lstrip("vV")
    if tag and re.search(r"\d+\.\d+", tag):
        return tag

    if asset:
        name = str(asset.get("name", ""))
        m = re.search(
            r"AutoRAWCompressor[-_.]([\d.]+(?:\.[A-Za-z][\w]*)?)\.zip",
            name,
            re.IGNORECASE,
        )
        if m:
            return m.group(1)

    body = str(release.get("body") or release.get("description") or "")
    m = re.search(r"(\d+\.\d+\.\d+\.\d+(?:\.\w+)?)", body)
    if m:
        return m.group(1)

    return tag or str(release.get("name") or "unknown")


def fetch_latest_update(token: str | None = None) -> UpdateInfo | None:
    token = (token or gitverse_token()).strip()
    if not token:
        raise RuntimeError(
            "Не задан токен GitVerse.\n\n"
            "Добавьте в ui_config.json:\n"
            '  "gitverse_token": "ваш_токен"\n\n'
            "Или переменную окружения GITVERSE_TOKEN.\n"
            "Токен: GitVerse → Настройки → Управление токенами → Публичное API."
        )

    url = f"{API_RELEASES}?page=1&per_page=10"
    req = urllib.request.Request(url, headers=_api_headers(token))
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise RuntimeError("GitVerse: неверный или просроченный токен (401).") from exc
        if exc.code == 403:
            raise RuntimeError("GitVerse: доступ запрещён (403). Проверьте права токена.") from exc
        raise RuntimeError(f"GitVerse API: HTTP {exc.code}") from exc

    releases = data if isinstance(data, list) else data.get("releases") or data.get("items") or []
    if not releases:
        return None

    current = version_string()
    for release in releases:
        if release.get("draft"):
            continue
        asset = _pick_zip_asset(release)
        if not asset:
            continue
        latest_ver = _version_from_release(release, asset)
        if not is_newer_version(latest_ver, current):
            continue
        download_url = str(asset.get("browser_download_url") or asset.get("url") or "")
        if not download_url:
            continue
        return UpdateInfo(
            version=latest_ver,
            release_name=str(release.get("name") or latest_ver),
            download_url=download_url,
            asset_name=str(asset.get("name") or "update.zip"),
            size=int(asset.get("size") or 0),
        )
    return None


def can_self_update() -> tuple[bool, str]:
    root = app_root()
    if not getattr(sys, "frozen", False):
        return False, "Автоустановка доступна только в собранной версии (exe)."
    if "WindowsApps" in root.as_posix():
        return False, "Установка через MSIX не поддерживает автообновление файлов. Скачайте новый пакет вручную."
    probe = root / "_update_write_test.tmp"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError:
        return False, f"Нет прав на запись в папку приложения:\n{root}"
    return True, ""


def _format_bytes(n: int) -> str:
    if n <= 0:
        return "?"
    units = ["Б", "КБ", "МБ", "ГБ"]
    v = float(n)
    for unit in units:
        if v < 1024 or unit == units[-1]:
            if unit == "Б":
                return f"{int(v)} {unit}"
            return f"{v:.1f} {unit}"
        v /= 1024
    return f"{n} Б"


def download_file(
    url: str,
    dest: Path,
    token: str,
    on_progress: ProgressCallback | None = None,
    total_hint: int = 0,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = _api_headers(token)
    req = urllib.request.Request(url, headers=headers)

    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or total_hint or 0)
        read = 0
        chunk_size = 256 * 1024
        with dest.open("wb") as out:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out.write(chunk)
                read += len(chunk)
                if on_progress:
                    if total > 0:
                        pct = min(99.0, read * 100.0 / total)
                        left = max(0, total - read)
                        detail = (
                            f"{_format_bytes(read)} / {_format_bytes(total)} · "
                            f"осталось {_format_bytes(left)}"
                        )
                    else:
                        pct = 0.0
                        detail = f"Скачано {_format_bytes(read)}"
                    on_progress("download", pct, detail)


def _resolve_zip_root(extracted: Path) -> Path:
    entries = [p for p in extracted.iterdir() if p.name not in {"__MACOSX"}]
    if len(entries) == 1 and entries[0].is_dir():
        inner = entries[0]
        if (inner / "AutoRAW-GUI.exe").is_file():
            return inner
    if (extracted / "AutoRAW-GUI.exe").is_file():
        return extracted
    for child in extracted.rglob("AutoRAW-GUI.exe"):
        return child.parent
    raise RuntimeError("В архиве не найден AutoRAW-GUI.exe")


def extract_zip(zip_path: Path, dest_dir: Path, on_progress: ProgressCallback | None = None) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.infolist()
        total = len(members) or 1
        for i, member in enumerate(members, start=1):
            zf.extract(member, dest_dir)
            if on_progress:
                pct = i * 100.0 / total
                on_progress("extract", pct, f"Файлов: {i}/{total}")
    return _resolve_zip_root(dest_dir)


def _write_apply_script(*, stage_dir: Path, target_dir: Path, pid: int, exe_name: str) -> Path:
    script = target_dir / "_apply_update.bat"
    # ui_config.json и секреты не перезаписываем
    content = f"""@echo off
setlocal EnableExtensions
set PID={pid}
set STAGE={stage_dir}
set TARGET={target_dir}

:wait_app
tasklist /FI "PID eq %PID%" 2>nul | find "%PID%" >nul
if not errorlevel 1 (
    ping -n 2 127.0.0.1 >nul
    goto wait_app
)

if exist "%TARGET%\\zona\\data.dat" copy /Y "%TARGET%\\zona\\data.dat" "%TEMP%\\autoraw_data.dat.bak" >nul

robocopy "%STAGE%" "%TARGET%" /E /XD "_update_cache" /XF "ui_config.json" "_apply_update.bat" /IS /IT /R:5 /W:2 /NFL /NDL /NJH /NJS
if errorlevel 8 exit /b 1

if exist "%TEMP%\\autoraw_data.dat.bak" (
    if not exist "%TARGET%\\zona" mkdir "%TARGET%\\zona"
    copy /Y "%TEMP%\\autoraw_data.dat.bak" "%TARGET%\\zona\\data.dat" >nul
    del /f /q "%TEMP%\\autoraw_data.dat.bak" 2>nul
)
if exist "%TARGET%\\{exe_name}" (
    start "" /D "%TARGET%" "%TARGET%\\{exe_name}"
)

rd /s /q "{stage_dir.parent}" 2>nul
del /f /q "%~f0" 2>nul
exit /b 0
"""
    script.write_text(content, encoding="cp866")
    return script


def apply_update_and_restart(stage_dir: Path) -> None:
    target = app_root()
    exe_name = Path(sys.executable).name
    pid = os.getpid()
    script = _write_apply_script(
        stage_dir=stage_dir,
        target_dir=target,
        pid=pid,
        exe_name=exe_name,
    )
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        ["cmd", "/c", str(script)],
        cwd=str(target),
        creationflags=flags,
        close_fds=True,
    )
    sys.exit(0)


def run_update(
    info: UpdateInfo,
    on_progress: ProgressCallback | None = None,
    token: str | None = None,
) -> None:
    ok, reason = can_self_update()
    if not ok:
        raise RuntimeError(reason)

    token = (token or gitverse_token()).strip()
    cache = app_root() / "_update_cache"
    if cache.exists():
        shutil.rmtree(cache, ignore_errors=True)
    cache.mkdir(parents=True, exist_ok=True)

    zip_path = cache / info.asset_name
    extract_dir = cache / "extracted"
    stage_dir = cache / "stage"

    if on_progress:
        on_progress("download", 0, f"Скачиваем {info.asset_name}…")
    download_file(info.download_url, zip_path, token, on_progress, info.size)

    if on_progress:
        on_progress("extract", 0, "Распаковка архива…")
    root = extract_zip(zip_path, extract_dir, on_progress)

    if on_progress:
        on_progress("apply", 0, "Подготовка к установке…")
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    shutil.copytree(root, stage_dir)

    if on_progress:
        on_progress("apply", 100, "Перезапуск приложения…")
    apply_update_and_restart(stage_dir)
