# Новый режим экспорта — план и статус (обновлено 25.06.2026)

## Реализовано

В меню **Настройки → Режим экспорта** (сверху вниз):

- **Новый** (`export_mode: "new"`) — основной пайплайн через RAW-дроплет
- **Стандартный** (`export_mode: "standard"`) — прежний быстрый экспорт из превью

Настройка сохраняется в `ui_config.json`, передаётся в `export_worker(..., export_mode)`.

Файлы: `src/autoraw_gui.py`, `src/ps_window.py`, `droplets/RAW.exe`, `src/app_paths.py`.

---

## Пайплайн «Новый»

После настройки кадрирования в GUI пользователь нажимает экспорт в режиме «Новый».

### Этап 1 — RAW.exe (Photoshop + Camera Raw)

1. В отмеченных папках для каждого **NEF** (по одному за вызов)
2. Запуск `droplets/RAW.exe` с путём к NEF (`run_droplet_subprocess`, окно PS сворачивается)
3. Дроплет применяет фотокоррекцию и сохраняет **PNG полного разрешения** (6016×4016) **в ту же папку**, что и NEF
4. Имя PNG может отличаться от имени NEF — программа находит файл по снимку папки до/после (`_snapshot_pngs` / `_find_droplet_png`)

### Этап 2 — AutoRAW (кадрирование)

1. Загрузить PNG (не embedded preview из NEF)
2. Пересчитать `crop_box` с превью на полное разрешение (`scale_crop_box`)
3. `render_frame` → сохранить в `папка/папка/01.jpg` и т.д.
4. Цветокор из GUI **не применяется** (коррекция уже в RAW-дроплете)

После успешного экспорта промежуточные PNG удаляются. При отмене — остаются.

Прогресс: **RAW: N/M** и **Кадрирование: N/M**.

Пост-экспортные дроплеты (`01_drop.exe` …) и АвтоЭкшен работают как в стандартном режиме, если включены.

---

## Пайплайн «Стандартный»

- NEF → встроенный JPEG через `open_preview()` (до ~2600 px), не полный RAW
- `crop_box` в пикселях превью (`FrameState.image`)
- Экспорт рендерит тот же превью-снимок; цветокор GUI применяется, если включён

```python
export_image = frame.image
export_crop = frame.crop_box
output = render_frame(frame, CANVAS_SIZE, source_image=export_image, crop_box=export_crop)
```

---

## Масштабирование crop_box

`crop_box` — пиксели превью, не 0..1:

```python
scaled_box = scale_crop_box(frame.crop_box, frame.image.size, full_png.size)
output = render_frame(frame, CANVAS_SIZE, source_image=full_png, crop_box=scaled_box)
```

`offset_x`, `offset_y`, `zoom`, `rotation` менять не нужно.

---

## Отменённые идеи (не нужны при RAW.exe)

- ~~Sidecar XMP из `color/adobe.xmp`~~ — коррекция в дроплете
- ~~JSX batch NEF → JPG~~ — заменено на `RAW.exe` → PNG

---

## Ограничения

- Нужен Adobe Photoshop + Camera Raw; в `droplets/` должен лежать `RAW.exe`
- Пакетная обработка долгая — окно PS сворачивается автоматически
- Если в папке нет NEF для кадра — предупреждение, кадр пропускается

---

## Возможные доработки (не срочно)

- Явное поведение для папок только с JPG (fallback на стандартный экспорт?)
- Скрыть/затемнить панель цветокора в режиме «Новый»
- Пост-экспортные дроплеты тоже через `run_droplet_subprocess`
- Уточнить подсчёт `total_units` прогресс-бара в пограничных сценариях
