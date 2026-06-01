"""Версия AutoRAW Compressor — меняйте числа и кодовое имя здесь.

Схема X.Y.Z.W.Codename:
  X (VERSION_MAJOR)   — глобальное обновление продукта (Soft 2, Soft 3, …)
  Y (VERSION_SEMI)    — полуглобальные изменения
  Z (VERSION_FEATURE) — нововведения и изменения функций
  W (VERSION_PATCH)   — мелкие исправления и мелкие нововведения
  Codename            — название сборки (ProtoAlpha, Beta, …)
"""

from __future__ import annotations

VERSION_MAJOR = 0
VERSION_SEMI = 0
VERSION_FEATURE = 1
VERSION_PATCH = 6
VERSION_CODENAME = "ProtoAlpha"

APP_NAME = "AutoRAW Compressor"


def version_string() -> str:
    return f"{VERSION_MAJOR}.{VERSION_SEMI}.{VERSION_FEATURE}.{VERSION_PATCH}.{VERSION_CODENAME}"


VERSION = version_string()
APP_TITLE = f"{APP_NAME} — {VERSION}"
APP_TITLE_SHORT = f"{APP_NAME} {VERSION}"

# При смене версии обновите также VERSION и README.md в корне проекта.
