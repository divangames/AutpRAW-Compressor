"""Fluent Design виджеты для tkinter."""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from ui_theme import (
    ANIM_MS,
    C,
    ICO,
    PAD,
    RADIUS,
    RADIUS_LG,
    RADIUS_SM,
    font,
    font_icon,
    lerp_color,
    mode_palette,
)


def round_rect(
    canvas: tk.Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    r: float,
    **kwargs: Any,
) -> int:
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    pts = [
        x1 + r, y1, x2 - r, y1,
        x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r,
        x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kwargs)


class _AnimMixin:
    _hover_t: float = 0.0
    _press_t: float = 0.0
    _anim_id: str | None = None

    def _cancel_anim(self) -> None:
        if self._anim_id:
            try:
                self.after_cancel(self._anim_id)
            except Exception:
                pass
            self._anim_id = None

    def _animate_to(self, attr: str, target: float, redraw: Callable[[], None]) -> None:
        self._cancel_anim()

        def step() -> None:
            current = getattr(self, attr)
            diff = target - current
            if abs(diff) < 0.04:
                setattr(self, attr, target)
                redraw()
                self._anim_id = None
                return
            setattr(self, attr, current + diff * 0.28)
            redraw()
            self._anim_id = self.after(ANIM_MS, step)

        step()


class FluentButton(tk.Canvas, _AnimMixin):
    def __init__(
        self,
        parent: tk.Misc,
        text: str = "",
        icon: str = "",
        command: Callable[[], None] | None = None,
        variant: str = "primary",
        width: int = 140,
        height: int = 44,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            parent,
            width=width,
            height=height,
            highlightthickness=0,
            bd=0,
            bg=C["MAIN"],
            **kwargs,
        )
        self._text = text
        self._icon = icon
        self._command = command
        self._variant = variant
        self._enabled = True
        self._btn_w = width
        self._btn_h = height
        self._hover_t = 0.0
        self._press_t = 0.0
        self._anim_id = None

        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self._redraw()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._redraw()

    def _colors(self) -> tuple[str, str]:
        if not self._enabled:
            return C["BTN_SEC"], C["TEXT3"]
        if self._variant == "primary":
            base = C["ACCENT"]
            if self._press_t > 0.3:
                base = lerp_color(C["ACCENT"], C["ACCENT_P"], self._press_t)
            elif self._hover_t > 0:
                base = lerp_color(C["ACCENT"], C["ACCENT_H"], self._hover_t)
            return base, "#ffffff"
        base = C["BTN_SEC"]
        if self._press_t > 0.3:
            base = lerp_color(C["BTN_SEC"], C["BTN_SEC_P"], self._press_t)
        elif self._hover_t > 0:
            base = lerp_color(C["BTN_SEC"], C["BTN_SEC_H"], self._hover_t)
        return base, C["TEXT"]

    def _redraw(self) -> None:
        self.delete("all")
        w = self.winfo_width() or self._btn_w
        h = self.winfo_height() or self._btn_h
        bg, fg = self._colors()

        if self._hover_t > 0 and self._enabled and self._variant == "primary":
            round_rect(
                self, 2, 4, w - 2, h + 2, RADIUS,
                fill=C["ELEVATION"], outline="",
            )

        round_rect(self, 1, 1, w - 1, h - 1, RADIUS, fill=bg, outline="")

        x = 18
        if self._icon:
            self.create_text(x, h // 2, text=self._icon, font=font_icon(14), fill=fg, anchor=tk.W)
            x += 24
        if self._text:
            self.create_text(x, h // 2, text=self._text, font=font(11, "bold" if self._variant == "primary" else "normal"), fill=fg, anchor=tk.W)

    def _on_enter(self, _e: tk.Event) -> None:
        if self._enabled:
            self._animate_to("_hover_t", 1.0, self._redraw)

    def _on_leave(self, _e: tk.Event) -> None:
        self._animate_to("_hover_t", 0.0, self._redraw)
        self._animate_to("_press_t", 0.0, self._redraw)

    def _on_press(self, _e: tk.Event) -> None:
        if self._enabled:
            self._animate_to("_press_t", 1.0, self._redraw)

    def _on_release(self, _e: tk.Event) -> None:
        if self._enabled and self._command:
            self._command()
        self._animate_to("_press_t", 0.0, self._redraw)


class IconButton(tk.Canvas, _AnimMixin):
    def __init__(self, parent: tk.Misc, icon: str, command: Callable[[], None] | None = None, size: int = 36, **kwargs: Any) -> None:
        super().__init__(parent, width=size, height=size, highlightthickness=0, bd=0, bg=C["BG"], **kwargs)
        self._icon = icon
        self._command = command
        self._size = size
        self._hover_t = 0.0
        self._press_t = 0.0
        self._anim_id = None
        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Enter>", lambda _e: self._animate_to("_hover_t", 1.0, self._redraw))
        self.bind("<Leave>", lambda _e: (self._animate_to("_hover_t", 0.0, self._redraw), self._animate_to("_press_t", 0.0, self._redraw)))
        self.bind("<ButtonPress-1>", lambda _e: self._animate_to("_press_t", 1.0, self._redraw))
        self.bind("<ButtonRelease-1>", self._on_release)
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        s = self.winfo_width() or self._size
        bg = lerp_color(C["MICA"], C["CARD_HOVER"], self._hover_t)
        if self._press_t > 0.2:
            bg = lerp_color(bg, C["BTN_SEC_P"], self._press_t)
        round_rect(self, 2, 2, s - 2, s - 2, RADIUS_SM, fill=bg, outline="")
        self.create_text(s // 2, s // 2, text=self._icon, font=font_icon(14), fill=C["TEXT2"], anchor=tk.CENTER)

    def _on_release(self, _e: tk.Event) -> None:
        if self._command:
            self._command()
        self._animate_to("_press_t", 0.0, self._redraw)


class FluentProgressBar(tk.Canvas):
    def __init__(self, parent: tk.Misc, height: int = 10, **kwargs: Any) -> None:
        super().__init__(parent, height=height, highlightthickness=0, bd=0, bg=C["DOCK"], **kwargs)
        self._value = 0.0
        self.bind("<Configure>", lambda _e: self._redraw())

    def set_value(self, pct: float) -> None:
        self._value = max(0.0, min(100.0, pct))
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 4:
            return
        round_rect(self, 0, 0, w, h, h // 2, fill=C["PROGRESS_BG"], outline="")
        fill_w = max(h, w * self._value / 100.0)
        if self._value > 0:
            round_rect(self, 0, 0, fill_w, h, h // 2, fill=C["PROGRESS_FILL"], outline="")


class DropZone(tk.Canvas, _AnimMixin):
    def __init__(
        self,
        parent: tk.Misc,
        on_click: Callable[[], None] | None = None,
        compact: bool = False,
        **kwargs: Any,
    ) -> None:
        self._compact = compact
        h = 76 if compact else 148
        super().__init__(parent, height=h, highlightthickness=0, bd=0, bg=C["MAIN"], **kwargs)
        self._on_click = on_click
        self._drag_over = False
        self._hover_t = 0.0
        self._press_t = 0.0
        self._anim_id = None
        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Enter>", lambda _e: self._animate_to("_hover_t", 1.0, self._redraw))
        self.bind("<Leave>", lambda _e: (self._set_drag(False), self._animate_to("_hover_t", 0.0, self._redraw)))
        self.bind("<Button-1>", lambda _e: self._on_click and self._on_click())
        self._redraw()

    def set_drag_over(self, active: bool) -> None:
        self._set_drag(active)

    def _set_drag(self, active: bool) -> None:
        self._drag_over = active
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 8:
            return

        if self._drag_over:
            bg = C["DROP_ACTIVE"]
            border = C["ACCENT"]
        elif self._hover_t > 0:
            bg = lerp_color(C["DROP_BG"], C["DROP_H"], self._hover_t)
            border = lerp_color(C["DROP_BORDER"], C["ACCENT"], self._hover_t * 0.5)
        else:
            bg = C["DROP_BG"]
            border = C["DROP_BORDER"]

        round_rect(self, 4, 4, w - 4, h - 4, RADIUS_LG, fill=C["ELEVATION"], outline="")
        round_rect(self, 1, 1, w - 1, h - 1, RADIUS_LG, fill=bg, outline=border, width=1)

        if self._compact:
            self.create_text(28, h // 2, text=ICO["FOLDER"], font=font_icon(18), fill=C["ACCENT"], anchor=tk.W)
            self.create_text(56, h // 2 - 8, text="Перетащите папки для добавления в очередь", font=font(11), fill=C["TEXT2"], anchor=tk.W)
            self.create_text(56, h // 2 + 10, text="или нажмите «Добавить папки» слева", font=font(9), fill=C["TEXT3"], anchor=tk.W)
        else:
            self.create_text(w // 2, h // 2 - 28, text=ICO["FOLDER"], font=font_icon(34), fill=C["ACCENT"])
            self.create_text(w // 2, h // 2 + 8, text="Перетащите папки сюда", font=font(14, "bold"), fill=C["TEXT"])
            self.create_text(w // 2, h // 2 + 32, text="Вложенные папки с 1.jpg – 8.jpg разберутся автоматически", font=font(10), fill=C["TEXT3"])
            self.create_text(w // 2, h // 2 + 52, text="Затем нажмите «Запустить» внизу", font=font(9), fill=C["ACCENT"])


class MicaPanel(tk.Canvas):
    """Панель с имитацией Mica/Acrylic."""
    def __init__(self, parent: tk.Misc, radius: int = RADIUS, pad: int = PAD, **kwargs: Any) -> None:
        super().__init__(parent, highlightthickness=0, bd=0, bg=C["BG"], **kwargs)
        self._radius = radius
        self._pad = pad
        self.inner = tk.Frame(self, bg=C["MICA"])
        self._win_id = self.create_window(pad, pad, window=self.inner, anchor=tk.NW)
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, _e: tk.Event | None = None) -> None:
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 2:
            return
        self.delete("bg")
        round_rect(self, 2, 3, w - 2, h - 1, self._radius, fill=C["ELEVATION"], outline="", tags="bg")
        round_rect(self, 0, 0, w, h - 2, self._radius, fill=C["MICA"], outline="", tags="bg")
        inner_w = max(1, w - self._pad * 2)
        inner_h = max(1, h - self._pad * 2)
        self.itemconfigure(self._win_id, width=inner_w, height=inner_h)


class JobCard(tk.Canvas, _AnimMixin):
    """Карточка задачи с прогрессом и раскрываемым списком файлов."""
    _ROW_H = 32
    _CHECK_X = 36
    _CHECK_SIZE = 16
    _MODE_W = 52
    _MODE_H = 20

    def __init__(
        self,
        parent: tk.Misc,
        job: Any,
        display_title: str = "",
        on_select: Callable[[Any, bool], None] | None = None,
        on_toggle: Callable[[Any], None] | None = None,
        on_file_action: Callable[[Any, str], None] | None = None,
        on_toggle_queue: Callable[[Any], None] | None = None,
        on_cycle_pass_mode: Callable[[Any], None] | None = None,
        is_task_selected: Callable[[Any], bool] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(parent, highlightthickness=0, bd=0, bg=C["MAIN"], **kwargs)
        self.job = job
        self._display_title = display_title or job.path.name
        self._expanded = False
        self._selected = False
        self._file_rows: list[tuple[int, int, Any]] = []
        self._hit_regions: list[tuple[int, int, int, int, str, Any]] = []
        self._on_select = on_select or (lambda _o, _c: None)
        self._on_toggle = on_toggle or (lambda _o: None)
        self._on_file_action = on_file_action or (lambda _o, _a: None)
        self._on_toggle_queue = on_toggle_queue or (lambda _o: None)
        self._on_cycle_pass_mode = on_cycle_pass_mode or (lambda _o: None)
        self._is_task_selected = is_task_selected or (lambda _t: False)
        self._hover_t = 0.0
        self._press_t = 0.0
        self._anim_id = None

        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Enter>", lambda _e: self._animate_to("_hover_t", 1.0, self._redraw))
        self.bind("<Leave>", lambda _e: self._animate_to("_hover_t", 0.0, self._redraw))
        self.bind("<Button-1>", self._on_click)
        self.bind("<Button-3>", self._on_right_click)
        self._redraw()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._redraw()

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._redraw()

    def refresh(self) -> None:
        self._redraw()

    def _job_stats(self) -> tuple[int, int, int, int, str, float]:
        from processor import TaskStatus, task_in_queue

        tasks = self.job.tasks
        total = sum(1 for t in tasks if t.path)
        queued = sum(1 for t in tasks if task_in_queue(t))
        done = sum(1 for t in tasks if t.status == TaskStatus.DONE)
        errors = sum(1 for t in tasks if t.status == TaskStatus.ERROR)
        processing = any(t.status == TaskStatus.PROCESSING for t in tasks)

        if processing:
            status = "Обработка"
        elif errors:
            status = f"Ошибки: {errors}"
        elif done == total and total > 0:
            status = "Готово"
        elif done > 0:
            status = f"Частично ({done}/{total})"
        else:
            status = "Ожидает"

        pct = (done / total * 100) if total else 0
        return total, queued, done, errors, status, pct

    def _draw_checkbox(self, x: int, cy: int, checked: bool, active: bool) -> None:
        y1 = cy - self._CHECK_SIZE // 2
        x2 = x + self._CHECK_SIZE
        y2 = cy + self._CHECK_SIZE // 2
        if active:
            fill = C["MICA_LIGHT"]
            outline = C["ACCENT"] if checked else C["TEXT3"]
        else:
            fill = C["MICA"]
            outline = C["TEXT3"]
        round_rect(self, x, y1, x2, y2, 4, fill=fill, outline=outline, width=1)
        if checked:
            mark = ICO["CHECK"] if active else "—"
            color = C["ACCENT"] if active else C["TEXT3"]
            self.create_text(x + self._CHECK_SIZE // 2, cy, text=mark, font=font_icon(9), fill=color, anchor=tk.CENTER)

    def _draw_mode_pill(self, x: int, cy: int, mode: Any, override: bool = False) -> int:
        from processor import PassMode

        pal = mode_palette(mode.value if isinstance(mode, PassMode) else str(mode))
        y1 = cy - self._MODE_H // 2
        x2 = x + self._MODE_W
        y2 = cy + self._MODE_H // 2
        round_rect(self, x, y1, x2, y2, 10, fill=pal["PILL"], outline=pal["CARD_BORDER"], width=1)
        label = mode.short if hasattr(mode, "short") else str(mode)
        self.create_text(x + self._MODE_W // 2, cy, text=label, font=font(8, "bold"), fill=pal["PILL_TEXT"], anchor=tk.CENTER)
        if override:
            self.create_text(x2 + 4, cy, text="•", font=font(10, "bold"), fill=pal["ACCENT"], anchor=tk.W)
        return x2

    def _register_hit(self, x1: int, y1: int, x2: int, y2: int, kind: str, obj: Any) -> None:
        self._hit_regions.append((x1, y1, x2, y2, kind, obj))

    def _redraw(self) -> None:
        from processor import PassMode, TaskStatus, droplet_label_for_task, effective_pass_mode, task_in_queue

        self.delete("all")
        self._hit_regions.clear()
        w = self.winfo_width()
        if w < 20:
            w = 400

        tasks = self.job.tasks
        total, queued, done, _errors, status_text, pct = self._job_stats()
        header_h = 96
        row_h = self._ROW_H
        visible_files = len(tasks) if self._expanded else 0
        h = header_h + visible_files * row_h + 8

        self.configure(height=h)

        folder_pal = mode_palette(self.job.pass_mode.value)
        if self._selected:
            bg = C["CARD_SEL"]
            border = C["CARD_SEL_BORDER"]
        elif self._hover_t > 0:
            bg = lerp_color(folder_pal["CARD"], C["CARD_HOVER"], self._hover_t * 0.35)
            border = folder_pal["CARD_BORDER"]
        else:
            bg = folder_pal["CARD"]
            border = folder_pal["CARD_BORDER"]

        round_rect(self, 3, 3, w - 3, h - 1, RADIUS, fill=C["ELEVATION"], outline="")
        round_rect(self, 0, 0, w, h - 3, RADIUS, fill=bg, outline=border, width=2)

        name = self._display_title
        self.create_text(52, 20, text=name, font=font(12, "bold"), fill=C["TEXT"], anchor=tk.W)
        self.create_text(52, 38, text=str(self.job.path.parent), font=font(9), fill=C["TEXT3"], anchor=tk.W)

        chevron = ICO["CHEVRON_UP"] if self._expanded else ICO["CHEVRON_DOWN"]
        self.create_text(24, 22, text=chevron, font=font_icon(10), fill=C["TEXT3"], anchor=tk.CENTER)
        self.create_text(24, 42, text=ICO["FOLDER"], font=font_icon(16), fill=folder_pal["ACCENT"], anchor=tk.CENTER)

        mode_x = w - 16 - self._MODE_W
        self._draw_mode_pill(mode_x, 20, self.job.pass_mode)
        self._register_hit(mode_x - 2, 8, w - 10, 32, "mode", self.job)

        self.create_text(w - 16, 38, text=f"{queued}/{total} в очереди", font=font(9), fill=C["TEXT2"], anchor=tk.E)

        status_color = C["SUCCESS"] if status_text == "Готово" else C["TEXT2"]
        if status_text == "Обработка":
            status_color = C["PROCESSING"]
        elif "Ошиб" in status_text:
            status_color = C["ERROR"]
        self.create_text(w - 16, 54, text=status_text, font=font(9, "bold"), fill=status_color, anchor=tk.E)

        bar_y = 72
        bar_w = w - 32
        round_rect(self, 16, bar_y, 16 + bar_w, bar_y + 6, 3, fill=C["PROGRESS_BG"], outline="")
        if pct > 0:
            round_rect(self, 16, bar_y, 16 + bar_w * pct / 100, bar_y + 6, 3, fill=folder_pal["PILL"], outline="")

        self._file_rows.clear()
        if self._expanded:
            y = header_h
            for task in tasks:
                row_y2 = y + row_h
                cy = y + row_h // 2
                eff_mode = effective_pass_mode(task, self.job)
                row_pal = mode_palette(eff_mode.value)
                selected = self._is_task_selected(task)
                override = task.pass_mode is not None

                if selected:
                    round_rect(self, 28, y + 2, w - 10, row_y2 - 2, 6, fill=C["CARD_SEL"], outline="")
                else:
                    round_rect(self, 28, y + 2, w - 10, row_y2 - 2, 6, fill=row_pal["ROW"], outline=row_pal["ROW_BORDER"], width=1)

                fname = task.path.name if task.path else task.label
                has_file = task.path is not None
                can_queue = has_file and task.status not in (
                    TaskStatus.DONE,
                    TaskStatus.PROCESSING,
                    TaskStatus.MISSING,
                )
                in_queue = task_in_queue(task) if has_file else False

                self._draw_checkbox(self._CHECK_X, cy, in_queue, can_queue)

                pill_x = 58
                self._draw_mode_pill(pill_x, cy, eff_mode, override=override)
                self._register_hit(pill_x - 2, y + 4, pill_x + self._MODE_W + 8, row_y2 - 4, "mode", task)

                name_color = C["TEXT"]
                if task.status == TaskStatus.SKIPPED:
                    name_color = C["TEXT3"]
                elif task.status == TaskStatus.DONE:
                    name_color = C["SUCCESS"]
                elif task.status == TaskStatus.ERROR:
                    name_color = C["ERROR"]
                elif task.status == TaskStatus.PROCESSING:
                    name_color = C["PROCESSING"]

                self.create_text(118, cy, text=fname, font=font(10), fill=name_color, anchor=tk.W)
                drop = droplet_label_for_task(task, self.job)
                self.create_text(w - 16, cy, text=drop, font=font(9), fill=row_pal["ACCENT"], anchor=tk.E)
                self._file_rows.append((y, row_y2, task))
                y = row_y2

    def _hit_test(self, x: int, y: int) -> tuple[str, Any] | None:
        for x1, y1, x2, y2, kind, obj in self._hit_regions:
            if x1 <= x <= x2 and y1 <= y <= y2:
                return kind, obj
        return None

    def _on_click(self, event: tk.Event) -> None:
        y = event.y
        hit = self._hit_test(event.x, y)
        if hit and hit[0] == "mode":
            self._on_cycle_pass_mode(hit[1])
            return

        if event.x <= 44 and y <= 52:
            self._on_toggle(self.job)
            return
        check_x2 = self._CHECK_X + self._CHECK_SIZE + 6
        for row_y, row_y2, task in self._file_rows:
            if row_y <= y < row_y2:
                if self._CHECK_X - 4 <= event.x <= check_x2:
                    self._on_toggle_queue(task)
                else:
                    ctrl = bool(event.state & 0x4)
                    self._on_select(task, ctrl)
                return
        ctrl = bool(event.state & 0x4)
        self._on_select(self.job, ctrl)

    def _on_right_click(self, event: tk.Event) -> None:
        from processor import PassMode, task_in_queue

        menu = tk.Menu(self, tearoff=0, bg=C["CARD"], fg=C["TEXT"], activebackground=C["ACCENT"], activeforeground="#fff")
        y = event.y
        for row_y, row_y2, task in self._file_rows:
            if row_y <= y < row_y2:
                if task_in_queue(task):
                    menu.add_command(label="Пропустить (снять галочку)", command=lambda t=task: self._on_toggle_queue(t))
                else:
                    menu.add_command(label="В очередь (поставить галочку)", command=lambda t=task: self._on_toggle_queue(t))
                menu.add_separator()
                sub = tk.Menu(menu, tearoff=0, bg=C["CARD"], fg=C["TEXT"])
                sub.add_command(label="Основной", command=lambda t=task: self._on_file_action(t, "mode_main"))
                sub.add_command(label="Старый", command=lambda t=task: self._on_file_action(t, "mode_old"))
                sub.add_command(label="Как у папки", command=lambda t=task: self._on_file_action(t, "mode_inherit"))
                menu.add_cascade(label="Режим прохода", menu=sub)
                menu.add_command(label="Удалить файл", command=lambda t=task: self._on_file_action(t, "remove"))
                menu.tk_popup(event.x_root, event.y_root)
                return
        sub = tk.Menu(menu, tearoff=0, bg=C["CARD"], fg=C["TEXT"])
        sub.add_command(label="Основной", command=lambda: self._on_file_action(self.job, "mode_main"))
        sub.add_command(label="Старый", command=lambda: self._on_file_action(self.job, "mode_old"))
        menu.add_cascade(label="Режим прохода", menu=sub)
        menu.add_command(label="Пропустить папку", command=lambda: self._on_file_action(self.job, "skip"))
        menu.add_command(label="В очередь — все файлы", command=lambda: self._on_file_action(self.job, "queue"))
        menu.add_command(label="Удалить папку", command=lambda: self._on_file_action(self.job, "remove"))
        menu.tk_popup(event.x_root, event.y_root)


class CardScroller(tk.Frame):
    def __init__(self, parent: tk.Misc, **kwargs: Any) -> None:
        super().__init__(parent, bg=C["MAIN"], **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0, bg=C["MAIN"])
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Fluent.Vertical.TScrollbar",
            background=C["CARD"],
            troughcolor=C["MAIN"],
            borderwidth=0,
            arrowsize=0,
        )
        self.scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview, style="Fluent.Vertical.TScrollbar")
        self.inner = tk.Frame(self.canvas, bg=C["MAIN"])
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor=tk.NW)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Enter>", lambda _e: self.canvas.bind_all("<MouseWheel>", self._on_mousewheel))
        self.canvas.bind("<Leave>", lambda _e: self.canvas.unbind_all("<MouseWheel>"))

    def _on_inner_configure(self, _e: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self._win, width=event.width)

    def _on_mousewheel(self, event: tk.Event) -> None:
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def clear(self) -> None:
        for w in self.inner.winfo_children():
            w.destroy()
