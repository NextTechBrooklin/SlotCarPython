"""Reusable, themed widgets for the Slot Car Duel UI."""

from __future__ import annotations

import math
import random
import time
import tkinter as tk
from typing import Callable

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFilter, ImageTk

from .. import icons
from .. import theme as T
from ..protocol import LAPS_PER_RACE, RPM_MAX


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def font(family: str = T.UI_FAMILY, size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=family, size=size, weight=weight)


def icon_image(name: str, size: int = 20, color: str = T.TEXT) -> ctk.CTkImage:
    """CTkImage rendered at 2x so it stays sharp on high-DPI displays."""
    img = icons.render(name, size * 2, color)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))


def fmt_time(seconds: float | None, placeholder: str = "--.---") -> str:
    return placeholder if seconds is None else f"{seconds:.3f}"


def section_label(master, text: str) -> ctk.CTkLabel:
    return ctk.CTkLabel(master, text=text.upper(), font=font(T.UI_SEMIBOLD, 11),
                        text_color=T.TEXT_FAINT, anchor="w")


# ---------------------------------------------------------------------------
# Buttons
# ---------------------------------------------------------------------------

class IconButton(ctk.CTkButton):
    """Sidebar/toolbar button with a racing icon and optional toggle state."""

    STYLES = {
        "primary": dict(fg=T.GO_GREEN, hover=T.GO_GREEN_HOVER, text="#04130b", icon="#04130b"),
        "danger": dict(fg=T.ACCENT, hover=T.ACCENT_HOVER, text="#ffffff", icon="#ffffff"),
        "ghost": dict(fg=T.SURFACE, hover=T.SURFACE_3, text=T.TEXT, icon=T.TEXT_MUTED),
        "subtle": dict(fg=T.SURFACE_2, hover=T.SURFACE_3, text=T.TEXT, icon=T.TEXT_MUTED),
    }

    def __init__(self, master, text: str, icon: str, command: Callable | None = None,
                 style: str = "ghost", height: int = 44, icon_size: int = 20,
                 active_color: str = T.AMBER, **kw) -> None:
        self._style = self.STYLES[style]
        self._icon_name = icon
        self._icon_size = icon_size
        self._active_color = active_color
        self._active = False
        bold = style in ("primary", "danger")
        super().__init__(
            master, text=text, command=command, height=height, corner_radius=12,
            fg_color=self._style["fg"], hover_color=self._style["hover"],
            text_color=self._style["text"], text_color_disabled=T.TEXT_FAINT,
            border_width=0, border_color=self._active_color,
            image=icon_image(icon, icon_size, self._style["icon"]),
            compound="left", anchor="w" if not bold else "center",
            font=font(T.DISPLAY_FAMILY, 17) if bold else font(T.UI_SEMIBOLD, 14),
            **kw,
        )

    def set_icon(self, icon: str) -> None:
        self._icon_name = icon
        self._refresh()

    def set_active(self, active: bool, text: str | None = None) -> None:
        self._active = active
        if text is not None:
            self.configure(text=text)
        self._refresh()

    def _refresh(self) -> None:
        if self._active:
            tint = T.mix(T.SURFACE, self._active_color, 0.16)
            self.configure(fg_color=tint, hover_color=T.mix(T.SURFACE, self._active_color, 0.26),
                           border_width=1, text_color=self._active_color,
                           image=icon_image(self._icon_name, self._icon_size, self._active_color))
        else:
            self.configure(fg_color=self._style["fg"], hover_color=self._style["hover"], border_width=0,
                           text_color=self._style["text"],
                           image=icon_image(self._icon_name, self._icon_size, self._style["icon"]))


# ---------------------------------------------------------------------------
# Status pill
# ---------------------------------------------------------------------------

class Pill(ctk.CTkFrame):
    def __init__(self, master, text: str = "", color: str = T.TEXT_MUTED, icon: str | None = None,
                 bg: str = T.SURFACE_2, **kw) -> None:
        super().__init__(master, fg_color=bg, corner_radius=14, height=28, **kw)
        self._icon = icon
        self._img = ctk.CTkLabel(self, text="", width=16)
        self._img.grid(row=0, column=0, padx=(10, 4), pady=3)
        self._label = ctk.CTkLabel(self, text="", font=font(T.UI_SEMIBOLD, 12), height=22)
        self._label.grid(row=0, column=1, padx=(0, 12), pady=3)
        self.set(text, color)

    def set(self, text: str, color: str, icon: str | None = None) -> None:
        if icon:
            self._icon = icon
        if self._icon:
            self._img.configure(image=icon_image(self._icon, 14, color), text="")
        else:
            self._img.configure(image=None, text="●", text_color=color, font=font(size=11))
        self._label.configure(text=text, text_color=color)


# ---------------------------------------------------------------------------
# Tachometer (LED ring)
# ---------------------------------------------------------------------------

class Tachometer(tk.Canvas):
    """A racing-dash style LED ring gauge for the 0-100 RPM channel.

    Static artwork (dim LEDs, lit LEDs, peak LEDs) is rendered with Pillow once
    per size; each value change just masks the lit layer up to the current
    segment, which is cheap enough for smooth 30 fps animation.
    """

    SEGMENTS = 36
    START = 135.0   # Pillow angles: degrees clockwise from 3 o'clock
    SWEEP = 270.0
    GAP = 2.6       # degrees between LEDs
    PEAK_HOLD_S = 1.6

    def __init__(self, master, accent: str, bg: str = T.SURFACE) -> None:
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, width=320, height=280)
        self.accent = accent
        self.bg = bg
        self.value = 0.0
        self.target = 0.0
        self._peak = 0.0
        self._peak_at = 0.0
        self._geom: tuple[int, int, int] | None = None   # (side, cx, cy)
        self._layers: tuple[Image.Image, Image.Image, Image.Image] | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._img_item = self.create_image(0, 0, anchor="center")
        self._value_item = self.create_text(0, 0, text="0", fill=T.TEXT)
        self._unit_item = self.create_text(0, 0, text="RPM", fill=T.TEXT_MUTED)
        self._tick_items: list[int] = [self.create_text(0, 0, text=str(v), fill=T.TEXT_FAINT)
                                       for v in range(0, 101, 20)]
        self._drawn = (-1, -1)
        self._resize_job: str | None = None
        self.bind("<Configure>", self._on_configure)

    # ------------------------------------------------------------- public API
    def set_target(self, rpm: float) -> None:
        self.target = max(0.0, min(RPM_MAX, float(rpm)))

    def reset(self) -> None:
        self.target = self.value = self._peak = 0.0
        self._redraw(force=True)

    def tick(self) -> None:
        """Advance the needle animation one frame (called ~30 fps)."""
        diff = self.target - self.value
        if abs(diff) < 0.15:
            self.value = self.target
        else:
            self.value += diff * (0.45 if diff > 0 else 0.25)  # fast attack, slower decay
        now = time.monotonic()
        if self.value >= self._peak:
            self._peak, self._peak_at = self.value, now
        elif now - self._peak_at > self.PEAK_HOLD_S:
            self._peak = max(self.value, self._peak - 3.0)
        self._redraw()

    # -------------------------------------------------------------- geometry
    def _on_configure(self, _e=None) -> None:
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(40, self._rebuild)

    def _rebuild(self) -> None:
        self._resize_job = None
        w, h = self.winfo_width(), self.winfo_height()
        side = max(80, min(w, h))
        cx, cy = w // 2, h // 2
        self._geom = (side, cx, cy)
        self._layers = self._render_layers(side)
        self._photo = ImageTk.PhotoImage(self._layers[0])
        self.itemconfigure(self._img_item, image=self._photo)
        self.coords(self._img_item, cx, cy)

        self.coords(self._value_item, cx, cy - side * 0.02)
        self.itemconfigure(self._value_item, font=(T.DIGITS_FAMILY, -int(side * 0.25)))
        self.coords(self._unit_item, cx, cy + side * 0.16)
        self.itemconfigure(self._unit_item, font=(T.UI_SEMIBOLD, -max(9, int(side * 0.055))))
        r_lbl = side * 0.285
        for item, v in zip(self._tick_items, range(0, 101, 20)):
            a = math.radians(self.START + self.SWEEP * v / 100)
            self.coords(item, cx + r_lbl * math.cos(a), cy + r_lbl * math.sin(a))
            self.itemconfigure(item, font=(T.UI_FAMILY, -max(8, int(side * 0.045))))
        self._redraw(force=True)

    def _seg_color(self, i: int) -> str:
        t = i / (self.SEGMENTS - 1)
        if t < 0.62:
            return T.mix(T.GAUGE_LOW, "#7cf0b0", t / 0.62 * 0.25)
        if t < 0.84:
            return T.GAUGE_MID
        return T.GAUGE_HIGH

    def _render_layers(self, side: int) -> tuple[Image.Image, Image.Image, Image.Image]:
        ss = 3
        S = side * ss
        c = S / 2
        r_out, thick = S * 0.46, S * 0.085
        step = self.SWEEP / self.SEGMENTS
        bg_rgb = (*T.hex_to_rgb(self.bg), 255)

        def ring(color_for: Callable[[int], str]) -> Image.Image:
            im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            box = (c - r_out, c - r_out, c + r_out, c + r_out)
            for i in range(self.SEGMENTS):
                a0 = self.START + i * step + self.GAP / 2
                a1 = self.START + (i + 1) * step - self.GAP / 2
                d.arc(box, a0, a1, fill=color_for(i), width=int(thick))
            return im

        base = Image.new("RGBA", (S, S), bg_rgb)
        d = ImageDraw.Draw(base)
        # Bezel and inner face.
        d.ellipse((c - S * 0.5 + ss, c - S * 0.5 + ss, c + S * 0.5 - ss, c + S * 0.5 - ss),
                  fill=(*T.hex_to_rgb(T.mix(self.bg, "#000000", 0.35)), 255))
        r_face = S * 0.335
        d.ellipse((c - r_face, c - r_face, c + r_face, c + r_face),
                  fill=(*T.hex_to_rgb(T.mix(self.bg, "#ffffff", 0.025)), 255))
        # Lane-coloured accent arc inside the LEDs.
        r_acc = S * 0.352
        d.arc((c - r_acc, c - r_acc, c + r_acc, c + r_acc), self.START, self.START + self.SWEEP,
              fill=T.mix(self.bg, self.accent, 0.75), width=max(2, int(S * 0.008)))
        base = Image.alpha_composite(base, ring(lambda i: T.GAUGE_OFF))

        lit_ring = ring(self._seg_color)
        glow = lit_ring.filter(ImageFilter.GaussianBlur(S * 0.018))
        lit = Image.alpha_composite(base, glow)
        lit = Image.alpha_composite(lit, lit_ring)
        peak = Image.alpha_composite(base, ring(lambda i: "#ffffff"))

        size = (side, side)
        return (base.resize(size, Image.LANCZOS), lit.resize(size, Image.LANCZOS),
                peak.resize(size, Image.LANCZOS))

    def _pie(self, side: int, a0: float, a1: float) -> Image.Image:
        m = Image.new("L", (side, side), 0)
        ImageDraw.Draw(m).pieslice((-2, -2, side + 2, side + 2), a0, a1, fill=255)
        return m

    def _redraw(self, force: bool = False) -> None:
        if self._layers is None or self._geom is None or self._photo is None:
            return
        side = self._geom[0]
        step = self.SWEEP / self.SEGMENTS
        n = round(self.value / RPM_MAX * self.SEGMENTS)
        pk = math.ceil(self._peak / RPM_MAX * self.SEGMENTS)
        if not force and (n, pk) == self._drawn:
            self.itemconfigure(self._value_item, text=f"{self.value:.0f}")
            return
        self._drawn = (n, pk)
        base, lit, peak = self._layers
        out = base.copy()
        if n > 0:
            out.paste(lit, (0, 0), self._pie(side, self.START, self.START + n * step))
        if pk > n and pk > 0:
            out.paste(peak, (0, 0), self._pie(side, self.START + (pk - 1) * step, self.START + pk * step))
        self._photo.paste(out)
        hot = self.value >= RPM_MAX * 0.84
        self.itemconfigure(self._value_item, text=f"{self.value:.0f}", fill=T.GAUGE_HIGH if hot else T.TEXT)


# ---------------------------------------------------------------------------
# F1-style start lights
# ---------------------------------------------------------------------------

class StartLights(tk.Canvas):
    COLORS = {"red": "#ff1f2e", "green": "#14e07f", "amber": "#ffb21c"}
    COUNT = 5

    def __init__(self, master, bg: str = T.BG, on_go: Callable[[], None] | None = None) -> None:
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, width=380, height=74)
        self.bg = bg
        self.on_go = on_go
        self.states = ["off"] * self.COUNT
        self._jobs: list[str] = []
        self._photo: ImageTk.PhotoImage | None = None
        self._item = self.create_image(0, 0, anchor="center")
        self._cache: dict = {}
        self.bind("<Configure>", lambda _e: self._draw())

    @property
    def counting(self) -> bool:
        return bool(self._jobs)

    def set_all(self, state: str) -> None:
        self.cancel()
        self.states = [state] * self.COUNT
        self._draw()

    def cancel(self) -> None:
        for job in self._jobs:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        self._jobs.clear()

    def countdown(self, step_ms: int = 800) -> None:
        """Light 5 reds one by one, hold for a random beat, then lights out -> GO."""
        self.set_all("off")
        for i in range(self.COUNT):
            self._jobs.append(self.after(step_ms * (i + 1), self._light, i))
        hold = step_ms * (self.COUNT + 1) + random.randint(400, 1400)
        self._jobs.append(self.after(hold, self._go))

    def _light(self, i: int) -> None:
        self.states[i] = "red"
        self._draw()

    def _go(self) -> None:
        self._jobs.clear()
        self.states = ["green"] * self.COUNT
        self._draw()
        if self.on_go:
            self.on_go()

    def _draw(self) -> None:
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20 or h < 20:
            return
        key = (w, h, tuple(self.states))
        img = self._cache.get(key)
        if img is None:
            img = self._render(w, h)
            if len(self._cache) > 40:
                self._cache.clear()
            self._cache[key] = img
        self._photo = ImageTk.PhotoImage(img)
        self.itemconfigure(self._item, image=self._photo)
        self.coords(self._item, w // 2, h // 2)

    def _render(self, w: int, h: int) -> Image.Image:
        ss = 3
        W, H = w * ss, h * ss
        im = Image.new("RGBA", (W, H), (*T.hex_to_rgb(self.bg), 255))
        r = H * 0.30
        gap = r * 0.75
        total = self.COUNT * 2 * r + (self.COUNT - 1) * gap
        x0 = (W - total) / 2
        cy = H / 2
        housing = (x0 - r * 0.55, cy - r * 1.45, x0 + total + r * 0.55, cy + r * 1.45)

        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        d = ImageDraw.Draw(im)
        d.rounded_rectangle(housing, radius=r * 0.9, fill="#05070b", outline=T.BORDER_STRONG, width=ss)
        for i, state in enumerate(self.states):
            cx = x0 + r + i * (2 * r + gap)
            box = (cx - r, cy - r, cx + r, cy + r)
            if state == "off":
                d.ellipse(box, fill="#161a22", outline="#232937", width=ss)
                d.ellipse((cx - r * 0.55, cy - r * 0.75, cx + r * 0.2, cy - r * 0.2), fill="#1d222c")
            else:
                col = self.COLORS[state]
                gd.ellipse((cx - r * 1.25, cy - r * 1.25, cx + r * 1.25, cy + r * 1.25), fill=col)
                d.ellipse(box, fill=col)
                d.ellipse((cx - r * 0.55, cy - r * 0.7, cx + r * 0.1, cy - r * 0.15),
                          fill=T.mix(col, "#ffffff", 0.55))
        glow = glow.filter(ImageFilter.GaussianBlur(r * 0.45))
        glow.putalpha(glow.getchannel("A").point(lambda a: int(a * 0.55)))
        out = Image.alpha_composite(im, glow)
        # Re-draw lamp faces on top of the glow so they stay crisp.
        d2 = ImageDraw.Draw(out)
        for i, state in enumerate(self.states):
            if state != "off":
                cx = x0 + r + i * (2 * r + gap)
                col = self.COLORS[state]
                d2.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col)
                d2.ellipse((cx - r * 0.55, cy - r * 0.7, cx + r * 0.1, cy - r * 0.15),
                           fill=T.mix(col, "#ffffff", 0.55))
        return out.resize((w, h), Image.LANCZOS)


# ---------------------------------------------------------------------------
# Driver card
# ---------------------------------------------------------------------------

class LapTile(ctk.CTkFrame):
    def __init__(self, master, lap: int) -> None:
        super().__init__(master, fg_color=T.SURFACE_2, corner_radius=12, border_width=1, border_color=T.BORDER)
        self.grid_columnconfigure(0, weight=1)
        self.caption = ctk.CTkLabel(self, text=f"LAP {lap}", font=font(T.UI_SEMIBOLD, 11),
                                    text_color=T.TEXT_FAINT, height=16)
        self.caption.grid(row=0, column=0, pady=(8, 0))
        self.value = ctk.CTkLabel(self, text="--.---", font=font(T.DIGITS_FAMILY, 24),
                                  text_color=T.TEXT_FAINT, height=30)
        self.value.grid(row=1, column=0, pady=(0, 8), padx=8)

    def show(self, state: str, text: str, accent: str) -> None:
        """state: pending | current | done | pb | fastest"""
        styles = {
            "pending": (T.SURFACE_2, T.BORDER, T.TEXT_FAINT, T.TEXT_FAINT),
            "current": (T.mix(T.SURFACE_2, accent, 0.10), accent, accent, T.TEXT),
            "done": (T.SURFACE_2, T.BORDER, T.TEXT_MUTED, T.TEXT),
            "pb": (T.mix(T.SURFACE_2, T.GO_GREEN, 0.10), T.mix(T.BORDER, T.GO_GREEN, 0.6), T.GO_GREEN, T.GO_GREEN),
            "fastest": (T.mix(T.SURFACE_2, T.PURPLE, 0.18), T.PURPLE, T.PURPLE, "#e6ccff"),
        }
        bg, border, cap, val = styles[state]
        self.configure(fg_color=bg, border_color=border)
        self.caption.configure(text_color=cap)
        self.value.configure(text=text, text_color=val)


class Stat(ctk.CTkFrame):
    def __init__(self, master, caption: str, big: bool = False) -> None:
        super().__init__(master, fg_color="transparent")
        ctk.CTkLabel(self, text=caption, font=font(T.UI_SEMIBOLD, 11), text_color=T.TEXT_FAINT,
                     height=14, anchor="w").grid(row=0, column=0, sticky="w")
        self.value = ctk.CTkLabel(self, text="--.---", font=font(T.DIGITS_FAMILY, 34 if big else 22),
                                  text_color=T.TEXT, anchor="w", height=40 if big else 28)
        self.value.grid(row=1, column=0, sticky="w")

    def set(self, text: str, color: str = T.TEXT) -> None:
        self.value.configure(text=text, text_color=color)


class DriverCard(ctk.CTkFrame):
    CHIP = {
        "waiting": ("WAITING", T.TEXT_MUTED),
        "grid": ("ON THE GRID", T.AMBER),
        "racing": ("ON TRACK", T.GO_GREEN),
        "finished": ("FINISHED", T.TEXT),
        "winner": ("WINNER", T.AMBER),
        "ghost": ("GHOST CAR", T.PURPLE),
    }

    def __init__(self, master, lane: int, on_name_change: Callable[[], None]) -> None:
        self.lane = lane
        self.accent = T.LANE_COLORS[lane]
        super().__init__(master, fg_color=T.SURFACE, corner_radius=20, border_width=1, border_color=T.BORDER)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        ctk.CTkFrame(self, height=4, corner_radius=2, fg_color=self.accent).grid(
            row=0, column=0, padx=22, pady=(14, 0), sticky="ew")

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=1, column=0, padx=18, pady=(12, 0), sticky="ew")
        head.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(head, text="", image=icon_image("helmet", 40, self.accent)).grid(
            row=0, column=0, rowspan=2, padx=(2, 12))
        ctk.CTkLabel(head, text=f"LANE {lane}", font=font(T.UI_SEMIBOLD, 11), text_color=self.accent,
                     height=14, anchor="w").grid(row=0, column=1, sticky="w")
        self.name_entry = ctk.CTkEntry(
            head, placeholder_text=f"Driver {lane}", font=font(T.DISPLAY_FAMILY, 24), height=36,
            fg_color=T.SURFACE, border_width=0, text_color=T.TEXT, placeholder_text_color=T.TEXT_FAINT)
        self.name_entry.grid(row=1, column=1, sticky="ew")
        self.name_entry.bind("<KeyRelease>", lambda _e: on_name_change())
        self.name_entry.bind("<Return>", lambda _e: self.focus_set())
        self.chip = Pill(head, bg=T.SURFACE_2)
        self.chip.grid(row=0, column=2, rowspan=2, sticky="e", padx=(8, 0))

        self.tacho = Tachometer(self, self.accent, bg=T.SURFACE)
        self.tacho.grid(row=2, column=0, padx=14, pady=(4, 0), sticky="nsew")

        laps = ctk.CTkFrame(self, fg_color="transparent")
        laps.grid(row=3, column=0, padx=18, pady=(4, 10), sticky="ew")
        self.tiles: list[LapTile] = []
        for i in range(LAPS_PER_RACE):
            laps.grid_columnconfigure(i, weight=1, uniform="laps")
            tile = LapTile(laps, i + 1)
            tile.grid(row=0, column=i, padx=4, sticky="ew")
            self.tiles.append(tile)

        stats = ctk.CTkFrame(self, fg_color=T.mix(T.SURFACE, "#000000", 0.25), corner_radius=14)
        stats.grid(row=4, column=0, padx=22, pady=(0, 18), sticky="ew")
        for i in range(3):
            stats.grid_columnconfigure(i, weight=1)
        self.total = Stat(stats, "TOTAL", big=True)
        self.total.grid(row=0, column=0, padx=16, pady=10, sticky="w")
        self.best = Stat(stats, "BEST LAP")
        self.best.grid(row=0, column=1, padx=8, pady=10, sticky="nw")
        self.gap = Stat(stats, "GAP")
        self.gap.grid(row=0, column=2, padx=16, pady=10, sticky="nw")
        self.set_chip("waiting")

    @property
    def name(self) -> str:
        return self.name_entry.get().strip()

    def set_chip(self, key: str) -> None:
        text, color = self.CHIP[key]
        self.chip.set(text, color, icon={"winner": "trophy", "ghost": "ghost"}.get(key))
        self.configure(border_color=T.AMBER if key == "winner" else T.BORDER,
                       border_width=2 if key == "winner" else 1)

    def update_from(self, race, phase_racing: bool, fastest: tuple[int, float] | None) -> None:
        d = race.drivers[self.lane]
        for i, tile in enumerate(self.tiles, start=1):
            t = d.laps.get(i)
            if t is None:
                is_current = phase_racing and i == d.laps_done + 1
                tile.show("current" if is_current else "pending", "ON TRACK" if is_current else "--.---",
                          self.accent)
                if is_current:
                    tile.value.configure(font=font(T.UI_SEMIBOLD, 13))
                else:
                    tile.value.configure(font=font(T.DIGITS_FAMILY, 24))
                continue
            tile.value.configure(font=font(T.DIGITS_FAMILY, 24))
            if fastest and fastest[0] == self.lane and abs(fastest[1] - t) < 1e-9:
                state = "fastest"
            elif d.best_lap is not None and abs(d.best_lap - t) < 1e-9 and d.laps_done > 1:
                state = "pb"
            else:
                state = "done"
            tile.show(state, f"{t:.3f}", self.accent)

        self.total.set(fmt_time(d.total if d.laps else None), T.TEXT if d.laps else T.TEXT_FAINT)
        best_is_fastest = fastest is not None and fastest[0] == self.lane
        self.best.set(fmt_time(d.best_lap), T.PURPLE if best_is_fastest else (T.TEXT if d.laps else T.TEXT_FAINT))
        gap = race.gap(self.lane)
        if gap is None:
            self.gap.set("--", T.TEXT_FAINT)
        elif abs(gap) < 0.0005:
            self.gap.set("±0.000", T.TEXT_MUTED)
        else:
            self.gap.set(f"{gap:+.3f}", T.DANGER if gap > 0 else T.GO_GREEN)


# ---------------------------------------------------------------------------
# Toast notifications
# ---------------------------------------------------------------------------

class Toaster:
    KINDS = {
        "info": ("flag", T.TEXT),
        "ok": ("check", T.GO_GREEN),
        "warn": ("cone", T.AMBER),
        "error": ("close", T.DANGER),
    }

    def __init__(self, root: ctk.CTk) -> None:
        self.root = root
        self._frame: ctk.CTkFrame | None = None
        self._job: str | None = None

    def show(self, text: str, kind: str = "info", ms: int = 3500) -> None:
        self.hide()
        icon, color = self.KINDS.get(kind, self.KINDS["info"])
        f = ctk.CTkFrame(self.root, fg_color=T.SURFACE_2, corner_radius=14, border_width=1,
                         border_color=T.mix(T.BORDER, color, 0.5))
        ctk.CTkLabel(f, text="", image=icon_image(icon, 18, color)).grid(row=0, column=0, padx=(14, 8), pady=12)
        ctk.CTkLabel(f, text=text, font=font(T.UI_SEMIBOLD, 13), text_color=T.TEXT,
                     wraplength=380, justify="left").grid(row=0, column=1, padx=(0, 16), pady=12)
        f.place(relx=1.0, rely=1.0, x=-24, y=-24, anchor="se")
        f.lift()
        f.bind("<Button-1>", lambda _e: self.hide())
        self._frame = f
        self._job = self.root.after(ms, self.hide)

    def hide(self) -> None:
        if self._job:
            self.root.after_cancel(self._job)
            self._job = None
        if self._frame is not None:
            self._frame.destroy()
            self._frame = None


# ---------------------------------------------------------------------------
# Race feed
# ---------------------------------------------------------------------------

class RaceFeed(ctk.CTkTextbox):
    TAGS = {
        "time": T.TEXT_FAINT, "info": T.TEXT_MUTED, "lane1": T.LANE_COLORS[1], "lane2": T.LANE_COLORS[2],
        "pb": T.GO_GREEN, "fastest": T.PURPLE, "warn": T.AMBER, "error": T.DANGER, "win": T.AMBER,
        "text": T.TEXT,
    }
    MAX_LINES = 400

    def __init__(self, master, **kw) -> None:
        super().__init__(master, fg_color=T.SURFACE, text_color=T.TEXT, border_width=0, corner_radius=14,
                         font=font(T.MONO_FAMILY, 12), wrap="word", activate_scrollbars=True,
                         scrollbar_button_color=T.SURFACE_3, **kw)
        for tag, color in self.TAGS.items():
            self.tag_config(tag, foreground=color)
        self.configure(state="disabled")

    def add(self, *segments: tuple[str, str]) -> None:
        """Append one line made of ``(text, tag)`` segments, timestamped."""
        self.configure(state="normal")
        self.insert("end", time.strftime("%H:%M:%S  "), "time")
        for text, tag in segments:
            self.insert("end", text, tag)
        self.insert("end", "\n")
        lines = int(self.index("end-1c").split(".")[0])
        if lines > self.MAX_LINES:
            self.delete("1.0", f"{lines - self.MAX_LINES}.0")
        self.see("end")
        self.configure(state="disabled")
