# AutoRAW Compressor

**Версия: 0.0.2.13.Alpha**

<img width="1444" height="934" alt="image" src="https://github.com/user-attachments/assets/d46c6146-f43f-45e6-a735-7561586fade1" />


Прототип массового автокадрирования для съёмки кроссовок: распознаёт товар на светлом фоне, применяет правила посадки по номеру кадра и готовит план кропа для Photoshop. Есть CLI и GUI с ручной подстройкой и экспортом.

Репозиторий: [github.com/divangames/AutpRAW-Compressor](https://github.com/divangames/AutpRAW-Compressor)

## Что нового в 0.0.2.13.Alpha

- **Номер кадра вручную** — клик по бейджу на миниатюре (`03 · 78%`) → выбор `01`…`08`; правила кадрирования и эталон пересчитываются по выбранному номеру.
- **Неполный набор** — если в папке меньше 8 фото, пропуски сохраняются (`нет кадров: 3, 7`); правила не «съезжают» на соседние номера.

## Что нового в 0.0.2.12.Alpha

- **Поворот** — шаг слайдера «Поворот» уменьшен до `0.1°` для более точной ручной подстройки.
- **Тесты** — pytest для crop/export/version; CI на GitHub Actions (Windows).

## Что нового в 0.0.2.10.Alpha

- **Экспорт** — у каждой папки свой статус-бар: «В очереди», прогресс обработки или зелёное «Готово».

## Что нового в 0.0.2.00.Alpha

- **Панель «Эталон»** — при выборе кадра автоматически подставляется образец из `reference/Sneakers/original/etalon/` (кадр 1 → `1.jpg`, 2 → `2.jpg` и т.д.); сброс (×) снова загружает образец по номеру.
- **Иконки** — обновлены `assets/image/favicon.png` (основное приложение) и `assets/image/icon_AutoAction.png` (АвтоЭкшен).
- **Сборка dist** — в portable-копию попадает `reference/Sneakers/original/etalon/`; при сборке проверяется наличие эталонов.
- **Codename** — переход с `ProtoAlpha` на `Alpha`.

Подробнее: [CHANGELOG.md](CHANGELOG.md).

## Возможности

- **Автокадрирование** — детектор товара, правила из `rules/`, нормализованный crop `0..1` для полного RAW в Photoshop.
- **RAW без полной конвертации** — из NEF/DNG берётся встроенный JPEG, рабочее превью до 1200 px по длинной стороне.
- **GUI** — дерево папок, до 8 превью, автонумерация кадров по search-эталонам, **ручной выбор номера** по клику на бейдж, ручной сдвиг/масштаб/поворот, цветокор, панель **«Эталон»** для сравнения с образцом, дроплеты Photoshop, экспорт отмеченных кадров.
- **Режим экспорта** — **Новый** (NEF → RAW-дроплет → PNG полного разрешения → кадрирование) и **Стандартный**; настройка в **Настройки → Режим экспорта**.
- **АвтоЭкшен** (`AutoAction/`) — отдельное приложение для пакетной обработки 1.jpg–8.jpg через Photoshop-дроплеты (версия совпадает с основным продуктом).
- **CLI** — пакетная обработка в `output/` с debug-превью и `crop_plan.json` / `crop_plan.jsx`.
- **Portable-сборка** — `dist/AutoRAWCompressor/` с exe и всеми ресурсами.

## Требования

- Windows 10/11
- Python 3.12+ (для разработки) или готовый `dist` после сборки
- Для GUI/CLI: [Pillow](https://pypi.org/project/Pillow/), [numpy](https://pypi.org/project/numpy/)
- Для сборки exe: PyInstaller (`requirements-build.txt`)

## Быстрый старт

1. Клонируйте репозиторий или распакуйте архив.
2. Положите тестовые снимки в папку `test/` локально (в Git она **не** хранится).
3. Запустите установку зависимостей:

```text
setup.bat
```

4. Запуск GUI:

```text
run_gui.bat
```

Можно перетащить корневую папку съёмки на `run_gui.bat` или указать путь в поле «Загрузить папку».

Пакетная обработка (папки `test`, `reference\Sneakers`, результат в `output`):

```text
run_autocrop.bat
```

## Скрипты (.bat)

| Файл | Назначение |
|------|------------|
| `setup.bat` | Установка Python-зависимостей |
| `run_gui.bat` | Графический интерфейс |
| `run_autocrop.bat` | CLI: автокадрирование в `output/` |
| `run_tests.bat` | pytest: регрессионные тесты |
| `build.bat` | Меню сборки / очистки / запуск dist |
| `sync_github.bat` | Push в GitHub (основной remote) |
| `sync_gitverse.bat` | Push в GitVerse (зеркало кода) |
| `sync_all.bat` | Push в GitHub и GitVerse |

`build.bat` без аргументов открывает меню. Из командной строки:

```text
build.bat build    rem собрать dist\AutoRAWCompressor
build.bat clean    rem удалить dist и кэш сборки
build.bat run      rem запустить GUI из dist
```

## Правила кадрирования

Номер кадра (`01` … `08`) задаёт правило из `rules/`:

| Кадры | Файл правила | Поведение |
|-------|----------------|-----------|
| `01` | `rules/1.jpg` | ширина товара 965 px, отступ снизу 185 px |
| `02`, `03`, `04`, `08` | `rules/2-3-4-8.jpg` | ширина 965 px, отступ снизу 265 px |
| `06` | `rules/6.jpg` | высота 897 px, отступы сверху/снизу 76 px, центр по X |
| `05`, `07` | `rules/other.png` | только вручную (`manual_only`) |

Референс для сравнения: `reference/Sneakers/`; образцы для панели «Эталон»: `reference/Sneakers/original/etalon/`. Профиль цвета: `color/standart.xmp`.

## Нумерация кадров (GUI)

При загрузке папки программа сопоставляет каждое фото с эталонами `reference/Sneakers/search/1.jpg … 8.jpg` и назначает номер кадра **по ракурсу**, а не по порядку файлов в папке.

- На бейджe миниатюры: номер и уверенность авто-сопоставления, например `03 · 78%`.
- Если в папке **меньше 8 снимков**, пропуски сохраняются: экспорт даёт `1.jpg`, `4.jpg`, … без «схлопывания» номеров. В статусе показывается, каких кадров нет (`нет кадров: 3, 7`).
- Если авто-сопоставление ошиблось (например, подошва получила номер бокового ракурса), **нажмите на бейдж** миниатюры и выберите нужный номер `01`…`08`.
  - Правило кадрирования, превью и панель «Эталон» обновятся под выбранный номер.
  - Процент на бейдже исчезает — номер задан вручную.
  - Если выбранный номер уже занят другим фото, **номера меняются местами** (swap).
  - В меню: `—` — слот свободен; имя файла — кто сейчас занимает этот номер.

Перетаскивание миниатюр меняет только порядок в списке; **номера кадров при этом не пересчитываются** по позиции.

## Структура проекта

```text
Compressor/
├── src/                 # autoraw_gui.py, autoraw_crop.py, app_paths.py
├── AutoAction/          # АвтоЭкшен — пакетная обработка через дроплеты
├── rules/               # эталоны посадки
├── reference/           # референсные JPG (в т.ч. original/etalon/ для GUI)
├── assets/image/        # favicon.png, icon_AutoAction.png
├── color/               # XMP-профиль
├── droplets/            # Photoshop droplet (.exe)
├── build/               # PyInstaller, publish_github_release.py
├── test/                # локальные RAW/JPG (в .gitignore)
├── output/              # результаты CLI (в .gitignore)
├── setup.bat
├── run_gui.bat
├── run_autocrop.bat
├── build.bat
├── sync_github.bat
└── sync_gitverse.bat
```

Подробности по алгоритму и GUI — в [src/README.md](src/README.md).

## Результаты CLI (`output/`)

- `*.preview.jpg` — лёгкие превью исходников
- `*.debug.jpg` — превью с рамками (красная — товар, синяя — crop)
- `*.layout.jpg` — предпросмотр на холсте 1400×1050
- `crop_plan.json` — план кадрирования
- `crop_plan.jsx` — заготовка для Photoshop

## Сборка portable

```text
build.bat build
```

Результат: `dist\AutoRAWCompressor\` — `AutoRAW-GUI.exe`, `AutoRAW-Crop.exe`, `reference`, `rules`, `droplets`, `CHANGELOG.md`, `run_gui.bat`. Папку можно переносить на другой диск.

MSIX-пакет (установщик Windows 10/11):

```text
build.bat msix
```

Результат: `dist\AutoRAWCompressor-<версия>.msix` и рядом `dist\AutoRAWCompressor-<версия>-CHANGELOG.txt`. Требуется [Windows SDK](https://developer.microsoft.com/windows/downloads/windows-sdk/) (MakeAppx + SignTool):

```text
winget install Microsoft.WindowsSDK.10.0.22621
```

Первый запуск на новом ПК: от имени администратора `build\msix\install_cert.bat`, затем двойной клик по `.msix`.

### Автообновление (portable / exe)

**Пользователям** токен GitHub не нужен: обновления берутся из [GitHub Releases](https://github.com/divangames/AutpRAW-Compressor/releases).

**Сборка релиза (maintainers):**

```text
python build\build_dist.py
python build\build_release_zip.py
set GITHUB_TOKEN=<token with repo scope>
python build\publish_github_release.py
```

`GITHUB_TOKEN` не коммитить. Опционально для лимита API: `GITHUB_READ_TOKEN` при сборке dist (вшивается в exe).  
Для приватного репозитория или разработки из исходников: `github_token` в `%LOCALAPPDATA%\AutoRAWCompressor\ui_config.json` или `GITHUB_TOKEN`.

В приложении: **Справка → Проверить обновление…** — скачивание, прогресс, распаковка в папку exe и перезапуск.

Имя ZIP: `AutoRAWCompressor-0.0.2.00.Alpha.zip`. Настройки пользователя и `zona/data.dat` при обновлении сохраняются.

**Защитник Windows / SmartScreen:** неподписанный PyInstaller-exe и скрипт установки обновления могут вызывать предупреждение. Это ожидаемо: «Подробнее» → «Выполнить в любом случае», либо добавьте папку `AutoRAWCompressor` в исключения Защитника. Цифровая подпись exe планируется отдельно.

Зависимости сборки:

```text
pip install -r requirements-build.txt
```

## Git (GitHub + GitVerse)

Код пушится в **оба** remote — только commit и push, без релизов на GitVerse.

| Remote | Назначение |
|--------|------------|
| `github` | [github.com/divangames/AutpRAW-Compressor](https://github.com/divangames/AutpRAW-Compressor) — основной; **релизы и автообновление** |
| `gitverse` | [gitverse.ru/delbraun/AutoRAWCompressor](https://gitverse.ru/delbraun/AutoRAWCompressor) — зеркало кода |

```text
sync_github.bat
sync_gitverse.bat
```

Релиз portable-сборки — только на GitHub (`python build\publish_github_release.py`, см. раздел «Автообновление»).

Папка `test/` с RAW-файлами **не попадает в репозиторий** (см. `.gitignore`). Каждый разработчик держит тестовые снимки локально.

## Ограничения

Это рабочий прототип: RAW целиком не конвертируется, чтобы не перегружать память. Следующий шаг — связать `crop_plan.json` с Photoshop-скриптом для применения crop к полному разрешению.

## Версионирование

Текущая версия задаётся в [`src/version.py`](src/version.py) (дубликат строки — [`VERSION`](VERSION), шапка README).

| Компонент | Поле в `version.py` | Назначение |
|-----------|---------------------|------------|
| `X` | `VERSION_MAJOR` | Глобальное обновление (Soft 2, Soft 3, …) |
| `Y` | `VERSION_SEMI` | Полуглобальные изменения |
| `Z` | `VERSION_FEATURE` | Нововведения и изменения функций |
| `W` | `VERSION_PATCH` | Мелкие исправления и мелкие нововведения |
| Codename | `VERSION_CODENAME` | Название сборки (`Alpha`, `Beta`, …) |

Строка версии: `X.Y.Z.W.Codename` (сейчас **0.0.2.13.Alpha**).

Отображается в заголовке GUI, `--version` CLI, меню `build.bat` и `dist/README.txt` после сборки.

## История изменений

См. [CHANGELOG.md](CHANGELOG.md).
