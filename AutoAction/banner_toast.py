"""Toast-уведомление с баннером (как в AutoRAW Compressor)."""
from __future__ import annotations

import sys
import tkinter as tk
from collections.abc import Callable
from typing import TYPE_CHECKING

from app_paths import resource_path
from ui_theme import C, font

if TYPE_CHECKING:
    from autoaction_gui import AutoActionApp

try:
    from PIL import Image, ImageOps, ImageTk

    _HAS_PIL = True
except Exception:
    _HAS_PIL = False


class BannerToastMixin:
    _banner_toast: tk.Toplevel | None = None
    _banner_toast_timer: str | None = None
    _banner_toast_photo: ImageTk.PhotoImage | None = None

    def _set_window_icon(self, window: tk.Tk | tk.Toplevel | None = None) -> None:
        target = window or self
        icon_path = resource_path("assets", "image", "icon_AutoAction.ico")
        if not icon_path.is_file():
            return
        try:
            target.iconbitmap(str(icon_path))
        except tk.TclError:
            pass

    def _toast_workarea_xy(self, toast_w: int, toast_h: int, margin: int = 14) -> tuple[int, int]:
        if sys.platform == "win32":
            try:
                import ctypes

                class _RECT(ctypes.Structure):
                    _fields_ = [
                        ("left", ctypes.c_long),
                        ("top", ctypes.c_long),
                        ("right", ctypes.c_long),
                        ("bottom", ctypes.c_long),
                    ]

                rect = _RECT()
                if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                    x = rect.right - toast_w - margin
                    y = rect.bottom - toast_h - margin
                    return max(rect.left, x), max(rect.top, y)
            except Exception:
                pass
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        return sw - toast_w - margin, sh - toast_h - margin - 48

    def _apply_toast_round_corners(
        self,
        win: tk.Toplevel,
        toast_w: int,
        toast_h: int,
        radius: int = 14,
    ) -> None:
        if sys.platform != "win32":
            return
        try:
            import ctypes

            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            win.update_idletasks()
            hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
            rgn = gdi32.CreateRoundRectRgn(0, 0, toast_w + 1, toast_h + 1, radius, radius)
            user32.SetWindowRgn(hwnd, rgn, True)
        except Exception:
            pass

    def _close_banner_toast(self: AutoActionApp) -> None:
        if self._banner_toast_timer:
            try:
                self.after_cancel(self._banner_toast_timer)
            except Exception:
                pass
            self._banner_toast_timer = None
        if self._banner_toast is not None:
            try:
                self._banner_toast.destroy()
            except Exception:
                pass
            self._banner_toast = None
        self._banner_toast_photo = None

    def _show_banner_toast(
        self: AutoActionApp,
        *,
        banner_file: str,
        title: str,
        detail: str,
        primary_text: str,
        on_primary: Callable[[], None],
        secondary_text: str | None = None,
        on_secondary: Callable[[], None] | None = None,
        fallback_icon: str = "✓",
        auto_close_ms: int | None = 12000,
        app_label: str,
    ) -> None:
        self._close_banner_toast()

        toast_w, hero_h = 380, 210
        body_h = 176 if secondary_text else 148
        toast_h = hero_h + body_h
        margin = 14
        corner_r = 14

        win = tk.Toplevel(self)
        win.overrideredirect(True)
        win.configure(bg="#1a1a1a")
        win.attributes("-topmost", True)
        self._banner_toast = win

        shell = tk.Frame(win, bg="#1a1a1a", bd=0, highlightthickness=0)
        shell.pack(fill=tk.BOTH, expand=True)

        hero = tk.Canvas(shell, width=toast_w, height=hero_h, highlightthickness=0, bd=0, cursor="arrow")
        hero.pack(fill=tk.X)

        banner_path = resource_path("assets", "image", banner_file)
        if _HAS_PIL and banner_path.is_file():
            src = Image.open(banner_path).convert("RGBA")
            fit = ImageOps.fit(src, (toast_w, hero_h), Image.Resampling.LANCZOS)
            self._banner_toast_photo = ImageTk.PhotoImage(fit)
            hero.create_image(0, 0, anchor=tk.NW, image=self._banner_toast_photo)
        else:
            hero.configure(bg=C["ACCENT"])
            hero.create_text(
                toast_w // 2,
                hero_h // 2,
                text=fallback_icon,
                fill="#ffffff",
                font=("Segoe UI", 48, "bold"),
            )

        def _close(_event: tk.Event | None = None) -> None:
            if on_secondary is not None:
                on_secondary()
            else:
                self._close_banner_toast()

        close_btn = tk.Label(
            hero,
            text="✕",
            fg="#ffffff",
            bg="#000000",
            font=("Segoe UI", 10, "bold"),
            padx=6,
            pady=2,
            cursor="hand2",
        )
        hero.create_window(toast_w - 14, 14, window=close_btn, anchor=tk.NE)
        close_btn.bind("<Button-1>", _close)

        body = tk.Frame(shell, bg="#1a1a1a", width=toast_w, height=body_h)
        body.pack(fill=tk.BOTH, expand=True)
        body.pack_propagate(False)

        head = tk.Frame(body, bg="#1a1a1a")
        head.pack(fill=tk.X, padx=16, pady=(14, 0))
        tk.Label(head, text=app_label, bg="#1a1a1a", fg=C["TEXT2"], font=font(9)).pack(side=tk.LEFT)

        tk.Label(
            body,
            text=title,
            bg="#1a1a1a",
            fg="#ffffff",
            font=font(13, weight="bold"),
            anchor="w",
        ).pack(fill=tk.X, padx=16, pady=(10, 4))

        tk.Label(
            body,
            text=detail,
            bg="#1a1a1a",
            fg=C["TEXT2"],
            font=font(10),
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, padx=16)

        btn_row = tk.Frame(body, bg="#1a1a1a")
        btn_row.pack(fill=tk.X, padx=16, pady=(10, 12))

        def _subtle_btn(
            parent: tk.Frame,
            text: str,
            command: Callable[[], None],
            *,
            accent: bool = False,
        ) -> tk.Label:
            bg = "#252525" if accent else "#1a1a1a"
            fg = "#d0d0d0" if accent else "#7a7a7a"
            btn = tk.Label(
                parent,
                text=text,
                bg=bg,
                fg=fg,
                font=font(9),
                padx=10,
                pady=3,
                cursor="hand2",
            )
            hover_bg = "#303030" if accent else "#222222"
            hover_fg = "#ffffff" if accent else "#a8a8a8"

            def _enter(_e: tk.Event) -> None:
                btn.configure(bg=hover_bg, fg=hover_fg)

            def _leave(_e: tk.Event) -> None:
                btn.configure(bg=bg, fg=fg)

            btn.bind("<Button-1>", lambda _e: command())
            btn.bind("<Enter>", _enter)
            btn.bind("<Leave>", _leave)
            return btn

        if secondary_text:
            actions = tk.Frame(btn_row, bg="#1a1a1a")
            actions.pack(anchor="w")
            _subtle_btn(actions, primary_text, on_primary, accent=True).pack(side=tk.LEFT, padx=(0, 8))
            _subtle_btn(actions, secondary_text, lambda: on_secondary() if on_secondary else None).pack(side=tk.LEFT)
        else:
            _subtle_btn(btn_row, primary_text, on_primary).pack(anchor="w")

        self.update_idletasks()
        x, y = self._toast_workarea_xy(toast_w, toast_h, margin)
        win.geometry(f"{toast_w}x{toast_h}+{x}+{y}")
        self.after(30, lambda: self._apply_toast_round_corners(win, toast_w, toast_h, corner_r))

        if auto_close_ms is not None and secondary_text is None:
            self._banner_toast_timer = self.after(auto_close_ms, self._close_banner_toast)

    def _show_processing_success_toast(
        self: AutoActionApp,
        *,
        processed: int,
        elapsed_sec: float,
        app_label: str,
    ) -> None:
        self._show_banner_toast(
            banner_file="MSG_Good.png",
            title="Обработка завершена",
            detail=f"Обработано файлов: {processed}\nВремя: {elapsed_sec:.1f} сек",
            primary_text="Отлично",
            on_primary=self._close_banner_toast,
            app_label=app_label,
        )
