"""Results history browser for saved ``raceresults_*.csv`` files."""

from __future__ import annotations

import os
from pathlib import Path
from tkinter import ttk
from typing import TYPE_CHECKING

import customtkinter as ctk

from .. import theme as T
from ..paths import RESULTS_DIR
from ..results import list_result_files, read_rows
from .widgets import IconButton, font, icon_image, section_label

if TYPE_CHECKING:
    from .app import RaceApp


def _style_treeview(root) -> None:
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("Pit.Treeview", background=T.SURFACE, fieldbackground=T.SURFACE, foreground=T.TEXT,
                    rowheight=30, borderwidth=0, font=(T.UI_FAMILY, 10))
    style.configure("Pit.Treeview.Heading", background=T.SURFACE_2, foreground=T.TEXT_MUTED, relief="flat",
                    borderwidth=0, font=(T.UI_SEMIBOLD, 10), padding=(8, 6))
    style.map("Pit.Treeview", background=[("selected", T.SURFACE_3)], foreground=[("selected", T.TEXT)])
    style.map("Pit.Treeview.Heading", background=[("active", T.SURFACE_3)])
    style.layout("Pit.Treeview", [("Pit.Treeview.treearea", {"sticky": "nswe"})])


class ResultsWindow(ctk.CTkToplevel):
    def __init__(self, app: RaceApp) -> None:
        super().__init__(app)
        self.app = app
        self.title("Results · Slot Car Duel")
        self.geometry("1080x640")
        self.minsize(860, 480)
        self.configure(fg_color=T.BG)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(250, app.apply_window_icon, self)
        _style_treeview(self)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, columnspan=2, padx=22, pady=(20, 12), sticky="ew")
        head.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(head, text="", image=icon_image("trophy", 30, T.AMBER)).grid(row=0, column=0, padx=(0, 12))
        ctk.CTkLabel(head, text="RESULTS HISTORY", font=font(T.DISPLAY_BOLD, 28, "bold"),
                     text_color=T.TEXT, anchor="w").grid(row=0, column=1, sticky="w")
        IconButton(head, "Open folder", "folder", self._open_folder, style="subtle", height=36,
                   width=150, icon_size=18).grid(row=0, column=2)

        side = ctk.CTkFrame(self, fg_color=T.SURFACE, corner_radius=16, width=280)
        side.grid(row=1, column=0, padx=(22, 10), pady=(0, 22), sticky="ns")
        side.grid_rowconfigure(1, weight=1)
        section_label(side, "Sessions").grid(row=0, column=0, padx=16, pady=(14, 4), sticky="w")
        self.file_list = ctk.CTkScrollableFrame(side, fg_color="transparent", width=250,
                                                scrollbar_button_color=T.SURFACE_3)
        self.file_list.grid(row=1, column=0, padx=6, pady=(0, 10), sticky="ns")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=1, padx=(10, 22), pady=(0, 22), sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)
        self.summary = ctk.CTkFrame(body, fg_color="transparent")
        self.summary.grid(row=0, column=0, sticky="ew")

        table_card = ctk.CTkFrame(body, fg_color=T.SURFACE, corner_radius=16)
        table_card.grid(row=1, column=0, pady=(12, 0), sticky="nsew")
        table_card.grid_columnconfigure(0, weight=1)
        table_card.grid_rowconfigure(0, weight=1)
        cols = ("time", "type", "driver", "lane", "lap", "lap_time", "total", "winner")
        heads = ("Time", "Record", "Driver", "Lane", "Lap", "Lap (s)", "Total (s)", "Winner")
        widths = (80, 110, 140, 50, 45, 75, 125, 110)
        self.tree = ttk.Treeview(table_card, columns=cols, show="headings", style="Pit.Treeview")
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="w" if c in ("driver", "winner", "type") else "center")
        self.tree.tag_configure("summary", background=T.mix(T.SURFACE, T.AMBER, 0.12), foreground=T.AMBER)
        self.tree.tag_configure("lane1", foreground=T.LANE_COLORS[1])
        self.tree.tag_configure("lane2", foreground=T.LANE_COLORS[2])
        self.tree.grid(row=0, column=0, padx=(10, 0), pady=10, sticky="nsew")
        sb = ctk.CTkScrollbar(table_card, command=self.tree.yview, button_color=T.SURFACE_3)
        sb.grid(row=0, column=1, padx=6, pady=10, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)

        self._buttons: dict[Path, ctk.CTkButton] = {}
        self.refresh()
        self.after(50, self.focus)

    def close(self) -> None:
        self.app.results_window = None
        self.destroy()

    def refresh(self) -> None:
        for b in self._buttons.values():
            b.destroy()
        self._buttons.clear()
        files = list_result_files()
        if not files:
            ctk.CTkLabel(self.file_list, text="No saved sessions yet", text_color=T.TEXT_FAINT).grid(pady=20)
            return
        for i, path in enumerate(files):
            stamp = path.stem.replace("raceresults_", "")
            label = f"{stamp[6:8]}/{stamp[4:6]}/{stamp[0:4]}   {stamp[9:11]}:{stamp[11:13]}" if len(stamp) >= 13 else stamp
            if path == self.app.results.path:
                label += "   • live"
            b = ctk.CTkButton(self.file_list, text=label, anchor="w", height=36, corner_radius=10,
                              fg_color="transparent", hover_color=T.SURFACE_3, text_color=T.TEXT_MUTED,
                              font=font(T.UI_SEMIBOLD, 13), image=icon_image("stopwatch", 16, T.TEXT_FAINT),
                              command=lambda p=path: self.load(p))
            b.grid(row=i, column=0, sticky="ew", pady=2)
            self._buttons[path] = b
        self.load(self.app.results.path if self.app.results.path in self._buttons else files[0])

    def load(self, path: Path) -> None:
        for p, b in self._buttons.items():
            b.configure(fg_color=T.SURFACE_3 if p == path else "transparent",
                        text_color=T.TEXT if p == path else T.TEXT_MUTED)
        self.tree.delete(*self.tree.get_children())
        for w in self.summary.winfo_children():
            w.destroy()
        try:
            rows = read_rows(path)
        except Exception as exc:
            self.app.toast(f"Could not read {path.name}: {exc}", "error")
            return

        races = [r for r in rows if r.get("record_type") == "RACE_SUMMARY"]
        laps = [r for r in rows if r.get("record_type") == "LAP"]
        fastest = min((float(r["lap_time_seconds"]) for r in laps if r.get("lap_time_seconds")), default=None)
        cards = [("RACES SAVED", str(len(races)), T.TEXT), ("LAPS LOGGED", str(len(laps)), T.TEXT),
                 ("FASTEST LAP", f"{fastest:.3f}s" if fastest else "--", T.PURPLE)]
        if races:
            cards.append(("LAST WINNER", races[-1].get("winner_name") or "--", T.AMBER))
        for i, (cap, val, color) in enumerate(cards):
            self.summary.grid_columnconfigure(i, weight=1, uniform="cards")
            c = ctk.CTkFrame(self.summary, fg_color=T.SURFACE, corner_radius=14)
            c.grid(row=0, column=i, padx=(0 if i == 0 else 6, 0), sticky="ew")
            ctk.CTkLabel(c, text=cap, font=font(T.UI_SEMIBOLD, 11), text_color=T.TEXT_FAINT).grid(
                row=0, column=0, padx=16, pady=(12, 0), sticky="w")
            ctk.CTkLabel(c, text=val, font=font(T.DIGITS_FAMILY, 26), text_color=color).grid(
                row=1, column=0, padx=16, pady=(0, 12), sticky="w")

        for r in rows:
            is_sum = r.get("record_type") == "RACE_SUMMARY"
            lane = r.get("driver_id", "")
            tag = "summary" if is_sum else f"lane{lane}" if lane in ("1", "2") else ""
            ts = r.get("timestamp", "")
            self.tree.insert("", "end", tags=(tag,), values=(
                ts[11:19] if len(ts) >= 19 else ts,
                "RACE SUMMARY" if is_sum else r.get("record_type", ""),
                r.get("notes", "") if is_sum else r.get("driver_name", ""),
                lane, r.get("lap", ""), r.get("lap_time_seconds", ""),
                r.get("total_time_seconds", "").replace("|", "  |  "), r.get("winner_name", ""),
            ))

    def _open_folder(self) -> None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(RESULTS_DIR)  # type: ignore[attr-defined]
        except Exception as exc:
            self.app.toast(f"Could not open folder: {exc}", "error")
