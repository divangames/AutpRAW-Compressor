"""Создать или обновить релиз на GitVerse и загрузить portable ZIP."""
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
BUILD = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(BUILD))
sys.path.insert(0, str(SRC))

from installer_common import extract_version_changelog, safe_version_slug  # noqa: E402
from updater import GITVERSE_OWNER, GITVERSE_REPO, _api_headers, gitverse_token  # noqa: E402
from version import version_string  # noqa: E402

API = f"https://api.gitverse.ru/repos/{GITVERSE_OWNER}/{GITVERSE_REPO}/releases"


def _multipart_body(fields: dict[str, str], file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = f"----gitverse{uuid4().hex}"
    lines: list[bytes] = []
    for name, value in fields.items():
        lines.append(f"--{boundary}\r\n".encode())
        lines.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        lines.append(f"{value}\r\n".encode())
    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    lines.append(f"--{boundary}\r\n".encode())
    lines.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'.encode()
    )
    lines.append(f"Content-Type: {mime}\r\n\r\n".encode())
    lines.append(file_path.read_bytes())
    lines.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(lines)
    return body, f"multipart/form-data; boundary={boundary}"


def _request(
    method: str,
    url: str,
    token: str,
    data: bytes | None = None,
    content_type: str | None = None,
) -> dict | list:
    headers = dict(_api_headers(token))
    if data is not None:
        headers["Content-Type"] = content_type or "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
    else:
        req = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitVerse API HTTP {exc.code}: {detail}") from exc


def _find_release_by_tag(token: str, tag_name: str) -> dict | None:
    url = f"{API}/tags/{tag_name}"
    try:
        data = _request("GET", url, token)
        return data if isinstance(data, dict) and data.get("id") else None
    except RuntimeError as exc:
        if "404" in str(exc):
            return None
        raise


def _delete_zip_assets(token: str, release_id: int) -> None:
    data = _request("GET", f"{API}/{release_id}", token)
    if not isinstance(data, dict):
        return
    for asset in data.get("assets") or []:
        name = str(asset.get("name", "")).lower()
        if not name.endswith(".zip"):
            continue
        asset_id = asset.get("id")
        if asset_id is None:
            continue
        print(f"Removing old asset: {asset.get('name')}")
        _request("DELETE", f"{API}/{release_id}/assets/{asset_id}", token)


def _upload_zip(token: str, release_id: int, zip_path: Path) -> None:
    upload_url = f"{API}/{release_id}/assets?name={zip_path.name}"
    print(f"Uploading {zip_path.name} ({zip_path.stat().st_size / (1024 * 1024):.1f} MB)…")
    form_body, ctype = _multipart_body({}, "attachment", zip_path)
    _request("POST", upload_url, token, data=form_body, content_type=ctype)


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish or update GitVerse release ZIP")
    parser.add_argument(
        "--update",
        action="store_true",
        help="Обновить существующий релиз с тем же тегом (удалить старый ZIP, загрузить новый)",
    )
    parser.add_argument(
        "--create",
        action="store_true",
        help="Всегда создавать новый релиз (ошибка, если тег уже есть)",
    )
    args = parser.parse_args()

    token = gitverse_token().strip()
    if not token:
        print("ERROR: задайте gitverse_token в ui_config.json или GITVERSE_TOKEN")
        return 1

    version = version_string()
    tag_name = version
    zip_path = ROOT / "dist" / f"AutoRAWCompressor-{safe_version_slug()}.zip"
    if not zip_path.is_file():
        print(f"ERROR: нет ZIP: {zip_path}\nЗапустите: python build\\build_release_zip.py")
        return 1

    body_text = extract_version_changelog()
    existing = _find_release_by_tag(token, tag_name)
    do_update = args.update or (existing is not None and not args.create)

    if do_update:
        if existing is None:
            print(f"ERROR: релиз {tag_name} не найден. Запустите без --update для создания.")
            return 1
        release_id = int(existing["id"])
        print(f"Updating release {tag_name} (id={release_id})…")
        payload = json.dumps(
            {
                "name": version,
                "body": body_text,
                "draft": False,
                "prerelease": True,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        _request("PATCH", f"{API}/{release_id}", token, data=payload, content_type="application/json")
        _delete_zip_assets(token, release_id)
        _upload_zip(token, release_id, zip_path)
        html = existing.get("html_url") or f"https://gitverse.ru/{GITVERSE_OWNER}/{GITVERSE_REPO}/releases/tag/{tag_name}"
        print(f"Release updated: {html}")
        return 0

    if existing is not None:
        print(f"Релиз {tag_name} уже существует. Используйте: python build\\publish_gitverse_release.py --update")
        return 1

    payload = json.dumps(
        {
            "tag_name": tag_name,
            "target_commitish": "master",
            "name": version,
            "body": body_text,
            "draft": False,
            "prerelease": True,
            "is_authorized_only": False,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    print(f"Creating release {tag_name}…")
    release = _request("POST", API, token, data=payload, content_type="application/json")
    release_id = release.get("id") if isinstance(release, dict) else None
    if not release_id:
        raise RuntimeError(f"Не получен id релиза: {release!r}")

    _upload_zip(token, int(release_id), zip_path)
    html = (
        release.get("html_url")
        if isinstance(release, dict)
        else f"https://gitverse.ru/{GITVERSE_OWNER}/{GITVERSE_REPO}/releases/tag/{tag_name}"
    )
    print(f"Release published: {html}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
