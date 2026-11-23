"""'Pit Wall' window: scan, connect and troubleshoot the Bluetooth LE link."""

from __future__ import annotations

from typing import TYPE_CHECKING

import customtkinter as ctk

from .. import theme as T
from ..ble import ConnState, DeviceInfo, is_slot_device
from .widgets import IconButton, Pill, font, icon_image, section_label

if TYPE_CHECKING:
    from .app import RaceApp

LOG_COLORS = {
    "info": T.TEXT_MUTED, "ok": T.GO_GREEN, "warn": T.AMBER, "error": T.DANGER,
    "rx": "#7dd3fc", "tx": "#fda4af", "time": T.TEXT_FAINT,
}


def signal_bars(rssi: int | None) -> tuple[str, str]:
    if rssi is None:
        return "▁▁▁▁", T.TEXT_FAINT
    bars = 4 if rssi > -60 else 3 if rssi > -70 else 2 if rssi > -80 else 1
    glyphs = "▂▄▆█"
    color = T.GO_GREEN if bars >= 3 else T.AMBER if bars == 2 else T.DANGER
    return glyphs[:bars] + "▁" * (4 - bars), color


class DeviceRow(ctk.CTkFrame):
    def __init__(self, master, info: DeviceInfo, on_select, on_activate) -> None:
        super().__init__(master, fg_color=T.SURFACE_2, corner_radius=12, border_width=1, border_color=T.BORDER,
                         cursor="hand2")
        self.info = info
        self.grid_columnconfigure(1, weight=1)
        self._icon = ctk.CTkLabel(self, text="", image=icon_image("bluetooth", 18, T.TEXT_MUTED))
        self._icon.grid(row=0, column=0, rowspan=2, padx=(12, 10), pady=8)
        self._name = ctk.CTkLabel(self, text="", font=font(T.UI_SEMIBOLD, 14), anchor="w", height=18)
        self._name.grid(row=0, column=1, sticky="w", pady=(8, 0))
        self._addr = ctk.CTkLabel(self, text="", font=font(T.MONO_FAMILY, 11), text_color=T.TEXT_FAINT,
                                  anchor="w", height=16)
        self._addr.grid(row=1, column=1, sticky="w", pady=(0, 8))
        self._badge = ctk.CTkLabel(self, text=" UART ", font=font(T.UI_SEMIBOLD, 10), fg_color=T.mix(T.SURFACE_2, T.GO_GREEN, 0.25),
                                   text_color=T.GO_GREEN, corner_radius=6, height=18)
        self._bars = ctk.CTkLabel(self, text="", font=font("Segoe UI Symbol", 13), width=48)
        self._bars.grid(row=0, column=3, rowspan=2, padx=(4, 4))
        self._rssi = ctk.CTkLabel(self, text="", font=font(T.MONO_FAMILY, 10), text_color=T.TEXT_FAINT, width=52)
        self._rssi.grid(row=0, column=4, rowspan=2, padx=(0, 12))
        for w in [self, *self.winfo_children()]:
            w.bind("<Button-1>", lambda _e: on_select(self))
            w.bind("<Double-Button-1>", lambda _e: on_activate(self))
        self.update_info(info)

    def update_info(self, info: DeviceInfo) -> None:
        self.info = info
        self._name.configure(text=info.name or "Unnamed device",
                             text_color=T.TEXT if info.name else T.TEXT_MUTED)
        self._addr.configure(text=info.address)
        if info.is_uart:
            self._badge.grid(row=0, column=2, rowspan=2, padx=4)
        else:
            self._badge.grid_remove()
        bars, color = signal_bars(info.rssi)
        self._bars.configure(text=bars, text_color=color)
        self._rssi.configure(text=f"{info.rssi} dBm" if info.rssi is not None else "")

    def set_selected(self, selected: bool) -> None:
        self.configure(border_color=T.LANE_COLORS[1] if selected else T.BORDER,
                       fg_color=T.mix(T.SURFACE_2, T.LANE_COLORS[1], 0.08) if selected else T.SURFACE_2)
        self._icon.configure(image=icon_image("bluetooth", 18, T.LANE_COLORS[1] if selected else T.TEXT_MUTED))

    @property
    def sort_key(self):
        return (not is_slot_device(self.info.name), not self.info.is_uart, not self.info.name,
                -(self.info.rssi or -200))


class BleWindow(ctk.CTkToplevel):
    def __init__(self, app: RaceApp) -> None:
        super().__init__(app)
        self.app = app
        self.title("Pit Wall · Bluetooth LE")
        self.geometry("600x760")
        self.minsize(520, 640)
        self.configure(fg_color=T.BG)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self.grid_rowconfigure(5, weight=1)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(250, app.apply_window_icon, self)

        self.rows: dict[str, DeviceRow] = {}
        self.selected: DeviceRow | None = None

        # -- header ---------------------------------------------------------
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, padx=22, pady=(20, 10), sticky="ew")
        head.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(head, text="", image=icon_image("bluetooth", 30, T.LANE_COLORS[1])).grid(
            row=0, column=0, rowspan=2, padx=(0, 12))
        ctk.CTkLabel(head, text="PIT WALL", font=font(T.DISPLAY_BOLD, 28, "bold"), text_color=T.TEXT,
                     anchor="w", height=30).grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(head, text="Connect the RN4870 timing module over Bluetooth LE",
                     font=font(size=12), text_color=T.TEXT_MUTED, anchor="w", height=16).grid(
            row=1, column=1, sticky="w")

        # -- connection card ------------------------------------------------
        conn = ctk.CTkFrame(self, fg_color=T.SURFACE, corner_radius=16, border_width=1, border_color=T.BORDER)
        conn.grid(row=1, column=0, padx=22, pady=(4, 12), sticky="ew")
        conn.grid_columnconfigure(1, weight=1)
        self.state_pill = Pill(conn)
        self.state_pill.grid(row=0, column=0, padx=(16, 10), pady=16)
        self.device_label = ctk.CTkLabel(conn, text="", font=font(T.UI_SEMIBOLD, 14), anchor="w")
        self.device_label.grid(row=0, column=1, sticky="w")
        self.connect_btn = IconButton(conn, "Connect", "plug", self._toggle_connect, style="primary",
                                      height=40, width=150)
        self.connect_btn.grid(row=0, column=2, padx=16, pady=12)

        # -- scan controls --------------------------------------------------
        scan = ctk.CTkFrame(self, fg_color="transparent")
        scan.grid(row=2, column=0, padx=22, pady=(4, 6), sticky="ew")
        scan.grid_columnconfigure(1, weight=1)
        self.scan_btn = IconButton(scan, "Scan", "radar", self._toggle_scan, style="subtle", height=38, width=130)
        self.scan_btn.grid(row=0, column=0)
        self.progress = ctk.CTkProgressBar(scan, mode="determinate", height=4, progress_color=T.LANE_COLORS[1],
                                           fg_color=T.SURFACE_2)
        self.progress.grid(row=0, column=1, padx=14, sticky="ew")
        self.progress.set(0)
        # On: only devices named "Slot..."; off: every device that advertises a name.
        self.slot_only = ctk.CTkSwitch(scan, text="Slot* devices only", font=font(size=12),
                                       text_color=T.TEXT_MUTED, progress_color=T.LANE_COLORS[1],
                                       command=self._relayout)
        self.slot_only.select()
        self.slot_only.grid(row=0, column=2)

        self.device_list = ctk.CTkScrollableFrame(self, fg_color=T.SURFACE, corner_radius=16,
                                                  scrollbar_button_color=T.SURFACE_3)
        self.device_list.grid(row=3, column=0, padx=22, pady=(6, 12), sticky="nsew")
        self.device_list.grid_columnconfigure(0, weight=1)
        self.empty_label = ctk.CTkLabel(self.device_list, text="Press Scan to look for the timing module.",
                                        font=font(size=13), text_color=T.TEXT_FAINT)
        self.empty_label.grid(row=0, column=0, pady=40)

        # -- diagnostics ----------------------------------------------------
        diag = ctk.CTkFrame(self, fg_color="transparent")
        diag.grid(row=4, column=0, padx=22, pady=(4, 6), sticky="ew")
        diag.grid_columnconfigure(0, weight=1)
        section_label(diag, "Diagnostics log").grid(row=0, column=0, sticky="w")
        self.raw_switch = ctk.CTkSwitch(diag, text="Raw RX/TX", font=font(size=12), text_color=T.TEXT_MUTED,
                                        progress_color=T.LANE_COLORS[1], command=self._reload_log)
        self.raw_switch.grid(row=0, column=1, padx=(0, 10))
        self.sim_btn = IconButton(diag, "Simulator", "car", app.toggle_simulator, style="subtle", height=32,
                                  width=130, icon_size=18, active_color=T.LANE_COLORS[2])
        self.sim_btn.grid(row=0, column=2, padx=(0, 8))
        IconButton(diag, "Clear", "close", self._clear_log, style="subtle", height=32, width=90,
                   icon_size=14).grid(row=0, column=3)

        self.log = ctk.CTkTextbox(self, fg_color=T.SURFACE, corner_radius=16, font=font(T.MONO_FAMILY, 11),
                                  wrap="none", text_color=T.TEXT_MUTED, scrollbar_button_color=T.SURFACE_3)
        self.log.grid(row=5, column=0, padx=22, pady=(6, 22), sticky="nsew")
        for tag, color in LOG_COLORS.items():
            self.log.tag_config(tag, foreground=color)

        self._reload_log()
        self.on_state(app.link.state, app.link.device_name)
        self.on_scan_state(app.ble.scanning)
        self.after(50, self.focus)

    # ------------------------------------------------------------- callbacks
    def close(self) -> None:
        self.app.ble.stop_scan()
        self.app.ble_window = None
        self.destroy()

    def _toggle_scan(self) -> None:
        if self.app.ble.scanning:
            self.app.ble.stop_scan()
        else:
            for row in self.rows.values():
                row.destroy()
            self.rows.clear()
            self.selected = None
            self._relayout()
            self.app.ble.scan()
            self.on_scan_state(True)

    def _toggle_connect(self) -> None:
        link = self.app.link
        if link.state is not ConnState.DISCONNECTED:
            self.app.disconnect()
            return
        if self.selected is None:
            self.app.toast("Select a device from the scan list first", "warn")
            return
        self.app.connect_ble(self.selected.info)

    def _select(self, row: DeviceRow) -> None:
        if self.selected is not None and self.selected.winfo_exists():
            self.selected.set_selected(False)
        self.selected = row
        row.set_selected(True)

    def _activate(self, row: DeviceRow) -> None:
        self._select(row)
        if self.app.link.state is ConnState.DISCONNECTED:
            self.app.connect_ble(row.info)

    # ------------------------------------------------------- app -> window
    def on_scan_state(self, scanning: bool) -> None:
        if scanning:
            self.scan_btn.set_active(True, "Stop")
            self.progress.configure(mode="indeterminate", progress_color=T.LANE_COLORS[1])
            self.progress.start()
            self._relayout()
        else:
            self.scan_btn.set_active(False, "Scan")
            self.progress.stop()
            self.progress.configure(mode="determinate", progress_color=T.SURFACE_2)
            self.progress.set(0)

    def on_scan_done(self) -> None:
        self.on_scan_state(False)
        if not any(r.winfo_ismapped() for r in self.rows.values()):
            hidden = len(self.rows)
            msg = "No devices named \"Slot...\" found. Is the timing module powered on?"
            if self.slot_only.get() and hidden:
                msg += f"\n{hidden} other device(s) hidden - turn off \"Slot* devices only\" to see them."
            self.empty_label.configure(text=msg if self.slot_only.get()
                                       else "No devices found. Is the timing module powered on?")

    def on_scan_result(self, info: DeviceInfo) -> None:
        row = self.rows.get(info.address)
        if row is None:
            row = DeviceRow(self.device_list, info, self._select, self._activate)
            self.rows[info.address] = row
        else:
            row.update_info(info)  # names often arrive in a later scan response
        if self.selected is None and (is_slot_device(info.name) or info.is_uart):
            self._select(row)
        self._relayout()

    def _relayout(self) -> None:
        slot_only = bool(self.slot_only.get())
        visible = [r for r in self.rows.values()
                   if (is_slot_device(r.info.name) if slot_only else bool(r.info.name))]
        for r in self.rows.values():
            r.grid_forget()
        if self.selected is not None and self.selected not in visible:
            self.selected.set_selected(False)  # never connect to a device the user can't see
            self.selected = None
        if visible:
            self.empty_label.grid_forget()
        else:
            self.empty_label.configure(text="Scanning..." if self.app.ble.scanning
                                       else "Press Scan to look for the timing module.")
            self.empty_label.grid(row=0, column=0, pady=40)
        for i, r in enumerate(sorted(visible, key=lambda r: r.sort_key)):
            r.grid(row=i, column=0, padx=8, pady=4, sticky="ew")

    def on_state(self, state: ConnState, name: str) -> None:
        sim = self.app.link is self.app.sim
        if state is ConnState.CONNECTED:
            self.state_pill.set("CONNECTED", T.GO_GREEN)
            self.device_label.configure(text=name, text_color=T.TEXT)
            self.connect_btn.configure(text="Disconnect", fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER,
                                       text_color="#ffffff", image=icon_image("unplug", 20, "#ffffff"), state="normal")
        elif state is ConnState.CONNECTING:
            self.state_pill.set("CONNECTING", T.AMBER)
            self.device_label.configure(text=name, text_color=T.TEXT_MUTED)
            self.connect_btn.configure(text="Cancel", fg_color=T.SURFACE_3, hover_color=T.BORDER_STRONG,
                                       text_color=T.TEXT, image=icon_image("close", 16, T.TEXT), state="normal")
        else:
            self.state_pill.set("OFFLINE", T.TEXT_MUTED)
            self.device_label.configure(text="No timing module connected", text_color=T.TEXT_FAINT)
            self.connect_btn.configure(text="Connect", fg_color=T.GO_GREEN, hover_color=T.GO_GREEN_HOVER,
                                       text_color="#04130b", image=icon_image("plug", 20, "#04130b"), state="normal")
        self.sim_btn.set_active(sim and state is ConnState.CONNECTED,
                                "Stop Sim" if sim and state is ConnState.CONNECTED else "Simulator")

    # ---------------------------------------------------------------- log
    def _visible(self, level: str) -> bool:
        return bool(self.raw_switch.get()) or level not in ("rx", "tx")

    def on_log(self, stamp: str, text: str, level: str) -> None:
        if not self._visible(level):
            return
        at_end = self.log.yview()[1] > 0.98
        self.log.insert("end", f"{stamp}  ", "time")
        self.log.insert("end", text + "\n", level)
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > 800:
            self.log.delete("1.0", f"{lines - 800}.0")
        if at_end:
            self.log.see("end")

    def _reload_log(self) -> None:
        self.log.delete("1.0", "end")
        for stamp, text, level in self.app.log_history:
            if self._visible(level):
                self.log.insert("end", f"{stamp}  ", "time")
                self.log.insert("end", text + "\n", level)
        self.log.see("end")

    def _clear_log(self) -> None:
        self.app.log_history.clear()
        self.log.delete("1.0", "end")
