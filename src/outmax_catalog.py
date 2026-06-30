"""Каталоги товаров: онлайн-парсеры (приоритет) и локальная база."""
from __future__ import annotations

import csv
import json
import re
import threading
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO, StringIO
from pathlib import Path
from typing import Callable

from app_paths import user_config_dir

DEFAULT_PARSER_URLS = ["https://outmaxshop.com/yml/all_new.yml"]
OUTMAX_YML_URL = DEFAULT_PARSER_URLS[0]
_USER_AGENT = "Mozilla/5.0 (compatible; AutoRAW/1.0)"
_CACHE_FILE = "outmax_catalog.json"
_fetch_lock = threading.Lock()

_ARTICLE_KEYS = ("id", "артикул", "article", "sku", "code", "vendorcode", "код")
_TITLE_KEYS = ("name", "название", "title", "наименование", "товар")
_VENDOR_KEYS = ("vendor", "бренд", "brand", "производитель")
_MODEL_KEYS = ("model", "модель")


@dataclass
class ProductCatalog:
    parser_date: str = ""
    parser_fetched_at: str = ""
    parser_count: int = 0
    parser_titles: dict[str, str] = field(default_factory=dict)
    local_updated_at: str = ""
    local_updated_by: str = ""
    local_count: int = 0
    local_titles: dict[str, str] = field(default_factory=dict)

    @property
    def total_lookup_count(self) -> int:
        return len(self.all_titles())

    def all_titles(self) -> dict[str, str]:
        merged = dict(self.local_titles)
        merged.update(self.parser_titles)
        return merged

    def lookup(self, article: str) -> str | None:
        article = article.strip()
        if not article:
            return None
        if article in self.parser_titles:
            return self.parser_titles[article]
        return self.local_titles.get(article)


# Backward-compatible alias
OutmaxCatalog = ProductCatalog


def catalog_cache_path() -> Path:
    return user_config_dir() / _CACHE_FILE


def default_parser_urls() -> list[str]:
    return list(DEFAULT_PARSER_URLS)


def normalize_parser_urls(urls: list[str] | None) -> list[str]:
    if not urls:
        return default_parser_urls()
    cleaned = [str(u).strip() for u in urls if str(u).strip()]
    return cleaned or default_parser_urls()


def _now_str() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M")


def _norm_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _pick_column(headers: list[str], keys: tuple[str, ...]) -> int | None:
    norm = {_norm_key(h): i for i, h in enumerate(headers)}
    for key in keys:
        idx = norm.get(_norm_key(key))
        if idx is not None:
            return idx
    return None


def _format_vendor_model(vendor: str, model: str, name: str) -> str:
    vendor = vendor.strip()
    model = model.strip()
    if vendor and model:
        return f"{vendor.upper()} {model}"
    return name.strip()


def _format_yml_title(offer: ET.Element) -> str:
    vendor = (offer.findtext("vendor") or "").strip()
    model = (offer.findtext("model") or "").strip()
    name = (offer.findtext("name") or "").strip()
    return _format_vendor_model(vendor, model, name)


def _parse_yml_bytes(data: bytes) -> tuple[dict[str, str], str]:
    root = ET.fromstring(data)
    catalog_date = (root.get("date") or "").strip()
    titles: dict[str, str] = {}
    for offer in root.findall(".//offer"):
        oid = (offer.get("id") or "").strip()
        if not oid:
            continue
        title = _format_yml_title(offer)
        if title:
            titles[oid] = title
    return titles, catalog_date


def _parse_table_rows(headers: list[str], body: list[list[str]]) -> dict[str, str]:
    article_idx = _pick_column(headers, _ARTICLE_KEYS)
    title_idx = _pick_column(headers, _TITLE_KEYS)
    vendor_idx = _pick_column(headers, _VENDOR_KEYS)
    model_idx = _pick_column(headers, _MODEL_KEYS)
    titles: dict[str, str] = {}
    for row in body:
        if not row:
            continue
        if article_idx is None:
            if len(row) < 2:
                continue
            article = str(row[0]).strip()
            title = str(row[1]).strip()
        else:
            article = str(row[article_idx]).strip() if article_idx < len(row) else ""
            vendor = str(row[vendor_idx]).strip() if vendor_idx is not None and vendor_idx < len(row) else ""
            model = str(row[model_idx]).strip() if model_idx is not None and model_idx < len(row) else ""
            name = str(row[title_idx]).strip() if title_idx is not None and title_idx < len(row) else ""
            title = _format_vendor_model(vendor, model, name)
        if article and title:
            titles[article] = title
    return titles


def _parse_csv_text(text: str) -> dict[str, str]:
    sample = text[:4096]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.reader(StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return {}
    headers = [str(h).strip() for h in rows[0]]
    data_rows = rows[1:] if len(rows) > 1 else []
    return _parse_table_rows(headers, data_rows)


def _xlsx_col_ref(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    value = 0
    for ch in letters.upper():
        value = value * 26 + (ord(ch) - ord("A") + 1)
    return max(0, value - 1)


def _parse_xlsx_bytes(data: bytes) -> dict[str, str]:
    with zipfile.ZipFile(BytesIO(data)) as zf:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            ss_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            for si in ss_root.findall(".//m:si", ns):
                parts = [t.text or "" for t in si.findall(".//m:t", ns)]
                shared.append("".join(parts))

        sheet_name = next((n for n in zf.namelist() if n.startswith("xl/worksheets/sheet")), "")
        if not sheet_name:
            return {}
        sheet = ET.fromstring(zf.read(sheet_name))
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rows_map: dict[int, dict[int, str]] = {}
        for cell in sheet.findall(".//m:c", ns):
            ref = cell.get("r") or ""
            col = _xlsx_col_ref(ref)
            row_num = int("".join(ch for ch in ref if ch.isdigit()) or "0")
            value = ""
            cell_type = cell.get("t")
            v = cell.find("m:v", ns)
            if v is not None and v.text is not None:
                if cell_type == "s":
                    idx = int(v.text)
                    value = shared[idx] if 0 <= idx < len(shared) else ""
                else:
                    value = v.text
            elif cell.find("m:is", ns) is not None:
                value = "".join(t.text or "" for t in cell.findall(".//m:t", ns))
            rows_map.setdefault(row_num, {})[col] = value.strip()

        if not rows_map:
            return {}
        ordered_rows = [rows_map[k] for k in sorted(rows_map)]
        max_col = max((max(r) for r in ordered_rows if r), default=0)
        table: list[list[str]] = []
        for row in ordered_rows:
            table.append([row.get(i, "") for i in range(max_col + 1)])
        if not table:
            return {}
        return _parse_table_rows(table[0], table[1:])


def parse_product_file(path: Path) -> dict[str, str]:
    suffix = path.suffix.lower()
    data = path.read_bytes()
    if suffix in {".yml", ".xml"}:
        titles, _ = _parse_yml_bytes(data)
        return titles
    if suffix in {".csv", ".tsv", ".txt"}:
        for encoding in ("utf-8-sig", "utf-8", "cp1251"):
            try:
                return _parse_csv_text(data.decode(encoding))
            except UnicodeDecodeError:
                continue
        return _parse_csv_text(data.decode("utf-8", errors="replace"))
    if suffix in {".xlsx"}:
        return _parse_xlsx_bytes(data)
    raise ValueError(f"Формат не поддерживается: {suffix or path.name}")


def _fetch_url_titles(url: str) -> tuple[dict[str, str], str]:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = resp.read()
    if url.lower().endswith((".yml", ".xml")) or data.lstrip()[:1] in (b"<", b"\xef"):
        return _parse_yml_bytes(data)
    text = data.decode("utf-8-sig", errors="replace")
    if text.lstrip().startswith("<"):
        return _parse_yml_bytes(data)
    return _parse_csv_text(text), ""


def fetch_parser_catalog(urls: list[str] | None) -> ProductCatalog:
    merged: dict[str, str] = {}
    latest_date = ""
    for url in normalize_parser_urls(urls):
        titles, catalog_date = _fetch_url_titles(url)
        merged.update(titles)
        if catalog_date and catalog_date > latest_date:
            latest_date = catalog_date
    fetched_at = _now_str()
    return ProductCatalog(
        parser_date=latest_date,
        parser_fetched_at=fetched_at,
        parser_count=len(merged),
        parser_titles=merged,
    )


def _catalog_to_json(catalog: ProductCatalog) -> dict:
    return {
        "parser_date": catalog.parser_date,
        "parser_fetched_at": catalog.parser_fetched_at,
        "parser_count": catalog.parser_count,
        "parser_titles": catalog.parser_titles,
        "local_updated_at": catalog.local_updated_at,
        "local_updated_by": catalog.local_updated_by,
        "local_count": catalog.local_count,
        "local_titles": catalog.local_titles,
    }


def _catalog_from_json(data: dict) -> ProductCatalog:
    if "parser_titles" in data or "local_titles" in data:
        return ProductCatalog(
            parser_date=str(data.get("parser_date", "")),
            parser_fetched_at=str(data.get("parser_fetched_at", "")),
            parser_count=int(data.get("parser_count", 0)),
            parser_titles={str(k): str(v) for k, v in (data.get("parser_titles") or {}).items()},
            local_updated_at=str(data.get("local_updated_at", "")),
            local_updated_by=str(data.get("local_updated_by", "")),
            local_count=int(data.get("local_count", 0)),
            local_titles={str(k): str(v) for k, v in (data.get("local_titles") or {}).items()},
        )
    # legacy cache
    titles = {str(k): str(v) for k, v in (data.get("titles") or {}).items()}
    return ProductCatalog(
        parser_date=str(data.get("catalog_date", "")),
        parser_fetched_at=str(data.get("fetched_at", "")),
        parser_count=int(data.get("count", len(titles))),
        parser_titles=titles,
    )


def save_catalog(catalog: ProductCatalog) -> None:
    catalog_cache_path().write_text(
        json.dumps(_catalog_to_json(catalog), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_catalog() -> ProductCatalog | None:
    path = catalog_cache_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return _catalog_from_json(data)
    except Exception:
        return None


def sync_local_with_parser(catalog: ProductCatalog) -> ProductCatalog:
    local = {
        article: title
        for article, title in catalog.local_titles.items()
        if article not in catalog.parser_titles
    }
    return ProductCatalog(
        parser_date=catalog.parser_date,
        parser_fetched_at=catalog.parser_fetched_at,
        parser_count=len(catalog.parser_titles),
        parser_titles=dict(catalog.parser_titles),
        local_updated_at=catalog.local_updated_at,
        local_updated_by=catalog.local_updated_by,
        local_count=len(local),
        local_titles=local,
    )


def merge_parser_catalog(existing: ProductCatalog | None, parser_part: ProductCatalog) -> ProductCatalog:
    base = existing or ProductCatalog()
    merged = ProductCatalog(
        parser_date=parser_part.parser_date or base.parser_date,
        parser_fetched_at=parser_part.parser_fetched_at,
        parser_count=len(parser_part.parser_titles),
        parser_titles=dict(parser_part.parser_titles),
        local_updated_at=base.local_updated_at,
        local_updated_by=base.local_updated_by,
        local_count=base.local_count,
        local_titles=dict(base.local_titles),
    )
    return sync_local_with_parser(merged)


def import_local_file(
    path: Path,
    *,
    catalog: ProductCatalog | None,
    updated_by: str,
) -> ProductCatalog:
    base = catalog or ProductCatalog()
    imported = parse_product_file(path)
    local = dict(base.local_titles)
    for article, title in imported.items():
        if article in base.parser_titles:
            local.pop(article, None)
        else:
            local[article] = title
    local = {a: t for a, t in local.items() if a not in base.parser_titles}
    return ProductCatalog(
        parser_date=base.parser_date,
        parser_fetched_at=base.parser_fetched_at,
        parser_count=len(base.parser_titles),
        parser_titles=dict(base.parser_titles),
        local_updated_at=_now_str(),
        local_updated_by=updated_by.strip() or "—",
        local_count=len(local),
        local_titles=local,
    )


def fetch_catalog(urls: list[str] | None = None) -> ProductCatalog:
    existing = load_catalog()
    parser_part = fetch_parser_catalog(urls)
    merged = merge_parser_catalog(existing, parser_part)
    save_catalog(merged)
    return merged


def article_from_name(name: str) -> str:
    name = name.strip()
    if " - " in name:
        return name.split(" - ", 1)[0].strip()
    return name


def lookup_title(catalog: ProductCatalog | None, article: str) -> str | None:
    if catalog is None:
        return None
    return catalog.lookup(article)


def sanitize_folder_name(name: str, *, max_len: int = 180) -> str:
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, " ")
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    return name


def labeled_folder_name(article: str, catalog: ProductCatalog | None) -> str | None:
    article = article_from_name(article)
    title = lookup_title(catalog, article)
    if not title:
        return None
    return sanitize_folder_name(f"{article} - {title}")


def label_export_dir(output_dir: Path, catalog: ProductCatalog | None) -> Path:
    new_name = labeled_folder_name(output_dir.name, catalog)
    if not new_name or new_name == output_dir.name:
        return output_dir
    target = output_dir.parent / new_name
    if target.exists():
        return output_dir
    try:
        output_dir.rename(target)
        return target
    except OSError:
        return output_dir


def parser_sysbar_text(catalog: ProductCatalog | None) -> str:
    if catalog is None or not catalog.parser_titles:
        return "MAX: нет данных"
    date = catalog.parser_date or catalog.parser_fetched_at or "—"
    return f"MAX: {catalog.parser_count} поз. · обновлён {date}"


def local_sysbar_text(catalog: ProductCatalog | None) -> str:
    if catalog is None or not catalog.local_titles:
        return "Локальная база: пусто"
    who = catalog.local_updated_by or "—"
    when = catalog.local_updated_at or "—"
    return f"Локальная база: {catalog.local_count} поз. · {when} · {who}"


def sysbar_text(catalog: ProductCatalog | None) -> str:
    parser = parser_sysbar_text(catalog)
    if catalog and catalog.local_titles:
        return f"{parser} · лок. {catalog.local_count}"
    return parser


def refresh_catalog_async(
    on_done: Callable[[ProductCatalog | None, Exception | None], None],
    *,
    urls: list[str] | None = None,
) -> None:
    def _worker() -> None:
        with _fetch_lock:
            try:
                on_done(fetch_catalog(urls), None)
            except Exception as exc:
                on_done(None, exc)

    threading.Thread(target=_worker, daemon=True).start()
