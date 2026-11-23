"""Wire protocol between the app and the slot car timing hardware.

This module is pure Python with no BLE or GUI dependencies so it can be unit
tested in isolation. See ``protocol.md`` in the project root for the full
human-readable specification.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Union

# ---------------------------------------------------------------------------
# GATT profile: Microchip RN4870 "Transparent UART"
# ---------------------------------------------------------------------------
UART_SERVICE_UUID = "49535343-fe7d-4ae5-8fa9-9fafd205e455"
UART_TX_NOTIFY_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"   # device -> app
UART_RX_WRITE_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"    # app -> device
REQUESTED_MTU = 247

LAPS_PER_RACE = 3
RPM_MAX = 100.0

# ---------------------------------------------------------------------------
# Outbound commands (app -> device)
# ---------------------------------------------------------------------------
GHOST_ON_VALUE = 5
PRACTICE_ON_VALUE = 45


def cmd_start_race() -> bytes:
    """``START_RACE`` - sent with *no* terminator (matches existing firmware)."""
    return b"START_RACE"


def cmd_ghost(on: bool) -> bytes:
    return f"GHOST:{GHOST_ON_VALUE if on else 0}\r\n".encode("ascii")


def cmd_practice(on: bool) -> bytes:
    return f"PRACTICE:{PRACTICE_ON_VALUE if on else 0}\r\n".encode("ascii")


# ---------------------------------------------------------------------------
# Inbound messages (device -> app)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class StartMsg:
    """Device reports the race has started."""


@dataclass(frozen=True)
class LapMsg:
    """A completed lap.

    ``lap`` is ``None`` for the native ``<Cn,`` format, meaning the app should
    auto-number the lap; the CSV ``LAP`` message carries an explicit lap number.
    """

    driver: int
    time_s: float
    lap: int | None = None


@dataclass(frozen=True)
class RpmMsg:
    driver: int
    rpm: float


Message = Union[StartMsg, LapMsg, RpmMsg]

_DRIVER_ALIASES = {
    "1": 1, "2": 2,
    "left": 1, "right": 2,
    "lane1": 1, "lane2": 2,
    "car1": 1, "car2": 2,
}

_NATIVE_RE = re.compile(r"^<([CR])([12]),\s*([-+]?(?:\d+\.?\d*|\.\d+))\s*$", re.IGNORECASE)


def normalize_driver(value: Any) -> int:
    """Map any accepted driver/lane identifier to ``1`` or ``2``."""
    if isinstance(value, bool):
        raise ValueError(f"unknown driver: {value!r}")
    if isinstance(value, int):
        if value in (1, 2):
            return value
        raise ValueError(f"unknown driver: {value!r}")
    key = str(value).strip().lower().replace(" ", "")
    if key not in _DRIVER_ALIASES:
        raise ValueError(f"unknown driver: {value!r}")
    return _DRIVER_ALIASES[key]


def parse_frame(frame: str) -> Message | None:
    """Parse one complete frame (terminator already removed).

    Formats are tried in priority order: native prefix, then CSV text.
    Returns ``None`` for anything unrecognised or malformed.
    """
    text = frame.strip()
    if not text:
        return None

    # 1) Native prefix:  <C1,14.752   <R2,67
    m = _NATIVE_RE.match(text)
    if m:
        kind, driver, value = m.group(1).upper(), int(m.group(2)), float(m.group(3))
        if kind == "C":
            return LapMsg(driver=driver, time_s=value) if value > 0 else None
        return RpmMsg(driver=driver, rpm=value)

    # 2) CSV text:  START | LAP,1,2,14752 | RPM,2,67.5
    parts = [p.strip() for p in text.split(",")]
    head = parts[0].upper()
    try:
        if len(parts) == 1 and head == "START":
            return StartMsg()
        if len(parts) == 4 and head == "LAP":
            return _lap(parts[1], parts[2], parts[3])
        if len(parts) == 3 and head == "RPM":
            return RpmMsg(driver=normalize_driver(parts[1]), rpm=float(parts[2]))
    except (ValueError, TypeError):
        return None
    return None


def _lap(driver: Any, lap: Any, time_ms: Any) -> LapMsg | None:
    lap_num = int(lap)
    ms = int(float(time_ms))
    if not 1 <= lap_num <= LAPS_PER_RACE or ms <= 0:
        return None
    return LapMsg(driver=normalize_driver(driver), time_s=ms / 1000.0, lap=lap_num)


class FrameAssembler:
    """Re-assembles BLE notification chunks into line frames.

    A frame ends at any CR or LF. That accepts the firmware's ``\\n\\r`` as well
    as ``\\r\\n``, ``\\n`` and ``\\r``; the empty "frames" produced between the
    two terminator characters are discarded.
    """

    MAX_BUFFER = 1024  # protect against a device that never sends a terminator

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, chunk: str) -> list[str]:
        self._buf += chunk
        frames: list[str] = []
        start = 0
        for i, ch in enumerate(self._buf):
            if ch in "\r\n":
                if i > start:
                    frames.append(self._buf[start:i])
                start = i + 1
        self._buf = self._buf[start:]
        if len(self._buf) > self.MAX_BUFFER:
            self._buf = self._buf[-self.MAX_BUFFER:]
        return frames

    @property
    def pending(self) -> str:
        return self._buf

    def clear(self) -> None:
        self._buf = ""
