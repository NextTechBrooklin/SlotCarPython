"""Race model: drivers, laps, phases and winner logic (no GUI code)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .protocol import LAPS_PER_RACE


class Phase(Enum):
    IDLE = "idle"
    COUNTDOWN = "countdown"
    RACING = "racing"
    FINISHED = "finished"


@dataclass
class Driver:
    lane: int
    name: str
    laps: dict[int, float] = field(default_factory=dict)
    finished_at: datetime | None = None

    @property
    def total(self) -> float:
        return sum(self.laps.values())

    @property
    def laps_done(self) -> int:
        return len(self.laps)

    @property
    def finished(self) -> bool:
        return self.laps_done >= LAPS_PER_RACE

    @property
    def best_lap(self) -> float | None:
        return min(self.laps.values()) if self.laps else None


@dataclass(frozen=True)
class LapOutcome:
    lane: int
    lap: int
    time_s: float
    personal_best: bool
    fastest_overall: bool
    driver_finished: bool
    race_finished: bool


class LapRejected(Exception):
    pass


class Race:
    def __init__(self, name1: str = "Driver 1", name2: str = "Driver 2") -> None:
        self.drivers: dict[int, Driver] = {1: Driver(1, name1), 2: Driver(2, name2)}
        self.phase = Phase.IDLE
        self.winner: int | None = None
        self.saved = False

    # -- lifecycle -------------------------------------------------------
    def set_names(self, name1: str, name2: str) -> None:
        self.drivers[1].name = name1 or "Driver 1"
        self.drivers[2].name = name2 or "Driver 2"

    def reset(self) -> None:
        for d in self.drivers.values():
            d.laps.clear()
            d.finished_at = None
        self.phase = Phase.IDLE
        self.winner = None
        self.saved = False

    def arm(self) -> None:
        """Clear times and enter the start-light countdown."""
        self.reset()
        self.phase = Phase.COUNTDOWN

    def go(self) -> None:
        if self.phase in (Phase.IDLE, Phase.COUNTDOWN):
            self.phase = Phase.RACING

    # -- timing ----------------------------------------------------------
    @property
    def fastest_lap(self) -> tuple[int, float] | None:
        best: tuple[int, float] | None = None
        for lane, d in self.drivers.items():
            if d.best_lap is not None and (best is None or d.best_lap < best[1]):
                best = (lane, d.best_lap)
        return best

    def record_lap(self, lane: int, time_s: float, lap: int | None = None) -> LapOutcome:
        if lane not in self.drivers:
            raise LapRejected(f"unknown lane {lane}")
        driver = self.drivers[lane]
        if lap is None:
            lap = driver.laps_done + 1
        if not 1 <= lap <= LAPS_PER_RACE:
            raise LapRejected(f"{driver.name}: lap {lap} is outside 1-{LAPS_PER_RACE}")
        if lap not in driver.laps and driver.finished:
            raise LapRejected(f"{driver.name} has already completed {LAPS_PER_RACE} laps")

        prev_best = driver.best_lap
        prev_fastest = self.fastest_lap
        driver.laps[lap] = time_s
        if self.phase in (Phase.IDLE, Phase.COUNTDOWN):
            self.phase = Phase.RACING

        if driver.finished and driver.finished_at is None:
            driver.finished_at = datetime.now()

        race_finished = all(d.finished for d in self.drivers.values())
        if race_finished and self.winner is None:
            d1, d2 = self.drivers[1], self.drivers[2]
            self.winner = 1 if d1.total <= d2.total else 2
            self.phase = Phase.FINISHED

        return LapOutcome(
            lane=lane,
            lap=lap,
            time_s=time_s,
            personal_best=prev_best is None or time_s < prev_best,
            fastest_overall=prev_fastest is None or time_s < prev_fastest[1],
            driver_finished=driver.finished,
            race_finished=race_finished,
        )

    def gap(self, lane: int) -> float | None:
        """Time gap to the other driver after the same number of completed laps."""
        me, other = self.drivers[lane], self.drivers[3 - lane]
        n = min(me.laps_done, other.laps_done)
        if n == 0:
            return None
        mine = sum(me.laps[i] for i in sorted(me.laps)[:n])
        theirs = sum(other.laps[i] for i in sorted(other.laps)[:n])
        return mine - theirs
