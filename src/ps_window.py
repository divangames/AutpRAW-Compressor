"""Запуск дроплетов Adobe Photoshop как subprocess."""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_TIMEOUT_S = 900.0
_STABLE_QUIET_S = 1.0
_POLL_INTERVAL_S = 0.2


@dataclass
class _ProcResult:
    returncode: int
    stdout: str
    stderr: str


def wait_for_output_stable(
    path: Path,
    before_stat: os.stat_result,
    *,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    stable_quiet_s: float = _STABLE_QUIET_S,
    no_change_grace_s: float = 5.0,
    poll_interval_s: float = _POLL_INTERVAL_S,
) -> bool:
    """Ждём, пока Photoshop закончит перезапись файла (mtime/size стабильны)."""
    deadline = time.monotonic() + timeout_s
    started = time.monotonic()
    stable_since: float | None = None
    last_key: tuple[int, int] | None = None
    saw_change = False

    while time.monotonic() < deadline:
        if not path.is_file():
            stable_since = None
            last_key = None
            time.sleep(poll_interval_s)
            continue

        st = path.stat()
        key = (st.st_mtime_ns, st.st_size)
        changed = (
            st.st_mtime_ns != before_stat.st_mtime_ns
            or st.st_size != before_stat.st_size
        )

        if changed:
            saw_change = True
            if key == last_key:
                if stable_since is None:
                    stable_since = time.monotonic()
                elif time.monotonic() - stable_since >= stable_quiet_s:
                    return True
            else:
                stable_since = None
        elif not saw_change and time.monotonic() - started >= no_change_grace_s:
            return st.st_size > 0

        last_key = key
        time.sleep(poll_interval_s)

    return path.is_file() and path.stat().st_size > 0


def run_droplet_subprocess(
    args: list[str],
    *,
    capture_output: bool = False,
    text: bool = True,
    encoding: str = "utf-8",
    errors: str = "replace",
    poll_interval: float = _POLL_INTERVAL_S,
    timeout_s: float | None = _DEFAULT_TIMEOUT_S,
) -> _ProcResult:
    """Запуск дроплета и ожидание завершения.

    По умолчанию stdout/stderr не перехватываются — иначе Photoshop-дроплеты
    на Windows часто зависают на заполненном pipe после первого файла.
    """
    del poll_interval
    kwargs: dict = {}
    if capture_output:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
        if text:
            kwargs["text"] = True
            kwargs["encoding"] = encoding
            kwargs["errors"] = errors
    else:
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL

    proc = subprocess.Popen(args, **kwargs)
    try:
        if capture_output:
            stdout, stderr = proc.communicate(timeout=timeout_s)
        elif timeout_s is None:
            proc.wait()
            stdout, stderr = "", ""
        else:
            proc.wait(timeout=timeout_s)
            stdout, stderr = "", ""
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return _ProcResult(returncode=-1, stdout="", stderr="timeout")
    except Exception:
        proc.kill()
        proc.communicate()
        raise

    return _ProcResult(
        returncode=proc.returncode or 0,
        stdout=stdout or "",
        stderr=stderr or "",
    )
