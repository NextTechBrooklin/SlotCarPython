"""Main application window and controller."""

from __future__ import annotations

import queue
import time
import tkinter as tk
from collections import deque
from datetime import datetime

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont, ImageTk

from .. import APP_NAME, __version__, icons, protocol
from .. import theme as T
from ..audio import AudioEngine, speak
from ..ble import BleManager, ConnState, DeviceInfo, LinkEvent
from ..paths import APP_ICON_FILE
from ..protocol import LapMsg, RpmMsg, StartMsg
from ..race import LapRejected, Phase, Race
from ..results import ResultsLog
from ..simulator import SimulatedLink
from .ble_window import BleWindow
from .celebration import Celebration
from .results_window import ResultsWindow
from .widgets import (DriverCard, IconButton, Pill, RaceFeed, StartLights, Toaster, font, icon_image,
                      section_label)

PUMP_MS = 33  # ~30 fps UI tick


# ---------------------------------------------------------------------------
# Header banner artwork
# ---------------------------------------------------------------------------

def _pil_font(size: int, variation: str) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        f = ImageFont.truetype("bahnschrift.ttf", size)
        f.set_variation_by_name(variation)
        return f
    except Exception:
        try:
            return ImageFont.truetype("segoeuib.ttf", size)
        except Exception:
            return ImageFont.load_default()


class HeaderBanner(tk.Canvas):
    """Logo, slanted title and livery stripes rendered with Pillow."""

    def __init__(self, master) -> None:
        super().__init__(master, bg=T.HEADER_BG, highlightthickness=0, bd=0, height=84)
        self._photo: ImageTk.PhotoImage | None = None
        self._item = self.create_image(0, 0, anchor="nw")
        self._job: str | None = None
        self.bind("<Configure>", self._schedule)

    def _schedule(self, _e=None) -> None:
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(30, self._draw)

    def _draw(self) -> None:
        self._job = None
        w, h = self.winfo_width(), self.winfo_height()
        if w < 50:
            return
        self._photo = ImageTk.PhotoImage(self.render(w, h))
        self.itemconfigure(self._item, image=self._photo)

    @staticmethod
    def render(w: int, h: int) -> Image.Image:
        img = Image.new("RGBA", (w, h), (*T.hex_to_rgb(T.HEADER_BG), 255))

        # Livery stripes sweeping in from the right, fading towards the title.
        stripes = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(stripes)
        slant = h * 0.9
        x = w * 0.50
        for width, color in ((h * 0.55, T.ACCENT), (h * 0.08, "#ffffff"), (h * 0.22, T.ACCENT),
                             (h * 0.05, "#ffffff"), (h * 0.12, T.mix(T.ACCENT, T.HEADER_BG, 0.35))):
            x += h * 0.12
            sd.polygon([(x + slant, 0), (x + slant + width, 0), (x + width, h), (x, h)], fill=color)
            x += width
        fade = Image.linear_gradient("L").rotate(90, expand=True).resize((w, h))
        fade = fade.point(lambda v: int(max(0, min(255, (255 - v) * 1.6 - 120))))
        alpha = Image.composite(stripes.getchannel("A"), Image.new("L", (w, h), 0), fade)
        stripes.putalpha(alpha.point(lambda a: int(a * 0.9)))
        img = Image.alpha_composite(img, stripes)

        # Logo badge.
        badge = icons.app_icon(int(h * 0.62), T.ACCENT)
        img.alpha_composite(badge, (24, (h - badge.height) // 2))

        # Title text drawn on its own layer, then sheared for a speed slant.
        tx = 24 + badge.width + 18
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        title_font = _pil_font(int(h * 0.44), "Bold Condensed")
        sub_font = _pil_font(max(10, int(h * 0.15)), "SemiBold")
        ty = int(h * 0.12)
        ld.text((tx, ty), "SLOT CAR ", font=title_font, fill=T.TEXT)
        dx = ld.textlength("SLOT CAR ", font=title_font)
        ld.text((tx + dx, ty), "DUEL", font=title_font, fill=T.ACCENT)
        sub = "LIVE BLUETOOTH LE LAP TIMING   ·   3-LAP HEAD-TO-HEAD"
        ld.text((tx + 2, int(h * 0.66)), sub, font=sub_font, fill=T.TEXT_MUTED)
        k = 0.18
        layer = layer.transform(layer.size, Image.AFFINE, (1, k, -k * h * 0.6, 0, 1, 0), Image.BICUBIC)
        return Image.alpha_composite(img, layer).convert("RGB")


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class RaceApp(ctk.CTk):
    def __init__(self, simulate: bool = False) -> None:
        ctk.set_appearance_mode("dark")
        super().__init__(fg_color=T.BG)
        self.title(f"{APP_NAME}  ·  v{__version__}")
        self.geometry("1440x900")
        self.minsize(1200, 780)
        self._ensure_app_icon()
        self.apply_window_icon(self)

        self.events: queue.Queue[LinkEvent] = queue.Queue()
        self.ble = BleManager(self.events)
        self.sim = SimulatedLink(self.events)
        self.link: BleManager | SimulatedLink = self.ble
        self.log_history: deque[tuple[str, str, str]] = deque(maxlen=1500)

        self.race = Race()
        self.results = ResultsLog()
        self.audio = AudioEngine(on_error=lambda m: self.log(m, "warn"))
        self.ghost_on = False
        self.practice_on = False
        self._rpm_ignore_until = 0.0
        self.ble_window: BleWindow | None = None
        self.results_window: ResultsWindow | None = None
        self._closing = False

        self.toaster = Toaster(self)
        self.celebration = Celebration(self, on_finished=self._announce_winner)

        self._build()
        self._bind_keys()
        self._refresh_all()
        self.feed.add(("Pit lane open. ", "text"), ("Connect the timing module from the Pit Wall, ", "info"),
                      ("or start the simulator to try it out.", "info"))
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(PUMP_MS, self._pump)
        if simulate:
            self.after(400, self.toggle_simulator)

    # ================================================================ layout
    def _build(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # -- header -----------------------------------------------------
        header = ctk.CTkFrame(self, fg_color=T.HEADER_BG, corner_radius=0, height=84)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        HeaderBanner(header).grid(row=0, column=0, sticky="ew")
        pills = ctk.CTkFrame(header, fg_color=T.HEADER_BG)
        pills.grid(row=0, column=1, padx=(0, 24))
        self.race_pill = Pill(pills, bg=T.SURFACE, bg_color=T.HEADER_BG)
        self.race_pill.grid(row=0, column=0, padx=6)
        self.conn_pill = Pill(pills, icon="bluetooth", bg=T.SURFACE, bg_color=T.HEADER_BG, cursor="hand2")
        self.conn_pill.grid(row=0, column=1, padx=6)
        for w in [self.conn_pill, *self.conn_pill.winfo_children()]:
            w.bind("<Button-1>", lambda _e: self.open_ble_window())
        stripe = ctk.CTkFrame(self, fg_color=T.ACCENT, corner_radius=0, height=3)
        stripe.grid(row=1, column=0, columnspan=2, sticky="ew")

        # -- sidebar ----------------------------------------------------
        side = ctk.CTkFrame(self, fg_color=T.SURFACE, corner_radius=0, width=250)
        side.grid(row=2, column=0, sticky="nsw")
        side.grid_propagate(False)
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(20, weight=1)

        r = 0
        section_label(side, "Race control").grid(row=r, column=0, padx=22, pady=(22, 8), sticky="w"); r += 1
        self.start_btn = IconButton(side, "START RACE", "flag", self.start_race, style="primary", height=54,
                                    icon_size=26)
        self.start_btn.grid(row=r, column=0, padx=16, pady=4, sticky="ew"); r += 1
        self.reset_btn = IconButton(side, "Reset race", "reset", self.reset_race)
        self.reset_btn.grid(row=r, column=0, padx=16, pady=4, sticky="ew"); r += 1

        section_label(side, "Track modes").grid(row=r, column=0, padx=22, pady=(20, 8), sticky="w"); r += 1
        self.ghost_btn = IconButton(side, "Ghost mode", "ghost", self.toggle_ghost, active_color=T.PURPLE)
        self.ghost_btn.grid(row=r, column=0, padx=16, pady=4, sticky="ew"); r += 1
        self.practice_btn = IconButton(side, "Practice", "cone", self.toggle_practice, active_color=T.AMBER)
        self.practice_btn.grid(row=r, column=0, padx=16, pady=4, sticky="ew"); r += 1

        section_label(side, "Results").grid(row=r, column=0, padx=22, pady=(20, 8), sticky="w"); r += 1
        self.save_btn = IconButton(side, "Save result", "podium", self.save_result)
        self.save_btn.grid(row=r, column=0, padx=16, pady=4, sticky="ew"); r += 1
        IconButton(side, "Results history", "trophy", self.open_results_window).grid(
            row=r, column=0, padx=16, pady=4, sticky="ew"); r += 1

        # Connection mini-card + audio at the bottom of the sidebar.
        bottom = ctk.CTkFrame(side, fg_color="transparent")
        bottom.grid(row=21, column=0, padx=16, pady=(8, 18), sticky="ew")
        bottom.grid_columnconfigure(0, weight=1)
        section_label(bottom, "Connection").grid(row=0, column=0, padx=6, pady=(0, 8), sticky="w")
        self.pitwall_btn = IconButton(bottom, "Pit Wall", "bluetooth", self.open_ble_window, style="subtle",
                                      height=56, active_color=T.GO_GREEN)
        self.pitwall_btn.grid(row=1, column=0, sticky="ew")

        audio = ctk.CTkFrame(bottom, fg_color=T.SURFACE_2, corner_radius=12)
        audio.grid(row=2, column=0, pady=(10, 0), sticky="ew")
        audio.grid_columnconfigure(1, weight=1)
        self.mute_btn = ctk.CTkButton(audio, text="", width=36, height=36, corner_radius=10,
                                      fg_color="transparent", hover_color=T.SURFACE_3,
                                      image=icon_image("speaker", 18, T.TEXT_MUTED), command=self.toggle_mute)
        self.mute_btn.grid(row=0, column=0, padx=(6, 0), pady=6)
        self.volume = ctk.CTkSlider(audio, from_=0, to=1, number_of_steps=100, height=16,
                                    progress_color=T.ACCENT, button_color=T.TEXT, button_hover_color="#ffffff",
                                    fg_color=T.SURFACE_3, command=self._on_volume)
        self.volume.set(self.audio.volume)
        self.volume.grid(row=0, column=1, padx=(4, 12), sticky="ew")
        ctk.CTkLabel(bottom, text="F5 start  ·  F8 reset  ·  Ctrl+B pit wall",
                     font=font(size=10), text_color=T.TEXT_FAINT).grid(row=3, column=0, pady=(10, 0))

        # -- main area --------------------------------------------------
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=2, column=1, padx=24, pady=(18, 20), sticky="nsew")
        main.grid_columnconfigure((0, 1), weight=1, uniform="lanes")
        main.grid_rowconfigure(1, weight=1)

        bar = ctk.CTkFrame(main, fg_color="transparent")
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        bar.grid_columnconfigure((0, 2), weight=1, uniform="bar")
        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w")
        self.phase_caption = ctk.CTkLabel(left, text="", font=font(T.UI_SEMIBOLD, 11), text_color=T.TEXT_FAINT,
                                          height=14, anchor="w")
        self.phase_caption.grid(row=0, column=0, sticky="w")
        self.phase_label = ctk.CTkLabel(left, text="", font=font(T.DISPLAY_BOLD, 34, "bold"),
                                        text_color=T.TEXT, height=40, anchor="w")
        self.phase_label.grid(row=1, column=0, sticky="w")
        self.lights = StartLights(bar, bg=T.BG, on_go=self._lights_out)
        self.lights.configure(width=400, height=78)
        self.lights.grid(row=0, column=1, padx=16)
        right = ctk.CTkFrame(bar, fg_color="transparent")
        right.grid(row=0, column=2, sticky="e")
        ctk.CTkLabel(right, text="FASTEST LAP", font=font(T.UI_SEMIBOLD, 11), text_color=T.TEXT_FAINT,
                     height=14, anchor="e").grid(row=0, column=0, columnspan=2, sticky="e")
        ctk.CTkLabel(right, text="", image=icon_image("stopwatch", 26, T.PURPLE)).grid(row=1, column=0, padx=(0, 8))
        self.fastest_label = ctk.CTkLabel(right, text="--.---", font=font(T.DIGITS_FAMILY, 34),
                                          text_color=T.PURPLE, height=40, anchor="e")
        self.fastest_label.grid(row=1, column=1, sticky="e")
        self.fastest_who = ctk.CTkLabel(right, text="", font=font(size=11), text_color=T.TEXT_MUTED, height=14,
                                        anchor="e")
        self.fastest_who.grid(row=2, column=0, columnspan=2, sticky="e")

        self.cards = {lane: DriverCard(main, lane, self._on_names_changed) for lane in (1, 2)}
        self.cards[1].grid(row=1, column=0, padx=(0, 10), sticky="nsew")
        self.cards[2].grid(row=1, column=1, padx=(10, 0), sticky="nsew")

        feed_wrap = ctk.CTkFrame(main, fg_color=T.SURFACE, corner_radius=16)
        feed_wrap.grid(row=2, column=0, columnspan=2, pady=(16, 0), sticky="ew")
        feed_wrap.grid_columnconfigure(0, weight=1)
        section_label(feed_wrap, "Race feed").grid(row=0, column=0, padx=18, pady=(10, 0), sticky="w")
        self.feed = RaceFeed(feed_wrap, height=118)
        self.feed.grid(row=1, column=0, padx=6, pady=(0, 6), sticky="ew")

    def _bind_keys(self) -> None:
        self.bind("<F5>", lambda _e: self.start_race())
        self.bind("<F8>", lambda _e: self.reset_race())
        self.bind("<Control-b>", lambda _e: self.open_ble_window())
        self.bind("<Control-r>", lambda _e: self.open_results_window())
        self.bind("<Escape>", lambda _e: self.celebration.close() if self.celebration.active else None)

    # ================================================================ icons
    def _ensure_app_icon(self) -> None:
        if APP_ICON_FILE.exists():
            return
        try:
            APP_ICON_FILE.parent.mkdir(parents=True, exist_ok=True)
            icons.app_icon(256, T.ACCENT).save(APP_ICON_FILE, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
        except Exception:
            pass

    def apply_window_icon(self, window) -> None:
        try:
            window.iconbitmap(str(APP_ICON_FILE))
        except Exception:
            pass

    # ================================================================ helpers
    def toast(self, text: str, kind: str = "info") -> None:
        self.toaster.show(text, kind)

    def log(self, text: str, level: str = "info") -> None:
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_history.append((stamp, text, level))
        if self.ble_window is not None:
            self.ble_window.on_log(stamp, text, level)

    def _lane_tag(self, lane: int) -> str:
        return f"lane{lane}"

    def _name(self, lane: int) -> str:
        return self.race.drivers[lane].name

    # ================================================================ event pump
    def _pump(self) -> None:
        if self._closing:
            return
        for _ in range(400):
            try:
                ev = self.events.get_nowait()
            except queue.Empty:
                break
            try:
                self._handle_event(ev)
            except Exception as exc:  # never let one bad event kill the pump
                self.log(f"Internal error handling {ev.kind}: {exc}", "error")
        for card in self.cards.values():
            card.tacho.tick()
        self.after(PUMP_MS, self._pump)

    def _handle_event(self, ev: LinkEvent) -> None:
        if ev.kind == "log":
            self.log(ev.data, ev.level)
        elif ev.kind == "state":
            self._refresh_connection()
        elif ev.kind == "frame":
            self._handle_frame(ev.data)
        elif ev.kind == "scan_result":
            if self.ble_window is not None:
                self.ble_window.on_scan_result(ev.data)
        elif ev.kind == "scan_done":
            if self.ble_window is not None:
                self.ble_window.on_scan_done()

    def _handle_frame(self, frame: str) -> None:
        msg = protocol.parse_frame(frame)
        if msg is None:
            self.log(f"Ignored unrecognised frame: {frame!r}", "warn")
        elif isinstance(msg, RpmMsg):
            if time.monotonic() >= self._rpm_ignore_until:
                self.cards[msg.driver].tacho.set_target(msg.rpm)
        elif isinstance(msg, LapMsg):
            self._on_lap(msg)
        elif isinstance(msg, StartMsg):
            self._on_device_start()

    # ================================================================ connection
    def open_ble_window(self) -> None:
        if self.ble_window is not None and self.ble_window.winfo_exists():
            self.ble_window.deiconify()
            self.ble_window.lift()
            self.ble_window.focus()
            return
        self.ble_window = BleWindow(self)

    def connect_ble(self, info: DeviceInfo) -> None:
        if self.link is self.sim and self.sim.connected:
            self.sim.disconnect()
        self.link = self.ble
        self.ble.stop_scan()
        self.ble.connect(info.address, info.name)

    def disconnect(self) -> None:
        self.link.disconnect()

    def toggle_simulator(self) -> None:
        if self.link is self.sim and self.sim.connected:
            self.sim.disconnect()
            self.link = self.ble
            self.feed.add(("Simulator stopped", "info"))
        else:
            if self.ble.state is not ConnState.DISCONNECTED:
                self.ble.disconnect()
            self.link = self.sim
            self.sim.connect()
            self.feed.add(("Track simulator connected ", "lane2"),
                          ("- press START RACE to watch a simulated duel.", "info"))
        self._refresh_connection()

    def _refresh_connection(self) -> None:
        state, name = self.link.state, self.link.device_name
        if state is ConnState.CONNECTED:
            self.conn_pill.set(name.upper()[:24], T.GO_GREEN)
            self.pitwall_btn.set_active(True, f"Pit Wall\n{name[:22]}")
        elif state is ConnState.CONNECTING:
            self.conn_pill.set("CONNECTING...", T.AMBER)
            self.pitwall_btn.set_active(False, "Pit Wall\nconnecting...")
        else:
            self.conn_pill.set("OFFLINE", T.TEXT_MUTED)
            self.pitwall_btn.set_active(False, "Pit Wall\nnot connected")
        if self.ble_window is not None:
            self.ble_window.on_state(state, name)

    def _send(self, payload: bytes, what: str) -> bool:
        if not self.link.connected:
            self.toast(f"Timing module offline - {what} not sent", "warn")
            self.log(f"{what}: not sent, no connection", "warn")
            return False
        self.link.send(payload)
        return True

    # ================================================================ race flow
    def _on_names_changed(self) -> None:
        self.race.set_names(self.cards[1].name, self.cards[2].name)

    def start_race(self) -> None:
        if self.race.phase is Phase.COUNTDOWN:
            return
        self.celebration.close(notify=False)
        self._end_track_modes()
        self._on_names_changed()
        self.race.arm()
        for card in self.cards.values():
            card.tacho.reset()
        self.feed.add(("Grid formed: ", "info"), (self._name(1), "lane1"), ("  vs  ", "info"),
                      (self._name(2), "lane2"), (" - lights sequence started", "info"))
        self.lights.countdown()
        self._refresh_all()

    def _lights_out(self) -> None:
        self.race.go()
        sent = self._send(protocol.cmd_start_race(), "START_RACE")
        self.feed.add(("LIGHTS OUT - AND AWAY WE GO!", "pb"),
                      ("" if sent else "  (offline: timing module not signalled)", "warn"))
        self.audio.start_music()
        self._refresh_all()

    def _on_device_start(self) -> None:
        self.feed.add(("Start signal received from timing module", "info"))
        for card in self.cards.values():
            card.tacho.reset()
        if self.race.phase in (Phase.IDLE, Phase.COUNTDOWN):
            self.lights.set_all("green")
            self.race.go()
            if not self.audio.music_playing:
                self.audio.start_music()
        self._refresh_all()

    def reset_race(self) -> None:
        self.lights.set_all("off")
        self.celebration.close(notify=False)
        self.audio.stop_music()
        self.audio.stop_cheer()
        self.race.reset()
        for card in self.cards.values():
            card.tacho.reset()
        self.feed.add(("Race reset - back to the pit lane", "info"))
        self._refresh_all()

    def _on_lap(self, msg: LapMsg) -> None:
        if self.race.phase is Phase.IDLE:
            self.feed.add(("Lap received before race start - recording anyway", "warn"))
        elif self.race.phase is Phase.COUNTDOWN:
            self.lights.set_all("green")
        had_winner = self.race.winner is not None
        try:
            out = self.race.record_lap(msg.driver, msg.time_s, msg.lap)
        except LapRejected as exc:
            self.feed.add((str(exc), "warn"))
            return
        self.results.lap(self.race, out.lane, out.lap, out.time_s)

        tag = self._lane_tag(out.lane)
        badge = ("  FASTEST LAP", "fastest") if out.fastest_overall else \
                ("  PERSONAL BEST", "pb") if out.personal_best and out.lap > 1 else ("", "info")
        self.feed.add((f"LAP {out.lap}/{protocol.LAPS_PER_RACE}  ", "info"), (f"{self._name(out.lane):<14}", tag),
                      (f"{out.time_s:8.3f}s", "text"), badge)
        if out.driver_finished and not out.race_finished:
            self.feed.add((self._name(out.lane), tag), (" takes the chequered flag", "info"))
        self._refresh_all()
        if out.race_finished and not had_winner and self.race.winner is not None:
            self._finish()

    def _finish(self) -> None:
        lane = self.race.winner
        assert lane is not None
        winner, loser = self.race.drivers[lane], self.race.drivers[3 - lane]
        margin = loser.total - winner.total
        self.audio.stop_music()
        self.lights.set_all("off")
        self.feed.add(("⚑ WINNER  ", "win"), (winner.name, self._lane_tag(lane)),
                      (f"  {winner.total:.3f}s  (+{margin:.3f}s)", "text"))
        self.audio.start_cheer()
        self.after(500, lambda: self.celebration.show(winner.name, lane, winner.total, margin, winner.best_lap))
        self.toast("Race complete - press Save result to log the summary", "ok")

    def _announce_winner(self) -> None:
        self.audio.stop_cheer()
        lane = self.race.winner
        if lane is None or self._closing:
            return
        d = self.race.drivers[lane]
        speak(f"The winner is {d.name}, with a total time of {d.total:.3f} seconds.")

    def _race_in_progress(self, what: str) -> bool:
        """The firmware's race loop ignores commands until all laps are done."""
        if self.race.phase in (Phase.COUNTDOWN, Phase.RACING):
            self.toast(f"{what} is available once the race is finished or reset", "warn")
            return True
        return False

    def toggle_ghost(self) -> None:
        on = not self.ghost_on
        if on and self._race_in_progress("Ghost mode"):
            return
        self._send(protocol.cmd_ghost(on), "Ghost mode")
        self.ghost_on = on
        self.ghost_btn.set_active(on, "Ghost mode: ON" if on else "Ghost mode")
        if not on:
            self._zero_gauges()
        self.feed.add(("Ghost mode running - both cars auto-driven" if on else "Ghost mode stopped",
                       "fastest" if on else "info"))
        self._refresh_all()

    def _zero_gauges(self) -> None:
        # The firmware stops the motors on GHOST:0 but never sends a final <Rn,0, so zero the gauges here,
        # and ignore RPM frames already in flight so they can't push the needles back up.
        self._rpm_ignore_until = time.monotonic() + 0.5
        for card in self.cards.values():
            card.tacho.reset()

    def _end_track_modes(self) -> None:
        """A race and Ghost mode / Practice are mutually exclusive.

        Explicitly switch both off on the device (and on the buttons) before the
        grid forms, so app and track agree. Previously the buttons stayed "ON"
        through the race, and the first click afterwards sent GHOST:0 instead of
        re-enabling ghost mode.
        """
        for active, cmd, label in ((self.ghost_on, protocol.cmd_ghost(False), "Ghost mode"),
                                   (self.practice_on, protocol.cmd_practice(False), "Practice")):
            if not active:
                continue
            if self.link.connected:
                self.link.send(cmd)
            self.feed.add((f"{label} switched off for the race", "info"))
        if self.ghost_on:
            self._zero_gauges()
        self.ghost_on = self.practice_on = False
        self.ghost_btn.set_active(False, "Ghost mode")
        self.practice_btn.set_active(False, "Practice")

    def toggle_practice(self) -> None:
        on = not self.practice_on
        if on and self._race_in_progress("Practice"):
            return
        self._send(protocol.cmd_practice(on), "Practice")
        self.practice_on = on
        self.practice_btn.set_active(on, "Practice: ON" if on else "Practice")
        self.feed.add((f"Practice session {'started' if on else 'stopped'}", "warn" if on else "info"))

    def save_result(self) -> None:
        if not all(d.finished for d in self.race.drivers.values()):
            self.toast(f"Both drivers must complete {protocol.LAPS_PER_RACE} laps before saving", "warn")
            return
        if self.race.saved:
            self.toast("This race has already been saved", "info")
            return
        self.results.summary(self.race)
        self.race.saved = True
        self.toast(f"Race saved to {self.results.path.name}", "ok")
        self.feed.add(("Race summary saved to ", "info"), (self.results.path.name, "text"))
        if self.results_window is not None:
            self.results_window.refresh()

    def open_results_window(self) -> None:
        if self.results_window is not None and self.results_window.winfo_exists():
            self.results_window.refresh()
            self.results_window.lift()
            self.results_window.focus()
            return
        self.results_window = ResultsWindow(self)

    # ================================================================ audio
    def _on_volume(self, value: float) -> None:
        self.audio.set_volume(value)
        if self.audio.muted and value > 0:
            self.toggle_mute()

    def toggle_mute(self) -> None:
        muted = not self.audio.muted
        self.audio.set_muted(muted)
        self.mute_btn.configure(image=icon_image("mute" if muted else "speaker", 18,
                                                 T.DANGER if muted else T.TEXT_MUTED))

    # ================================================================ refresh
    def _refresh_all(self) -> None:
        phase = self.race.phase
        fastest = self.race.fastest_lap
        racing = phase is Phase.RACING
        for lane, card in self.cards.items():
            d = self.race.drivers[lane]
            card.update_from(self.race, racing, fastest)
            if self.ghost_on and phase in (Phase.IDLE, Phase.FINISHED):
                card.set_chip("ghost")
            elif self.race.winner == lane:
                card.set_chip("winner")
            elif d.finished:
                card.set_chip("finished")
            elif phase is Phase.COUNTDOWN:
                card.set_chip("grid")
            elif racing:
                card.set_chip("racing")
            else:
                card.set_chip("waiting")

        leader_laps = max(d.laps_done for d in self.race.drivers.values())
        caption, text, color, pill = {
            Phase.IDLE: ("PIT LANE", "READY TO RACE", T.TEXT, ("READY", T.TEXT_MUTED)),
            Phase.COUNTDOWN: ("STAND BY", "LIGHTS ON...", T.ACCENT, ("STARTING", T.ACCENT)),
            Phase.RACING: (f"{protocol.LAPS_PER_RACE}-LAP DUEL",
                           f"LAP {min(leader_laps + 1, protocol.LAPS_PER_RACE)} / {protocol.LAPS_PER_RACE}",
                           T.GO_GREEN, ("RACE ON", T.GO_GREEN)),
            Phase.FINISHED: ("RESULT", "CHEQUERED FLAG", T.AMBER, ("FINISHED", T.AMBER)),
        }[phase]
        if self.ghost_on and phase in (Phase.IDLE, Phase.FINISHED):
            caption, text, color, pill = "TRACK MODE", "GHOST RUN", T.PURPLE, ("GHOST MODE", T.PURPLE)
        self.phase_caption.configure(text=caption)
        self.phase_label.configure(text=text, text_color=color)
        self.race_pill.set(pill[0], pill[1], icon="ghost" if pill[0] == "GHOST MODE" else "flag")
        self.start_btn.configure(state="disabled" if phase is Phase.COUNTDOWN else "normal",
                                 text="RESTART RACE" if phase in (Phase.RACING, Phase.FINISHED) else "START RACE")
        if fastest:
            self.fastest_label.configure(text=f"{fastest[1]:.3f}")
            self.fastest_who.configure(text=self._name(fastest[0]), text_color=T.LANE_COLORS[fastest[0]])
        else:
            self.fastest_label.configure(text="--.---")
            self.fastest_who.configure(text="no laps yet", text_color=T.TEXT_FAINT)
        self._refresh_connection()

    # ================================================================ shutdown
    def _on_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.celebration.close(notify=False)
        self.lights.cancel()
        self.withdraw()
        self.audio.shutdown()
        self.sim.shutdown()
        self.ble.shutdown(timeout=4.0)
        self.destroy()
