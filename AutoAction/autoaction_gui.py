"""АвтоЭкшен — Fluent Design UI (Windows 11)."""
from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

try:
    from PIL import Image, ImageTk
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False

from banner_toast import BannerToastMixin
from safe_dnd import install_drop_target
from version import APP_NAME, APP_TITLE, VERSION
from win_chrome import apply_windows_chrome

from app_paths import droplets_main_dir, droplets_old_dir, droplets_root, resource_path
from processor import (
    JobFolder,
    TaskStatus,
    FileTask,
    PassMode,
    effective_pass_mode,
    flatten_tasks,
    job_for_task,
    merge_jobs,
    runnable_tasks,
    runnable_tasks_by_folder,
    run_task_droplet,
    scan_job_folders,
    set_task_in_queue,
    task_in_queue,
    validate_droplets_for_tasks,
)
from ui_theme import C, ICO, font, font_display, mode_palette
from ui_widgets import (
    CardScroller,
    DropZone,
    FluentButton,
    FluentProgressBar,
    IconButton,
    JobCard,
)


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class AutoActionApp(tk.Tk, BannerToastMixin):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1100x740")
        self.minsize(920, 640)
        self.configure(bg=C["BG"])
        self._set_window_icon()

        self._roots: list[Path] = []
        self._jobs: list[JobFolder] = []
        self._tasks: list[FileTask] = []
        self._cards: dict[int, JobCard] = {}
        self._expanded: set[int] = set()
        self._selected_jobs: set[int] = set()
        self._selected_tasks: set[int] = set()
        self._worker: threading.Thread | None = None
        self._cancel = threading.Event()
        self._events: queue.Queue = queue.Queue()
        self._drop_queue: queue.Queue = queue.Queue()
        self._dnd_ready = False
        self._start_time = 0.0
        self._done_count = 0
        self._total_count = 0
        self._logo_img = None
        self._last_drop_key: tuple[str, ...] = ()
        self._last_drop_time = 0.0

        self._build_ui()
        self._setup_dnd()
        self._bind_shortcuts()
        self.after(80, self._poll_events)
        self.after(50, self._poll_drop_queue)
        self.after_idle(self._load_logo_deferred)
        self.after(80, lambda: apply_windows_chrome(self))

        droplets = droplets_root()
        main_d = droplets_main_dir()
        old_d = droplets_old_dir()
        if not main_d.is_dir() or not any(main_d.glob("*.exe")):
            self._set_status(f"Основной проход: нет дроплетов в {main_d}")
        elif not (old_d / "old.exe").is_file():
            self._set_status(f"Старый проход: нет {old_d / 'old.exe'}")

    @property
    def _is_busy(self) -> bool:
        return bool(self._worker and self._worker.is_alive())

    def _build_ui(self) -> None:
        shell = tk.Frame(self, bg=C["BG"])
        shell.pack(fill=tk.BOTH, expand=True)

        workspace = tk.Frame(shell, bg=C["BG"])
        workspace.pack(fill=tk.BOTH, expand=True)

        self._build_rail(workspace)
        self._build_main(workspace)
        self._build_command_dock(shell)

    def _build_rail(self, parent: tk.Frame) -> None:
        rail = tk.Frame(parent, bg=C["RAIL"], width=260)
        rail.pack(side=tk.LEFT, fill=tk.Y)
        rail.pack_propagate(False)

        brand = tk.Frame(rail, bg=C["RAIL"], padx=20, pady=22)
        brand.pack(fill=tk.X)

        self._logo_frame = tk.Frame(brand, bg=C["RAIL"])
        self._logo_frame.pack(anchor=tk.W)

        tk.Label(brand, text=APP_NAME, font=font_display(20), fg=C["TEXT"], bg=C["RAIL"]).pack(anchor=tk.W, pady=(10, 2))
        tk.Label(brand, text=VERSION, font=font(9), fg=C["TEXT3"], bg=C["RAIL"]).pack(anchor=tk.W, pady=(0, 2))
        tk.Label(brand, text="Photoshop · пакетная обработка", font=font(9), fg=C["TEXT3"], bg=C["RAIL"]).pack(anchor=tk.W)

        tk.Frame(rail, bg=C["DIVIDER"], height=1).pack(fill=tk.X, padx=16, pady=8)

        actions = tk.Frame(rail, bg=C["RAIL"], padx=16)
        actions.pack(fill=tk.X)

        FluentButton(
            actions,
            text="Добавить папки",
            icon=ICO["ADD"],
            command=self._browse_add,
            variant="primary",
            width=228,
            height=46,
        ).pack(fill=tk.X, pady=(0, 8))
        FluentButton(
            actions,
            text="Очистить очередь",
            icon=ICO["DELETE"],
            command=self._clear_all,
            variant="secondary",
            width=228,
            height=40,
        ).pack(fill=tk.X)

        tk.Frame(rail, bg=C["DIVIDER"], height=1).pack(fill=tk.X, padx=16, pady=16)

        stats = tk.Frame(rail, bg=C["CARD"], padx=16, pady=14)
        stats.pack(fill=tk.X, padx=16)
        tk.Label(stats, text="Сводка", font=font(10, "bold"), fg=C["TEXT2"], bg=C["CARD"]).pack(anchor=tk.W)

        self.stat_folders = tk.Label(stats, text="Папок: 0", font=font(11), fg=C["TEXT"], bg=C["CARD"])
        self.stat_folders.pack(anchor=tk.W, pady=(8, 2))
        self.stat_files = tk.Label(stats, text="Файлов: 0", font=font(11), fg=C["TEXT"], bg=C["CARD"])
        self.stat_files.pack(anchor=tk.W, pady=2)
        self.stat_queued = tk.Label(stats, text="В очереди: 0", font=font(11, "bold"), fg=C["ACCENT"], bg=C["CARD"])
        self.stat_queued.pack(anchor=tk.W, pady=(2, 0))

        tk.Frame(rail, bg=C["DIVIDER"], height=1).pack(fill=tk.X, padx=16, pady=16)

        route = tk.Frame(rail, bg=C["RAIL"], padx=20)
        route.pack(fill=tk.X)
        tk.Label(route, text="Режимы прохода", font=font(9, "bold"), fg=C["TEXT3"], bg=C["RAIL"]).pack(anchor=tk.W)
        tk.Label(route, text="● Основной (синий)", font=font(9), fg=mode_palette("main")["ACCENT"], bg=C["RAIL"]).pack(anchor=tk.W, pady=(4, 1))
        tk.Label(route, text="● Старый (янтарный)", font=font(9), fg=mode_palette("old")["ACCENT"], bg=C["RAIL"]).pack(anchor=tk.W, pady=1)
        tk.Frame(rail, bg=C["DIVIDER"], height=1).pack(fill=tk.X, padx=16, pady=12)
        tk.Label(route, text="Маршрут (Основной)", font=font(9, "bold"), fg=C["TEXT3"], bg=C["RAIL"]).pack(anchor=tk.W)
        for line in ("1 → 01_drop", "2,3,4,8 → 02-03-04-08", "5,6,7 → 05-06-07"):
            tk.Label(route, text=line, font=font(9), fg=C["TEXT2"], bg=C["RAIL"]).pack(anchor=tk.W, pady=1)

        bottom = tk.Frame(rail, bg=C["RAIL"])
        bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=16, pady=16)
        row = tk.Frame(bottom, bg=C["RAIL"])
        row.pack(fill=tk.X)
        IconButton(row, ICO["INFO"], command=self._show_info, size=34).pack(side=tk.LEFT, padx=(0, 6))
        IconButton(row, ICO["SETTINGS"], command=self._show_settings, size=34).pack(side=tk.LEFT)

    def _build_main(self, parent: tk.Frame) -> None:
        main = tk.Frame(parent, bg=C["MAIN"])
        main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        header = tk.Frame(main, bg=C["CHROME"], padx=24, pady=16)
        header.pack(fill=tk.X)

        left = tk.Frame(header, bg=C["CHROME"])
        left.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(left, text="Очередь", font=font_display(18), fg=C["TEXT"], bg=C["CHROME"]).pack(anchor=tk.W)
        tk.Label(
            left,
            text="Ctrl+клик — выбор  ·  Ctrl+A — все  ·  ☑ — очередь  ·  плашка — режим",
            font=font(9),
            fg=C["TEXT3"],
            bg=C["CHROME"],
        ).pack(anchor=tk.W, pady=(4, 0))

        tools = tk.Frame(header, bg=C["CHROME"])
        tools.pack(side=tk.RIGHT)
        for icon, cmd in (
            (ICO["SELECT_ALL"], self._select_all_folders),
            (ICO["CHECK"], self._queue_selected),
            (ICO["SKIP"], self._skip_selected),
            (ICO["DELETE"], self._remove_selected),
            (ICO["REFRESH"], self._rescan_all),
        ):
            IconButton(tools, icon, command=cmd, size=34).pack(side=tk.LEFT, padx=3)

        content = tk.Frame(main, bg=C["MAIN"], padx=24, pady=16)
        content.pack(fill=tk.BOTH, expand=True)

        self.drop_hero = DropZone(content, on_click=self._browse_add, compact=False)
        self.drop_compact = DropZone(content, on_click=self._browse_add, compact=True)

        self.card_scroller = CardScroller(content)

        self.empty_label = tk.Label(
            self.card_scroller.inner,
            text="",
            font=font(11),
            fg=C["TEXT3"],
            bg=C["MAIN"],
            justify=tk.CENTER,
        )
        self._update_queue_view()
        self.card_scroller.pack(fill=tk.BOTH, expand=True)

    def _build_command_dock(self, parent: tk.Frame) -> None:
        dock = tk.Frame(parent, bg=C["DOCK"], padx=24, pady=18)
        dock.pack(fill=tk.X, side=tk.BOTTOM)

        tk.Frame(dock, bg=C["DIVIDER"], height=1).pack(fill=tk.X, pady=(0, 14))

        top = tk.Frame(dock, bg=C["DOCK"])
        top.pack(fill=tk.X, pady=(0, 10))
        self.main_progress = FluentProgressBar(top, height=10)
        self.main_progress.pack(fill=tk.X)

        mid = tk.Frame(dock, bg=C["DOCK"])
        mid.pack(fill=tk.X, pady=(0, 12))

        self.stat_count = tk.Label(mid, text="0 / 0", font=font(12, "bold"), fg=C["TEXT"], bg=C["DOCK"])
        self.stat_count.pack(side=tk.LEFT)
        self.stat_speed = tk.Label(mid, text="— файл/мин", font=font(10), fg=C["TEXT2"], bg=C["DOCK"])
        self.stat_speed.pack(side=tk.LEFT, padx=(18, 0))
        self.stat_time = tk.Label(mid, text="00:00", font=font(10), fg=C["TEXT2"], bg=C["DOCK"])
        self.stat_time.pack(side=tk.LEFT, padx=(18, 0))
        self.stat_remain = tk.Label(mid, text="Осталось: 0", font=font(10), fg=C["TEXT2"], bg=C["DOCK"])
        self.stat_remain.pack(side=tk.RIGHT)

        bottom = tk.Frame(dock, bg=C["DOCK"])
        bottom.pack(fill=tk.X)

        status_col = tk.Frame(bottom, bg=C["DOCK"])
        status_col.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.status_var = tk.StringVar(value="Добавьте папки и нажмите «Запустить»")
        tk.Label(status_col, textvariable=self.status_var, font=font(10), fg=C["TEXT2"], bg=C["DOCK"], anchor=tk.W).pack(anchor=tk.W)
        self.stat_current = tk.Label(status_col, text="Готово к работе", font=font(9), fg=C["TEXT3"], bg=C["DOCK"], anchor=tk.W)
        self.stat_current.pack(anchor=tk.W, pady=(2, 0))

        btns = tk.Frame(bottom, bg=C["DOCK"])
        btns.pack(side=tk.RIGHT)
        self.start_btn = FluentButton(
            btns,
            text="Запустить",
            icon=ICO["PLAY"],
            command=self._start,
            variant="primary",
            width=200,
            height=50,
        )
        self.start_btn.pack(side=tk.LEFT)
        self.stop_btn = FluentButton(
            btns,
            text="Стоп",
            icon=ICO["STOP"],
            command=self._stop,
            variant="secondary",
            width=120,
            height=50,
        )
        self.stop_btn.pack(side=tk.LEFT, padx=(10, 0))
        self.stop_btn.set_enabled(False)

    def _load_logo_deferred(self) -> None:
        parent = self._logo_frame
        path = resource_path("assets", "image", "icon_AutoAction.png")
        if path.is_file() and _HAS_PIL:
            try:
                img = Image.open(path).resize((36, 36), Image.Resampling.LANCZOS)
                self._logo_img = ImageTk.PhotoImage(img)
                tk.Label(parent, image=self._logo_img, bg=C["RAIL"]).pack(anchor=tk.W)
                return
            except Exception:
                pass
        tk.Label(parent, text=ICO["FOLDER"], font=("Segoe MDL2 Assets", 20), fg=C["ACCENT"], bg=C["RAIL"]).pack(anchor=tk.W)

    def _update_queue_view(self) -> None:
        if self._jobs:
            self.drop_hero.pack_forget()
            self.drop_compact.pack(fill=tk.X, pady=(0, 12))
            self.empty_label.pack_forget()
        else:
            self.drop_compact.pack_forget()
            self.drop_hero.pack(fill=tk.X, pady=(0, 16))
            self.empty_label.pack_forget()

    def _update_sidebar_stats(self) -> None:
        folders = len(self._jobs)
        files = sum(1 for t in self._tasks if t.path)
        queued = len(runnable_tasks(self._tasks))
        self.stat_folders.configure(text=f"Папок: {folders}")
        self.stat_files.configure(text=f"Файлов: {files}")
        self.stat_queued.configure(text=f"В очереди: {queued}")

    def _bind_shortcuts(self) -> None:
        self.bind("<Delete>", lambda _e: self._remove_selected())
        self.bind("<Control-a>", lambda _e: self._select_all_files())
        self.card_scroller.canvas.bind("<Control-a>", lambda _e: self._select_all_files())
        self.card_scroller.inner.bind("<Control-a>", lambda _e: self._select_all_files())

    def _setup_dnd(self) -> None:
        # HWND готов только после отрисовки окна.
        self.after(200, self._install_dnd)

    def _install_dnd(self) -> None:
        if self._dnd_ready:
            return
        self.update_idletasks()
        hooked = False
        for widget in (self, self.drop_hero, self.drop_compact, self.card_scroller.canvas):
            if install_drop_target(widget, self._drop_queue):
                hooked = True
        if hooked:
            self._dnd_ready = True

    def _poll_drop_queue(self) -> None:
        try:
            while True:
                paths: list[Path] = self._drop_queue.get_nowait()
                self.drop_hero.set_drag_over(False)
                self.drop_compact.set_drag_over(False)
                key = tuple(str(p.resolve()) for p in paths)
                now = time.monotonic()
                if key == self._last_drop_key and now - self._last_drop_time < 0.35:
                    continue
                self._last_drop_key = key
                self._last_drop_time = now
                self._add_paths(paths)
        except queue.Empty:
            pass
        self.after(50, self._poll_drop_queue)

    def _show_info(self) -> None:
        messagebox.showinfo(
            APP_TITLE,
            "АвтоЭкшен — пакетная обработка 1.jpg–8.jpg\n\n"
            "Режим «Основной» (droplets/Main):\n"
            "  1.jpg → 01_drop\n"
            "  2,3,4,8 → 02-03-04-08\n"
            "  5,6,7 → 05-06-07\n\n"
            "Режим «Старый» (droplets/Old):\n"
            "  все файлы → old.exe\n\n"
            f"Main: {droplets_main_dir()}\n"
            f"Old: {droplets_old_dir()}",
        )

    def _show_settings(self) -> None:
        messagebox.showinfo(
            APP_NAME,
            f"Версия: {VERSION}\n"
            f"Источников папок: {len(self._roots)}\n"
            f"Задач в очереди: {len(self._jobs)}",
        )

    def _browse_add(self) -> None:
        folder = filedialog.askdirectory(title="Выберите папку для добавления")
        if folder:
            self._add_paths([Path(folder)])

    def _add_paths(self, paths: list[Path]) -> None:
        if self._is_busy:
            messagebox.showinfo(APP_TITLE, "Дождитесь окончания обработки.")
            return

        added_roots = 0
        new_jobs: list[JobFolder] = []
        for path in paths:
            resolved = path.resolve()
            if resolved not in {r.resolve() for r in self._roots}:
                self._roots.append(resolved)
                added_roots += 1
            new_jobs.extend(scan_job_folders(resolved))

        before = len(self._jobs)
        self._jobs = merge_jobs(self._jobs, new_jobs)
        added_jobs = len(self._jobs) - before
        self._sync_tasks()
        self._rebuild_cards()
        self._refresh_counts()

        if added_jobs:
            self._set_status(f"Добавлено папок: {added_jobs}")
        elif added_roots:
            self._set_status("Папка добавлена, файлы 1.jpg–8.jpg не найдены")
        else:
            self._set_status("Эти папки уже в списке")

    def _clear_all(self) -> None:
        if self._is_busy:
            return
        if not self._jobs:
            return
        if not messagebox.askyesno(APP_TITLE, "Очистить весь список?"):
            return
        self._roots.clear()
        self._jobs.clear()
        self._selected_jobs.clear()
        self._selected_tasks.clear()
        self._expanded.clear()
        self._sync_tasks()
        self._rebuild_cards()
        self._refresh_counts()
        self._set_status("Список очищен")

    def _rescan_all(self) -> None:
        if self._is_busy or not self._roots:
            return
        jobs: list[JobFolder] = []
        for root in self._roots:
            jobs = merge_jobs(jobs, scan_job_folders(root))
        self._jobs = jobs
        self._sync_tasks()
        self._rebuild_cards()
        self._refresh_counts()
        self._set_status(f"Обновлено: {len(self._jobs)} папок")

    def _sync_tasks(self) -> None:
        self._tasks = flatten_tasks(self._jobs)

    def _job_key(self, job: JobFolder) -> int:
        return id(job)

    def _task_key(self, task: FileTask) -> int:
        return id(task)

    def _folder_title(self, job: JobFolder) -> str:
        name = job.path.name
        if sum(1 for j in self._jobs if j.path.name == name) > 1:
            return f"{job.path.parent.name}/{name}"
        return name

    def _rebuild_cards(self) -> None:
        for w in self.card_scroller.inner.winfo_children():
            if w is not self.empty_label:
                w.destroy()
        self._cards.clear()

        self._update_queue_view()

        if not self._jobs:
            return

        self.empty_label.pack_forget()

        for job in self._jobs:
            key = self._job_key(job)
            card = JobCard(
                self.card_scroller.inner,
                job,
                display_title=self._folder_title(job),
                on_select=self._on_card_select,
                on_toggle=self._on_card_toggle,
                on_file_action=self._on_file_action,
                on_toggle_queue=self._on_toggle_queue,
                on_cycle_pass_mode=self._on_cycle_pass_mode,
                is_task_selected=lambda t, s=self: s._task_key(t) in s._selected_tasks,
            )
            card.pack(fill=tk.X, pady=6, padx=2)
            card.set_expanded(key in self._expanded)
            card.set_selected(key in self._selected_jobs)
            self._cards[key] = card

    def _refresh_cards(self) -> None:
        for key, card in self._cards.items():
            card.refresh()
            card.set_selected(key in self._selected_jobs)

    def _on_card_select(self, obj: JobFolder | FileTask, ctrl: bool) -> None:
        if self._is_busy:
            return
        if isinstance(obj, JobFolder):
            key = self._job_key(obj)
            if ctrl:
                self._selected_jobs.symmetric_difference_update({key})
            else:
                self._selected_jobs = {key}
                self._selected_tasks.clear()
        else:
            key = self._task_key(obj)
            if ctrl:
                self._selected_tasks.symmetric_difference_update({key})
            else:
                self._selected_tasks = {key}
                self._selected_jobs.clear()
        self._refresh_cards()

    def _on_card_toggle(self, job: JobFolder) -> None:
        key = self._job_key(job)
        if key in self._expanded:
            self._expanded.discard(key)
        else:
            self._expanded.add(key)
        card = self._cards.get(key)
        if card:
            card.set_expanded(key in self._expanded)
            card.refresh()

    def _on_toggle_queue(self, task: FileTask) -> None:
        if self._is_busy:
            return
        set_task_in_queue(task, not task_in_queue(task))
        self._refresh_counts()
        self._refresh_cards()

    def _on_cycle_pass_mode(self, obj: JobFolder | FileTask) -> None:
        if self._is_busy:
            return
        if isinstance(obj, JobFolder):
            obj.pass_mode = obj.pass_mode.next()
            for task in obj.tasks:
                task.pass_mode = None
            self._set_status(f"Папка: режим «{obj.pass_mode.label}»")
        else:
            job = job_for_task(self._jobs, obj)
            if not job:
                return
            current = effective_pass_mode(obj, job)
            if obj.pass_mode is None:
                obj.pass_mode = current.next()
            else:
                obj.pass_mode = obj.pass_mode.next()
                if obj.pass_mode == job.pass_mode:
                    obj.pass_mode = None
            if obj.pass_mode is None:
                self._set_status(f"Файл: как у папки («{job.pass_mode.label}»)")
            else:
                self._set_status(f"Файл: режим «{obj.pass_mode.label}»")
        self._refresh_cards()

    def _on_file_action(self, obj: JobFolder | FileTask, action: str) -> None:
        if self._is_busy:
            return
        if action == "mode_main":
            if isinstance(obj, JobFolder):
                obj.pass_mode = PassMode.MAIN
                for t in obj.tasks:
                    t.pass_mode = None
            else:
                obj.pass_mode = PassMode.MAIN
            self._refresh_cards()
            return
        if action == "mode_old":
            if isinstance(obj, JobFolder):
                obj.pass_mode = PassMode.OLD
                for t in obj.tasks:
                    t.pass_mode = None
            else:
                obj.pass_mode = PassMode.OLD
            self._refresh_cards()
            return
        if action == "mode_inherit":
            if isinstance(obj, FileTask):
                obj.pass_mode = None
                self._refresh_cards()
            return
        if action == "skip":
            if isinstance(obj, JobFolder):
                for task in obj.tasks:
                    if task.path and task.status not in (TaskStatus.DONE, TaskStatus.PROCESSING):
                        task.status = TaskStatus.SKIPPED
            else:
                if obj.path and obj.status not in (TaskStatus.DONE, TaskStatus.PROCESSING):
                    obj.status = TaskStatus.SKIPPED
            self._refresh_counts()
            self._refresh_cards()
            self._set_status("Пропущено")
        elif action == "queue":
            if isinstance(obj, JobFolder):
                for task in obj.tasks:
                    set_task_in_queue(task, True)
            else:
                set_task_in_queue(obj, True)
            self._refresh_counts()
            self._refresh_cards()
            self._set_status("Добавлено в очередь")
        elif action == "remove":
            if isinstance(obj, JobFolder):
                self._jobs = [j for j in self._jobs if j is not obj]
            else:
                for job in self._jobs:
                    if obj in job.tasks:
                        job.tasks = [t for t in job.tasks if t is not obj]
                        break
                self._jobs = [j for j in self._jobs if j.tasks]
            self._sync_tasks()
            self._rebuild_cards()
            self._refresh_counts()
            self._set_status("Удалено из списка")

    def _selected_objects(self) -> tuple[list[JobFolder], list[FileTask]]:
        folders = [j for j in self._jobs if self._job_key(j) in self._selected_jobs]
        tasks = [t for t in self._tasks if self._task_key(t) in self._selected_tasks]
        return folders, tasks

    def _select_all_folders(self) -> None:
        if self._is_busy:
            return
        self._selected_jobs = {self._job_key(j) for j in self._jobs}
        self._selected_tasks.clear()
        self._refresh_cards()

    def _select_all_files(self) -> None:
        if self._is_busy:
            return
        self._selected_jobs.clear()
        self._selected_tasks = {self._task_key(t) for t in self._tasks if t.path}
        self._expanded = {self._job_key(j) for j in self._jobs}
        for card in self._cards.values():
            card.set_expanded(True)
        self._refresh_cards()
        self._set_status(f"Выбрано файлов: {len(self._selected_tasks)}")

    def _skip_selected(self) -> None:
        if self._is_busy:
            return
        folders, tasks = self._selected_objects()
        for job in folders:
            for task in job.tasks:
                if task.path and task.status not in (TaskStatus.DONE, TaskStatus.PROCESSING):
                    task.status = TaskStatus.SKIPPED
        for task in tasks:
            if task.path and task.status not in (TaskStatus.DONE, TaskStatus.PROCESSING):
                task.status = TaskStatus.SKIPPED
        if folders or tasks:
            self._refresh_counts()
            self._refresh_cards()
            self._set_status("Выбранные элементы пропущены")

    def _queue_selected(self) -> None:
        if self._is_busy:
            return
        folders, tasks = self._selected_objects()
        for job in folders:
            for task in job.tasks:
                set_task_in_queue(task, True)
        for task in tasks:
            set_task_in_queue(task, True)
        if folders or tasks:
            self._refresh_counts()
            self._refresh_cards()
            self._set_status("Выбранные файлы в очереди")

    def _remove_selected(self) -> None:
        if self._is_busy:
            return
        folders, tasks = self._selected_objects()
        if not folders and not tasks:
            return
        if folders:
            remove = {id(j) for j in folders}
            self._jobs = [j for j in self._jobs if id(j) not in remove]
        for task in tasks:
            for job in self._jobs:
                if task in job.tasks:
                    job.tasks = [t for t in job.tasks if t is not task]
                    break
        self._jobs = [j for j in self._jobs if j.tasks]
        self._selected_jobs.clear()
        self._selected_tasks.clear()
        self._sync_tasks()
        self._rebuild_cards()
        self._refresh_counts()
        self._set_status("Удалено из списка")

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _update_progress_ui(self, current: str = "") -> None:
        total = self._total_count
        done = self._done_count
        pct = (done / total * 100) if total else 0
        self.main_progress.set_value(pct)
        self.stat_count.configure(text=f"{done} / {total}")
        remain = max(0, total - done)
        self.stat_remain.configure(text=f"Осталось: {remain}")

        elapsed = 0.0
        if self._start_time:
            elapsed = time.monotonic() - self._start_time
            self.stat_time.configure(text=format_duration(elapsed))

        if elapsed > 1 and done > 0:
            per_min = done / elapsed * 60
            self.stat_speed.configure(text=f"{per_min:.1f} файл/мин")
        elif not self._is_busy:
            self.stat_speed.configure(text="— файл/мин")

        if current:
            self.stat_current.configure(text=current)

    def _refresh_counts(self) -> None:
        runnable = runnable_tasks(self._tasks)
        self._total_count = len(runnable)
        self._done_count = sum(1 for t in self._tasks if t.status == TaskStatus.DONE)
        self._update_sidebar_stats()
        self._update_progress_ui(current="Готово к работе")

    def _start(self) -> None:
        if self._is_busy:
            return
        runnable = runnable_tasks_by_folder(self._jobs)
        if not runnable:
            messagebox.showinfo(APP_TITLE, "Нет файлов для обработки.")
            return
        err = validate_droplets_for_tasks(self._jobs, runnable)
        if err:
            messagebox.showerror(APP_TITLE, err)
            return

        self._cancel.clear()
        self._done_count = 0
        self._total_count = len(runnable)
        self._start_time = time.monotonic()
        self.start_btn.set_enabled(False)
        self.stop_btn.set_enabled(True)

        for task in self._tasks:
            if task.path and task.status not in (TaskStatus.DONE, TaskStatus.SKIPPED):
                task.status = TaskStatus.PENDING
                task.error = ""

        self._refresh_cards()
        self._worker = threading.Thread(target=self._worker_run, args=(runnable,), daemon=True)
        self._worker.start()

    def _stop(self) -> None:
        self._cancel.set()
        self._set_status("Остановка…")

    def _worker_run(self, tasks: list[FileTask]) -> None:
        for job in self._jobs:
            if self._cancel.is_set():
                break
            for task in job.tasks:
                if task not in tasks:
                    continue
                if self._cancel.is_set():
                    break
                if task.path is None or task.status == TaskStatus.SKIPPED:
                    continue
                self._events.put(("task_start", task))
                ok, error = run_task_droplet(task, job)
                self._events.put(("task_done", task, ok, error))
        self._events.put(("finished", self._cancel.is_set(), time.monotonic() - self._start_time))

    def _poll_events(self) -> None:
        try:
            while True:
                event = self._events.get_nowait()
                kind = event[0]

                if kind == "task_start":
                    task: FileTask = event[1]
                    task.status = TaskStatus.PROCESSING
                    self._refresh_cards()
                    rel = task.path.name if task.path else task.label
                    self._update_progress_ui(current=f"{task.folder_name} / {rel}")

                elif kind == "task_done":
                    task, ok, error = event[1], event[2], event[3]
                    task.status = TaskStatus.DONE if ok else TaskStatus.ERROR
                    task.error = error
                    self._done_count += 1
                    self._refresh_cards()
                    self._update_progress_ui()

                elif kind == "finished":
                    cancelled, elapsed_sec = event[1], event[2]
                    self.start_btn.set_enabled(True)
                    self.stop_btn.set_enabled(False)
                    elapsed = format_duration(elapsed_sec)
                    done_ok = sum(1 for t in self._tasks if t.status == TaskStatus.DONE)
                    errors = sum(1 for t in self._tasks if t.status == TaskStatus.ERROR)
                    self._refresh_counts()
                    if cancelled:
                        self._set_status(f"Остановлено за {elapsed}")
                        messagebox.showinfo(
                            APP_NAME,
                            f"Обработка остановлена.\n"
                            f"Успело обработаться: {done_ok}\n"
                            f"Время: {elapsed_sec:.1f} сек",
                        )
                    elif errors:
                        self._set_status(f"Завершено с {errors} ошибками · {elapsed}")
                        messagebox.showwarning(
                            APP_NAME,
                            f"Обработка завершена с ошибками.\n"
                            f"Успешно: {done_ok}\n"
                            f"Ошибок: {errors}\n"
                            f"Время: {elapsed_sec:.1f} сек",
                        )
                    else:
                        self._set_status(f"Готово за {elapsed}")
                        self._show_processing_success_toast(
                            processed=done_ok,
                            elapsed_sec=elapsed_sec,
                            app_label=APP_NAME,
                        )

        except queue.Empty:
            pass

        if self._is_busy and self._start_time:
            self._update_progress_ui()

        self.after(80, self._poll_events)


def main() -> None:
    app = AutoActionApp()
    import sys

    paths: list[Path] = []
    for arg in sys.argv[1:]:
        cleaned = arg.strip().strip('"').strip("{}").strip()
        if not cleaned:
            continue
        path = Path(cleaned)
        if path.is_dir():
            paths.append(path.resolve())
    if paths:
        app.after(200, lambda p=paths: app._add_paths(p))
    app.mainloop()


if __name__ == "__main__":
    main()
