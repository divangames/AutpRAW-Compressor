"""Проверка и установка обновлений с GitHub Releases."""
from __future__ import annotations

import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app_paths import app_root, ensure_ui_config, ui_config_path, user_config_dir
from version import version_string

GITHUB_OWNER = "divangames"
GITHUB_REPO = "AutpRAW-Compressor"
RELEASES_PAGE = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
API_RELEASES = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"

ProgressCallback = Callable[[str, float, str], None]
# (stage, percent 0-100, detail text)


@dataclass
class UpdateInfo:
    version: str
    release_name: str
    download_url: str
    asset_name: str
    size: int


def _builtin_read_token() -> str:
    try:
        from builtin_github_read_token import BUILTIN_GITHUB_READ_TOKEN

        return str(BUILTIN_GITHUB_READ_TOKEN or "").strip()
    except ImportError:
        return ""


def github_token_missing_message() -> str:
    ensure_ui_config()
    cfg = ui_config_path()
    return (
        "Не удалось скачать обновление.\n\n"
        "Для публичного репозитория токен обычно не нужен — проверьте интернет "
        f"или скачайте вручную:\n{RELEASES_PAGE}\n\n"
        "Для приватного репозитория задайте GITHUB_TOKEN при сборке "
        "или github_token в\n"
        f"{cfg}"
    )


def github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token
    ensure_ui_config()
    try:
        cfg = json.loads(ui_config_path().read_text(encoding="utf-8"))
        return str(cfg.get("github_token") or "").strip()
    except Exception:
        return ""


def github_download_token() -> str:
    """Токен для GitHub API/скачивания: пользовательский или встроенный из сборки."""
    return github_token() or _builtin_read_token()


def _api_headers(token: str) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "AutoRAWCompressor",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _is_transient_network_error(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return False
    msg = str(exc).lower()
    needles = (
        "unexpected_eof",
        "ssl",
        "timed out",
        "timeout",
        "connection reset",
        "connection was reset",
        "connection was aborted",
        "failed to establish",
        "could not connect",
        "10060",
        "10054",
        "connection refused",
        "handshake",
    )
    return any(needle in msg for needle in needles)


def _network_error_message() -> str:
    return (
        "Не удалось связаться с GitHub (ошибка SSL или сети).\n\n"
        "Проверьте интернет и повторите через минуту. "
        f"Обновление можно скачать вручную:\n{RELEASES_PAGE}"
    )


def _curl_exe() -> Path:
    return Path(r"C:\Windows\System32\curl.exe")


def _http_get_via_curl(url: str, headers: dict[str, str], timeout: int) -> bytes:
    curl = _curl_exe()
    if not curl.is_file():
        raise RuntimeError("curl.exe не найден")
    args = [
        str(curl),
        "-fsS",
        "--ssl-no-revoke",
        "--retry",
        "3",
        "--retry-delay",
        "2",
        "--max-time",
        str(max(5, timeout)),
    ]
    for key, value in headers.items():
        args.extend(["-H", f"{key}: {value}"])
    args.append(url)
    proc = subprocess.run(args, capture_output=True, timeout=timeout + 20)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or b"")[-500:].decode("utf-8", errors="replace")
        raise RuntimeError(tail)
    return proc.stdout


def _http_get_via_powershell(url: str, headers: dict[str, str], timeout: int) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("PowerShell недоступен")
    esc = lambda text: text.replace("'", "''")
    header_parts = [f"'{esc(key)}' = '{esc(value)}'" for key, value in headers.items()]
    headers_expr = "{" + "; ".join(header_parts) + "}" if header_parts else "@{}"
    ps = (
        f"$ProgressPreference='SilentlyContinue'; "
        f"$headers = {headers_expr}; "
        f"$r = Invoke-WebRequest -Uri '{esc(url)}' -Headers $headers "
        f"-TimeoutSec {max(5, timeout)} -UseBasicParsing; "
        f"[Console]::Out.Write($r.Content)"
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
        timeout=timeout + 25,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or b"")[-500:].decode("utf-8", errors="replace")
        raise RuntimeError(tail)
    if not proc.stdout:
        raise RuntimeError("Пустой ответ GitHub")
    return proc.stdout


def _http_get_bytes(
    url: str,
    headers: dict[str, str] | None = None,
    *,
    timeout: int = 30,
    retries: int = 4,
) -> bytes:
    """GET с повторами и fallback (curl/PowerShell) при сбоях SSL на Windows."""
    hdrs = dict(headers or {})
    hdrs.setdefault("User-Agent", "AutoRAWCompressor")
    last_err: Exception | None = None

    for attempt in range(retries):
        if attempt:
            time.sleep(min(1.5 * attempt, 6.0))
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
                return resp.read()
        except urllib.error.HTTPError:
            raise
        except Exception as exc:
            last_err = exc
            if not _is_transient_network_error(exc):
                raise

    if sys.platform == "win32":
        for func in (_http_get_via_curl, _http_get_via_powershell):
            try:
                return func(url, hdrs, timeout)
            except Exception as exc:
                last_err = exc

    raise RuntimeError(_network_error_message()) from last_err


def _package_asset_name(version: str) -> str:
    return f"AutoRAWCompressor-{version.replace(' ', '_')}.zip"


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


def _fetch_releases_json(token: str) -> list:
    url = f"{API_RELEASES}?per_page=10"
    headers = _api_headers(token)
    try:
        raw = _http_get_bytes(url, headers, timeout=20)
        data = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            if token:
                raise RuntimeError("GitHub: неверный или просроченный токен (401).") from exc
            raise RuntimeError(
                "GitHub: для проверки обновлений нужен токен (401). "
                "Задайте github_token в настройках или GITHUB_TOKEN."
            ) from exc
        if exc.code == 403:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            if "rate limit" in detail.lower():
                raise RuntimeError(
                    "GitHub: превышен лимит запросов (403). Повторите позже или задайте GITHUB_TOKEN."
                ) from exc
            raise RuntimeError("GitHub: доступ запрещён (403). Проверьте права токена.") from exc
        if exc.code == 404:
            raise RuntimeError(
                f"GitHub: репозиторий {GITHUB_OWNER}/{GITHUB_REPO} не найден (404)."
            ) from exc
        raise RuntimeError(f"GitHub API: HTTP {exc.code}") from exc
    return data if isinstance(data, list) else []


def fetch_latest_update(token: str | None = None) -> UpdateInfo | None:
    api_token = (token or github_download_token()).strip()
    try:
        releases = _fetch_releases_json(api_token)
    except RuntimeError as exc:
        if api_token and "401" in str(exc):
            releases = _fetch_releases_json("")
        else:
            raise
    if not releases:
        return None

    current = version_string()
    for release in releases:
        if release.get("draft"):
            continue
        asset = _pick_zip_asset(release)
        latest_ver = _version_from_release(release, asset)
        if not is_newer_version(latest_ver, current):
            continue
        pkg_name = _package_asset_name(latest_ver)
        if not asset:
            continue
        asset_name = str(asset.get("name") or pkg_name)
        asset_size = int(asset.get("size") or 0)
        download_url = str(asset.get("browser_download_url") or "")
        if not download_url:
            continue
        return UpdateInfo(
            version=latest_ver,
            release_name=str(release.get("name") or latest_ver),
            download_url=download_url,
            asset_name=asset_name,
            size=asset_size,
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


def _download_stream(
    resp: object,
    dest: Path,
    on_progress: ProgressCallback | None,
    total_hint: int,
) -> None:
    total = int(getattr(resp, "headers", {}).get("Content-Length") or total_hint or 0)  # type: ignore[union-attr]
    read = 0
    chunk_size = 256 * 1024
    with dest.open("wb") as out:
        while True:
            chunk = resp.read(chunk_size)  # type: ignore[union-attr]
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


def _download_headers(token: str) -> dict[str, str]:
    headers = {
        "Accept": "application/octet-stream",
        "User-Agent": "AutoRAWCompressor",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def download_file(
    url: str,
    dest: Path,
    token: str,
    on_progress: ProgressCallback | None = None,
    total_hint: int = 0,
) -> None:
    token = (token or github_download_token()).strip()
    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = _download_headers(token)

    last_http: urllib.error.HTTPError | None = None
    last_network: Exception | None = None
    for attempt in range(3):
        if attempt:
            time.sleep(min(1.5 * attempt, 4.0))
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=120, context=_ssl_context()) as resp:
                _download_stream(resp, dest, on_progress, total_hint)
            if on_progress:
                on_progress("download", 100.0, "Загрузка завершена")
            return
        except urllib.error.HTTPError as exc:
            last_http = exc
            if exc.code in (401, 403) and token:
                token = ""
                headers = _download_headers(token)
                continue
            if exc.code not in (401, 403):
                raise RuntimeError(f"Ошибка загрузки: HTTP {exc.code}") from exc
            break
        except Exception as exc:
            last_network = exc
            if not _is_transient_network_error(exc):
                raise RuntimeError(f"Ошибка загрузки: {exc}") from exc

    if sys.platform == "win32":
        curl = _curl_exe()
        if curl.is_file():
            try:
                if on_progress:
                    on_progress("download", 0.0, "Повтор через curl…")
                args = [
                    str(curl),
                    "-fSL",
                    "--ssl-no-revoke",
                    "--retry",
                    "3",
                    "--retry-delay",
                    "2",
                    "-o",
                    str(dest),
                ]
                if token:
                    args.extend(["-H", f"Authorization: Bearer {token}"])
                args.append(url)
                proc = subprocess.run(args, capture_output=True, text=True, timeout=900)
                if proc.returncode == 0:
                    if on_progress:
                        on_progress("download", 100.0, "Загрузка завершена")
                    return
            except Exception as exc:
                if last_http is not None:
                    raise RuntimeError(github_token_missing_message()) from exc
                if last_network is not None and _is_transient_network_error(last_network):
                    raise RuntimeError(_network_error_message()) from last_network
                raise

    if last_http is not None:
        if last_http.code in (401, 403):
            raise RuntimeError(github_token_missing_message()) from last_http
        raise RuntimeError(f"Ошибка загрузки: HTTP {last_http.code}") from last_http
    if last_network is not None:
        raise RuntimeError(_network_error_message()) from last_network
    raise RuntimeError("Не удалось скачать обновление.")


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
    script = user_config_dir() / "apply_update.bat"
    log_path = user_config_dir() / "apply_update.log"
    stage = str(stage_dir.resolve())
    target = str(target_dir.resolve())
    cache_dir = str((target_dir / "_update_cache").resolve())
    # ui_config.json и секреты не перезаписываем
    content = f"""@echo off
setlocal EnableExtensions
set "PID={pid}"
set "STAGE={stage}"
set "TARGET={target}"
set "LOG={log_path}"
set "CACHE={cache_dir}"
set "EXE={exe_name}"

echo [%date% %time%] update start PID=%PID% STAGE=%STAGE% TARGET=%TARGET%>>"%LOG%"

:wait_app
powershell -NoProfile -Command "exit([int]!!(Get-Process -Id {pid} -ErrorAction SilentlyContinue))" 2>nul
if %ERRORLEVEL% NEQ 0 (
    ping -n 2 127.0.0.1 >nul
    goto wait_app
)
echo [%date% %time%] app exited>>"%LOG%"
ping -n 4 127.0.0.1 >nul

if exist "%TARGET%\\zona\\data.dat" copy /Y "%TARGET%\\zona\\data.dat" "%TEMP%\\autoraw_data.dat.bak" >nul

set "TRY=0"
:copy_retry
set /a TRY+=1
echo [%date% %time%] robocopy try %TRY%>>"%LOG%"
robocopy "%STAGE%" "%TARGET%" /E /XD "_update_cache" /XF "ui_config.json" /IS /IT /R:8 /W:3 /NFL /NDL /NJH /NJS >>"%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo [%date% %time%] robocopy exit %RC%>>"%LOG%"
if %RC% GEQ 8 (
    if %TRY% LSS 5 (
        ping -n 3 127.0.0.1 >nul
        goto copy_retry
    )
    echo [%date% %time%] FAILED robocopy>>"%LOG%"
    exit /b %RC%
)

if exist "%TEMP%\\autoraw_data.dat.bak" (
    if not exist "%TARGET%\\zona" mkdir "%TARGET%\\zona"
    copy /Y "%TEMP%\\autoraw_data.dat.bak" "%TARGET%\\zona\\data.dat" >nul
    del /f /q "%TEMP%\\autoraw_data.dat.bak" 2>nul
)
if exist "%TARGET%\\%EXE%" (
    start "" /D "%TARGET%" "%TARGET%\\%EXE%"
    echo [%date% %time%] restarted>>"%LOG%"
) else (
    echo [%date% %time%] ERROR exe missing>>"%LOG%"
)

rd /s /q "%CACHE%" 2>nul
rd /s /q "%STAGE%" 2>nul
del /f /q "%~f0" 2>nul
exit /b 0
"""
    script.write_text(content, encoding="cp866")
    return script


def _launch_apply_script(script: Path, target: Path) -> None:
    """Запуск bat в отдельном процессе — не должен завершаться вместе с GUI при os._exit."""
    if sys.platform == "win32":
        try:
            os.startfile(script)  # type: ignore[attr-defined]
            return
        except OSError:
            pass
        flags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            | 0x01000000  # CREATE_BREAKAWAY_FROM_JOB
        )
        subprocess.Popen(
            ["cmd.exe", "/c", str(script)],
            cwd=str(target),
            creationflags=flags,
            close_fds=True,
        )
        return
    subprocess.Popen(["/bin/sh", str(script)], cwd=str(target), close_fds=True)


def apply_update_and_restart(stage_dir: Path) -> None:
    """Запускает фоновый bat и немедленно завершает процесс (иначе bat ждёт PID вечно)."""
    target = app_root()
    exe_name = Path(sys.executable).name
    pid = os.getpid()
    script = _write_apply_script(
        stage_dir=stage_dir,
        target_dir=target,
        pid=pid,
        exe_name=exe_name,
    )
    _launch_apply_script(script, target)
    # Дать cmd стартовать до выхода процесса (иначе дочерний bat может обрываться).
    time.sleep(0.8)
    # sys.exit() из потока загрузки не закрывает Tk — процесс остаётся, bat висит на :wait_app.
    os._exit(0)


def run_update(
    info: UpdateInfo,
    on_progress: ProgressCallback | None = None,
    token: str | None = None,
) -> None:
    ok, reason = can_self_update()
    if not ok:
        raise RuntimeError(reason)

    token = (token or github_download_token()).strip()
    cache = app_root() / "_update_cache"
    if cache.exists():
        shutil.rmtree(cache, ignore_errors=True)
    cache.mkdir(parents=True, exist_ok=True)

    zip_path = cache / info.asset_name
    extract_dir = cache / "extracted"

    if on_progress:
        on_progress("download", 0, f"Скачиваем {info.asset_name}…")
    download_file(info.download_url, zip_path, token, on_progress, info.size)

    if on_progress:
        on_progress("extract", 0, "Распаковка архива…")
    root = extract_zip(zip_path, extract_dir, on_progress)

    if on_progress:
        on_progress("apply", 0, "Подготовка к установке…")
    # Стадия вне папки exe — bat копирует оттуда; при сбое не мешает _update_cache.
    external_stage = user_config_dir() / "update_stage"
    if external_stage.exists():
        shutil.rmtree(external_stage, ignore_errors=True)
    shutil.copytree(root, external_stage)

    if on_progress:
        on_progress("apply", 100, "Перезапуск приложения…")
    apply_update_and_restart(external_stage)
