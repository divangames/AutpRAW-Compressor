"""Создать или обновить релиз на GitHub и загрузить portable ZIP."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(BUILD))
sys.path.insert(0, str(SRC))

from installer_common import extract_version_changelog, safe_version_slug  # noqa: E402
from updater import (  # noqa: E402
    API_RELEASES,
    GITHUB_OWNER,
    GITHUB_REPO,
    _api_headers,
    github_token,
)
from version import version_string  # noqa: E402


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
        raise RuntimeError(f"GitHub API HTTP {exc.code}: {detail}") from exc


def _find_release_by_tag(token: str, tag_name: str) -> dict | None:
    url = f"{API_RELEASES}/tags/{tag_name}"
    try:
        data = _request("GET", url, token)
        return data if isinstance(data, dict) and data.get("id") else None
    except RuntimeError as exc:
        if "404" in str(exc):
            return None
        raise


def _delete_zip_assets(token: str, release_id: int) -> None:
    data = _request("GET", f"{API_RELEASES}/{release_id}", token)
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
        _request("DELETE", f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/assets/{asset_id}", token)


def _upload_release_asset(token: str, release_id: int, zip_path: Path) -> str:
    name = zip_path.name
    url = (
        f"https://uploads.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/"
        f"releases/{release_id}/assets?name={name}"
    )
    print(f"Uploading asset ({zip_path.stat().st_size / (1024 * 1024):.1f} MB)…")
    headers = _api_headers(token)
    headers["Content-Type"] = "application/octet-stream"
    req = urllib.request.Request(
        url,
        data=zip_path.read_bytes(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub asset upload HTTP {exc.code}: {detail}") from exc
    return str(data.get("browser_download_url") or "")


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish or update GitHub release ZIP")
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

    token = github_token().strip()
    if not token:
        print("ERROR: задайте github_token в ui_config.json или GITHUB_TOKEN")
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
                "body": body_text.strip(),
                "draft": False,
                "prerelease": True,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        _request("PATCH", f"{API_RELEASES}/{release_id}", token, data=payload, content_type="application/json")
        _delete_zip_assets(token, release_id)
        asset_url = _upload_release_asset(token, release_id, zip_path)
        html = existing.get("html_url") or f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tag/{tag_name}"
        print(f"Release updated: {html}")
        print(f"Asset: {asset_url}")
        return 0

    if existing is not None:
        print(f"Релиз {tag_name} уже существует. Используйте: python build\\publish_github_release.py --update")
        return 1

    payload = json.dumps(
        {
            "tag_name": tag_name,
            "target_commitish": "master",
            "name": version,
            "body": body_text.strip(),
            "draft": False,
            "prerelease": True,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    print(f"Creating release {tag_name}…")
    release = _request("POST", API_RELEASES, token, data=payload, content_type="application/json")
    release_id = release.get("id") if isinstance(release, dict) else None
    if not release_id:
        raise RuntimeError(f"Не получен id релиза: {release!r}")

    asset_url = _upload_release_asset(token, int(release_id), zip_path)
    html = (
        release.get("html_url")
        if isinstance(release, dict)
        else f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tag/{tag_name}"
    )
    print(f"Release published: {html}")
    print(f"Asset: {asset_url}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
