"""CSV persistence for lap times and race summaries.

The column layout is identical to the original Slot Car Duel app so existing
``raceresults_*.csv`` files remain readable.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from .paths import RESULTS_DIR
from .race import Race

HEADER = [
    "timestamp", "record_type", "driver_name", "driver_id", "lap",
    "lap_time_seconds", "total_time_seconds", "winner_name", "notes",
]


class ResultsLog:
    def __init__(self, directory: Path = RESULTS_DIR) -> None:
        self.directory = directory
        self.path = directory / f"raceresults_{datetime.now():%Y%m%d_%H%M%S}.csv"

    def _write(self, row: list) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists()
        with self.path.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(HEADER)
            w.writerow(row)

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    def lap(self, race: Race, lane: int, lap: int, time_s: float) -> None:
        name = race.drivers[lane].name
        self._write([self._now(), "LAP", name, lane, lap, f"{time_s:.3f}", "", "", ""])

    def summary(self, race: Race) -> None:
        d1, d2 = race.drivers[1], race.drivers[2]
        winner = race.drivers[race.winner].name if race.winner else ""
        self._write([
            self._now(), "RACE_SUMMARY", "", "", "", "",
            f"{d1.total:.3f}|{d2.total:.3f}", winner, f"{d1.name} vs {d2.name}",
        ])


def list_result_files(directory: Path = RESULTS_DIR) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob("raceresults_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
