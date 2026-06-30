"""Сканирование папок и запуск Photoshop-дроплетов."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from app_paths import droplets_main_dir, droplets_old_dir
from ps_window import run_droplet_subprocess, wait_for_output_stable

DROPLET_BY_NUMBER: dict[int, str] = {
    1: "01_drop.exe",
    2: "02-03-04-08_drop.exe",
    3: "02-03-04-08_drop.exe",
    4: "02-03-04-08_drop.exe",
    5: "05-06-07_drop.exe",
    6: "05-06-07_drop.exe",
    7: "05-06-07_drop.exe",
    8: "02-03-04-08_drop.exe",
}

OLD_DROPLET = "old.exe"
TARGET_NUMBERS = tuple(range(1, 9))
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".JPG", ".JPEG")


class PassMode(str, Enum):
    MAIN = "main"
    OLD = "old"

    @property
    def label(self) -> str:
        return "Основной" if self is PassMode.MAIN else "Старый"

    @property
    def short(self) -> str:
        return "Осн." if self is PassMode.MAIN else "Стар."

    def next(self) -> PassMode:
        return PassMode.OLD if self is PassMode.MAIN else PassMode.MAIN


PASS_MODES = (PassMode.MAIN, PassMode.OLD)


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"
    MISSING = "missing"
    SKIPPED = "skipped"


@dataclass
class FileTask:
    folder: Path
    number: int
    path: Path | None
    droplet_name: str
    status: TaskStatus = TaskStatus.PENDING
    error: str = ""
    pass_mode: PassMode | None = None

    @property
    def label(self) -> str:
        return f"{self.number}.jpg"

    @property
    def folder_name(self) -> str:
        return self.folder.name


@dataclass
class JobFolder:
    path: Path
    tasks: list[FileTask] = field(default_factory=list)
    pass_mode: PassMode = PassMode.MAIN


def effective_pass_mode(task: FileTask, job: JobFolder) -> PassMode:
    if task.pass_mode is not None:
        return task.pass_mode
    return job.pass_mode


def droplet_exe_for_task(task: FileTask, job: JobFolder) -> Path:
    mode = effective_pass_mode(task, job)
    if mode is PassMode.OLD:
        return droplets_old_dir() / OLD_DROPLET
    return droplets_main_dir() / DROPLET_BY_NUMBER[task.number]


def droplet_label_for_task(task: FileTask, job: JobFolder) -> str:
    mode = effective_pass_mode(task, job)
    if mode is PassMode.OLD:
        return "old"
    return DROPLET_BY_NUMBER[task.number].replace("_drop.exe", "")


def _find_numbered_file(folder: Path, number: int) -> Path | None:
    for ext in IMAGE_EXTENSIONS:
        candidate = folder / f"{number}{ext}"
        if candidate.is_file():
            return candidate
    for ext in IMAGE_EXTENSIONS:
        candidate = folder / f"{number:02d}{ext}"
        if candidate.is_file():
            return candidate
    return None


def folder_has_targets(folder: Path) -> bool:
    return any(_find_numbered_file(folder, n) is not None for n in TARGET_NUMBERS)


def _job_from_folder(folder: Path) -> JobFolder:
    tasks: list[FileTask] = []
    for number in TARGET_NUMBERS:
        file_path = _find_numbered_file(folder, number)
        droplet = DROPLET_BY_NUMBER[number]
        status = TaskStatus.PENDING if file_path else TaskStatus.MISSING
        tasks.append(
            FileTask(
                folder=folder,
                number=number,
                path=file_path,
                droplet_name=droplet,
                status=status,
            )
        )
    return JobFolder(path=folder, tasks=tasks)


def scan_job_folders(root: Path) -> list[JobFolder]:
    root = Path(root).resolve()
    if not root.is_dir():
        return []

    candidates: list[Path] = []
    seen: set[Path] = set()

    def walk(folder: Path) -> None:
        if folder_has_targets(folder):
            key = folder.resolve()
            if key not in seen:
                seen.add(key)
                candidates.append(folder)
        try:
            children = sorted(folder.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        for child in children:
            if child.is_dir():
                walk(child)

    walk(root)
    return [_job_from_folder(folder) for folder in candidates]


def merge_jobs(existing: list[JobFolder], new_jobs: list[JobFolder]) -> list[JobFolder]:
    seen = {job.path.resolve() for job in existing}
    merged = list(existing)
    for job in new_jobs:
        key = job.path.resolve()
        if key not in seen:
            seen.add(key)
            merged.append(job)
    merged.sort(key=lambda j: str(j.path).lower())
    return merged


def flatten_tasks(jobs: list[JobFolder]) -> list[FileTask]:
    result: list[FileTask] = []
    for job in jobs:
        result.extend(job.tasks)
    return result


def job_for_task(jobs: list[JobFolder], task: FileTask) -> JobFolder | None:
    for job in jobs:
        if task in job.tasks:
            return job
    return None


def task_in_queue(task: FileTask) -> bool:
    return task.path is not None and task.status not in (
        TaskStatus.SKIPPED,
        TaskStatus.MISSING,
        TaskStatus.DONE,
        TaskStatus.PROCESSING,
    )


def set_task_in_queue(task: FileTask, in_queue: bool) -> None:
    if not task.path:
        return
    if task.status in (TaskStatus.DONE, TaskStatus.PROCESSING):
        return
    if in_queue:
        if task.status == TaskStatus.SKIPPED:
            task.status = TaskStatus.PENDING
    elif task.status in (TaskStatus.PENDING, TaskStatus.ERROR):
        task.status = TaskStatus.SKIPPED


def runnable_tasks(tasks: list[FileTask]) -> list[FileTask]:
    return [t for t in tasks if t.path is not None and t.status not in (TaskStatus.DONE, TaskStatus.SKIPPED)]


def runnable_tasks_by_folder(jobs: list[JobFolder]) -> list[FileTask]:
    """Задачи в порядке папок: сначала все файлы одной папки, затем следующей."""
    result: list[FileTask] = []
    for job in jobs:
        for task in job.tasks:
            if task.path is not None and task.status not in (TaskStatus.DONE, TaskStatus.SKIPPED):
                result.append(task)
    return result


def validate_droplets_for_tasks(jobs: list[JobFolder], tasks: list[FileTask]) -> str | None:
    missing: list[str] = []
    for task in tasks:
        job = job_for_task(jobs, task)
        if not job:
            continue
        exe = droplet_exe_for_task(task, job)
        if not exe.is_file():
            missing.append(str(exe))
    if not missing:
        return None
    unique = sorted(set(missing))
    return "Не найдены дроплеты:\n" + "\n".join(unique[:8]) + (f"\n… и ещё {len(unique) - 8}" if len(unique) > 8 else "")


def run_task_droplet(task: FileTask, job: JobFolder) -> tuple[bool, str]:
    if not task.path:
        return False, "Нет файла"
    droplet_exe = droplet_exe_for_task(task, job)
    if not droplet_exe.is_file():
        return False, f"Дроплет не найден: {droplet_exe}"

    try:
        before_stat = task.path.stat()
        result = run_droplet_subprocess([str(droplet_exe), str(task.path)])
        if result.returncode == -1 and result.stderr == "timeout":
            return False, "таймаут ожидания дроплета"
        wait_for_output_stable(task.path, before_stat)
        stderr_text = (result.stderr or "").strip()
        stdout_text = (result.stdout or "").strip()

        after_exists = task.path.exists()
        after_stat = task.path.stat() if after_exists else None
        changed = bool(
            after_stat
            and (
                after_stat.st_mtime_ns != before_stat.st_mtime_ns
                or after_stat.st_size != before_stat.st_size
            )
        )

        soft_success = (
            result.returncode == 1
            and after_exists
            and after_stat is not None
            and after_stat.st_size > 0
            and not stderr_text
            and (changed or not stdout_text)
        )

        if result.returncode != 0 and not soft_success:
            error_text = stderr_text or stdout_text or f"code {result.returncode}"
            return False, error_text
        return True, ""
    except Exception as exc:
        return False, str(exc)
