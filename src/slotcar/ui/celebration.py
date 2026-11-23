"""Full-window winner celebration: procedural fireworks + winner card."""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from typing import Callable

import customtkinter as ctk
from PIL import Image, ImageTk

from .. import icons
from .. import theme as T
from .fireworks import FireworksShow
from .widgets import font

FRAME_MS = 33          # target ~30 fps
RENDER_MAX_W = 1920    # render at native size up to this width (larger windows are up-scaled)
SKY_BEHIND_CARD = T.mix("#03040a", "#141a35", 0.33)  # sky colour at mid-height (card corner colour)


class _Renderer(threading.Thread):
    """Steps the simulation and renders/up-scales frames off the UI thread.

    Pillow releases the GIL for its heavy pixel work, so this runs in parallel
    with Tk; the UI thread only has to hand the finished frame to Tk.
    """

    def __init__(self, show: FireworksShow, size: tuple[int, int]) -> None:
        super().__init__(name="fireworks", daemon=True)
        self.show = show
        self.size = size
        self.frames: queue.Queue[Image.Image] = queue.Queue(maxsize=2)
        self.stop_event = threading.Event()

    def render_one(self) -> Image.Image:
        img = self.show.render()
        return img if img.size == self.size else img.resize(self.size, Image.BILINEAR)

    def run(self) -> None:
        last = time.perf_counter()
        while not self.stop_event.is_set():
            start = time.perf_counter()
            self.show.step(start - last)
            last = start
            frame = self.render_one()
            while not self.stop_event.is_set():
                try:
                    self.frames.put(frame, timeout=0.05)
                    break
                except queue.Full:
                    continue
            self.stop_event.wait(max(0.0, FRAME_MS / 1000 - (time.perf_counter() - start)))


class Celebration:
    def __init__(self, root: ctk.CTk, on_finished: Callable[[], None]) -> None:
        self.root = root
        self.on_finished = on_finished
        self._label: tk.Label | None = None
        self._card: ctk.CTkFrame | None = None
        self._renderer: _Renderer | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._jobs: list[str] = []
        self.active = False

    def show(self, name: str, lane: int, total: float, margin: float, best: float | None,
             duration_ms: int = 7000) -> None:
        self.close(notify=False)
        self.active = True
        self.root.update_idletasks()
        w, h = max(self.root.winfo_width(), 640), max(self.root.winfo_height(), 400)

        scale = min(1.0, RENDER_MAX_W / w)
        palette = [T.LANE_COLORS[lane], T.LANE_COLORS[lane], T.AMBER, T.ACCENT, T.PURPLE, T.GO_GREEN, "#ffffff"]
        show = FireworksShow(int(w * scale), int(h * scale), palette, finale_at=duration_ms / 1000 - 2.4)
        self._renderer = _Renderer(show, (w, h))
        self._photo = ImageTk.PhotoImage(self._renderer.render_one())
        self._label = tk.Label(self.root, image=self._photo, bg="#000000", bd=0, highlightthickness=0,
                               cursor="hand2")
        self._label.place(x=0, y=0, relwidth=1, relheight=1)
        self._label.bind("<Button-1>", lambda _e: self.close())

        self._build_card(name, lane, total, margin, best)
        self._renderer.start()
        self._jobs.append(self.root.after(FRAME_MS, self._tick))
        self._jobs.append(self.root.after(duration_ms, self.close))

    def _tick(self) -> None:
        r = self._renderer
        if not self.active or r is None or self._photo is None:
            return
        start = time.perf_counter()
        frame = None
        while True:  # always show the newest frame
            try:
                frame = r.frames.get_nowait()
            except queue.Empty:
                break
        if frame is not None:
            self._photo.paste(frame)
        spent = int((time.perf_counter() - start) * 1000)
        self._jobs.append(self.root.after(max(5, FRAME_MS - spent), self._tick))

    def _build_card(self, name: str, lane: int, total: float, margin: float, best: float | None) -> None:
        accent = T.LANE_COLORS[lane]
        card = ctk.CTkFrame(self.root, fg_color=T.mix(T.BG, "#000000", 0.3), corner_radius=28,
                            border_width=2, border_color=T.AMBER, bg_color=SKY_BEHIND_CARD)
        card.grid_columnconfigure(0, weight=1)
        trophy = icons.render_glow("trophy", 192, T.AMBER, glow=14)  # rendered 2x for high-DPI
        img = ctk.CTkImage(trophy, trophy, size=(trophy.width // 2, trophy.height // 2))
        ctk.CTkLabel(card, text="", image=img).grid(row=0, column=0, pady=(26, 0))
        ctk.CTkLabel(card, text="CHEQUERED FLAG  ·  WINNER", font=font(T.UI_SEMIBOLD, 13),
                     text_color=T.AMBER).grid(row=1, column=0, pady=(6, 0))
        ctk.CTkLabel(card, text=name.upper(), font=font(T.DISPLAY_BOLD, 56, "bold"),
                     text_color=T.TEXT).grid(row=2, column=0, padx=48)
        ctk.CTkLabel(card, text=f"LANE {lane}", font=font(T.UI_SEMIBOLD, 12),
                     text_color=accent).grid(row=3, column=0)

        stats = ctk.CTkFrame(card, fg_color="transparent")
        stats.grid(row=4, column=0, pady=(16, 6), padx=36)
        items = [("TOTAL", f"{total:.3f}s", T.TEXT), ("MARGIN", f"+{margin:.3f}s", T.GO_GREEN)]
        if best is not None:
            items.append(("BEST LAP", f"{best:.3f}s", T.PURPLE))
        for col, (cap, val, color) in enumerate(items):
            ctk.CTkLabel(stats, text=cap, font=font(T.UI_SEMIBOLD, 11), text_color=T.TEXT_FAINT).grid(
                row=0, column=col, padx=22)
            ctk.CTkLabel(stats, text=val, font=font(T.DIGITS_FAMILY, 30), text_color=color).grid(
                row=1, column=col, padx=22)
        ctk.CTkLabel(card, text="click anywhere to continue", font=font(size=11),
                     text_color=T.TEXT_FAINT).grid(row=5, column=0, pady=(6, 20))
        for widget in [card, *card.winfo_children()]:
            widget.bind("<Button-1>", lambda _e: self.close())
        # Sit slightly low so the bursts in the upper sky stay visible above the card.
        card.place(relx=0.5, rely=0.6, anchor="center")
        card.lift()
        self._card = card

    def close(self, notify: bool = True) -> None:
        was_active = self.active
        self.active = False
        for job in self._jobs:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
        self._jobs.clear()
        for w in (self._card, self._label):
            if w is not None:
                try:
                    w.destroy()
                except Exception:
                    pass
        self._card = self._label = None
        if self._renderer is not None:
            self._renderer.stop_event.set()
            self._renderer = None
        self._photo = None
        if notify and was_active:
            self.on_finished()
