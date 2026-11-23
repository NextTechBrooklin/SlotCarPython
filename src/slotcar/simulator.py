"""A software stand-in for the timing hardware.

It speaks exactly the same wire protocol as the RN4870 firmware: it reacts to
``START_RACE`` / ``PRACTICE:n`` / ``GHOST:n`` and streams ``<Rn,`` RPM and
``<Cn,`` lap frames back as raw bytes, which go through the same
:class:`~slotcar.protocol.FrameAssembler` as real BLE notifications. Useful
for demos and for developing the UI without a track.
"""

from __future__ import annotations

import math
import queue
import random
import threading
import time

from . import protocol
from .ble import ConnState, LinkEvent


class _GhostRamp:
    """Port of the firmware's ghost-mode PWM ramp (ghost.c, Ghost_RampStep).

    Starts at 70 %, climbs in 2 % steps every 100 ms to a random target in
    70-85 %, falls back to 70 %, picks a new target, repeats.
    """

    MIN, MAX, STEP = 70, 85, 2

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.cur = self.MIN
        self.target = self._rand()
        self.up = True

    def _rand(self) -> int:
        return self.rng.randint(self.MIN, self.MAX)

    def step(self) -> None:
        if self.up:
            if self.cur + self.STEP >= self.target:
                self.cur, self.up = self.target, False
            else:
                self.cur += self.STEP
        elif self.cur <= self.MIN + self.STEP:
            self.cur, self.up, self.target = self.MIN, True, self._rand()
        else:
            self.cur -= self.STEP


class SimulatedLink:
    device_name = "Track Simulator"

    def __init__(self, events: queue.Queue) -> None:
        self.events = events
        self.state = ConnState.DISCONNECTED
        self._assembler = protocol.FrameAssembler()
        self._stop = threading.Event()
        self._mode = "idle"  # idle | race | practice
        self._laps = {1: protocol.LAPS_PER_RACE, 2: protocol.LAPS_PER_RACE}
        self._ghost = False
        self._ghost_ramps: dict[int, _GhostRamp] = {}
        self._ghost_started = False
        self._rng = random.Random()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def connected(self) -> bool:
        return self.state is ConnState.CONNECTED

    scanning = False

    def _emit(self, kind, data=None, level="info") -> None:
        self.events.put(LinkEvent(kind, data, level))

    # ------------------------------------------------------------------ link API
    def connect(self, *_args) -> None:
        self.state = ConnState.CONNECTED
        self._emit("state", self.state)
        self._emit("log", "Simulator connected - no hardware required", "ok")
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="simulator", daemon=True)
        self._thread.start()

    def disconnect(self) -> None:
        self._stop.set()
        self.state = ConnState.DISCONNECTED
        self._emit("state", self.state)
        self._emit("log", "Simulator disconnected")

    def shutdown(self, timeout: float = 1.0) -> None:
        self._stop.set()

    def send(self, payload: bytes) -> None:
        self._emit("log", f"TX {payload.decode('ascii', 'replace')!r}  [{payload.hex(' ')}]", "tx")
        cmd = payload.decode("ascii", "replace").strip().upper()
        with self._lock:
            # Like the firmware, ghost mode is a blocking loop that only listens for GHOST:0,
            # and a running race (Race_Run) doesn't take new commands until it finishes.
            if self._ghost and not cmd.startswith("GHOST:"):
                self._emit("log", f"Simulator: {cmd!r} ignored - ghost mode running (send GHOST:0 first)", "warn")
                return
            if self._race_running() and cmd != "START_RACE":
                self._emit("log", f"Simulator: {cmd!r} ignored - race in progress", "warn")
                return
            if cmd == "START_RACE":
                self._mode = "race"
                self._race_start = time.monotonic()
                self._laps = {1: 0, 2: 0}
                self._lap_started = {1: self._race_start, 2: self._race_start}
                self._lap_target = {1: self._lap_time(1), 2: self._lap_time(2)}
            elif cmd.startswith("PRACTICE:"):
                self._mode = "idle" if cmd.endswith(":0") else "practice"
            elif cmd.startswith("GHOST:"):
                on = not cmd.endswith(":0")
                if on and not self._ghost:
                    self._ghost_ramps = {1: _GhostRamp(self._rng), 2: _GhostRamp(self._rng)}
                    self._ghost_started = False
                self._ghost = on
                self._emit("log", "Simulator: ghost mode running - both cars auto-driven at 70-85 %"
                           if on else "Simulator: ghost mode stopped, motors off")

    def _race_running(self) -> bool:
        return self._mode == "race" and any(n < protocol.LAPS_PER_RACE for n in self._laps.values())

    # ------------------------------------------------------------- simulation
    @staticmethod
    def _lap_time(lane: int) -> float:
        base = 5.6 if lane == 1 else 5.8
        return round(random.gauss(base, 0.45), 3)

    def _rx(self, text: str) -> None:
        """Deliver bytes exactly as the firmware would: '\\n\\r' terminated."""
        raw = (text + "\n\r").encode("ascii")
        self._emit("log", f"RX {raw.decode('ascii')!r}  [{raw.hex(' ')}]", "rx")
        for frame in self._assembler.feed(raw.decode("ascii")):
            self._emit("frame", frame)

    def _run(self) -> None:
        def target_zero(lane: int) -> bool:
            return self._mode == "race" and self._laps[lane] >= protocol.LAPS_PER_RACE

        rpm = {1: 0.0, 2: 0.0}
        resting = {1: True, 2: True}
        phase = {1: 0.0, 2: 1.3}
        was_ghost = False
        while not self._stop.wait(0.1):  # 100 ms, the firmware's ramp step interval
            now = time.monotonic()
            with self._lock:
                if self._ghost:
                    self._ghost_tick(rpm)
                    was_ghost = True
                    continue
                if was_ghost:
                    # Firmware zeroes the motors on GHOST:0 but sends no final RPM frame.
                    rpm = {1: 0.0, 2: 0.0}
                    resting = {1: True, 2: True}
                    was_ghost = False
                mode = self._mode
                for lane in (1, 2):
                    on_track = mode == "practice" or (mode == "race" and self._laps[lane] < protocol.LAPS_PER_RACE)
                    if on_track:
                        phase[lane] += 0.35 + random.random() * 0.1
                        # Throttle profile: straights (high) and corners (low).
                        target = 62 + 30 * abs(math.sin(phase[lane])) + random.uniform(-4, 4)
                    else:
                        target = 0.0
                    rpm[lane] += (target - rpm[lane]) * 0.35
                    if mode == "race" and on_track and now - self._lap_started[lane] >= self._lap_target[lane]:
                        lap_s = self._lap_target[lane]
                        self._laps[lane] += 1
                        self._lap_started[lane] = now
                        self._lap_target[lane] = self._lap_time(lane)
                        self._rx(f"<C{lane},{lap_s:.3f}")
                if mode == "race" and all(n >= protocol.LAPS_PER_RACE for n in self._laps.values()):
                    if rpm[1] < 1 and rpm[2] < 1:
                        self._mode = "idle"
            for lane in (1, 2):
                if rpm[lane] < 0.5 and (mode == "idle" or target_zero(lane)):
                    rpm[lane] = 0.0
                    if resting[lane]:
                        continue
                    resting[lane] = True  # send one final 0 then go quiet
                else:
                    resting[lane] = False
                self._rx(f"<R{lane},{max(0.0, min(100.0, rpm[lane])):.0f}")

    def _ghost_tick(self, rpm: dict[int, float]) -> None:
        """One 100 ms ghost-mode step: like the firmware, send RPM only when it changes."""
        if not self._ghost_started:
            self._ghost_started = True
            for lane, ramp in self._ghost_ramps.items():
                rpm[lane] = ramp.cur
                self._rx(f"<R{lane},{ramp.cur}")
            return
        for lane, ramp in self._ghost_ramps.items():
            before = ramp.cur
            ramp.step()
            rpm[lane] = ramp.cur
            if ramp.cur != before:
                self._rx(f"<R{lane},{ramp.cur}")
