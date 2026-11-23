"""The simulator's ghost mode must behave like the firmware (ghost.c)."""

import queue
import time

from slotcar import protocol
from slotcar.simulator import SimulatedLink, _GhostRamp


def frames(events):
    out = []
    while True:
        try:
            ev = events.get_nowait()
        except queue.Empty:
            return out
        if ev.kind == "frame":
            out.append(protocol.parse_frame(ev.data))


def test_ghost_ramp_stays_in_firmware_range():
    import random
    r = _GhostRamp(random.Random(1))
    seen = set()
    for _ in range(500):
        r.step()
        seen.add(r.cur)
    assert min(seen) == 70 and max(seen) <= 85 and len(seen) > 4


def test_ghost_mode_drives_both_cars_without_laps_and_ignores_start_race():
    events = queue.Queue()
    sim = SimulatedLink(events)
    sim.connect()
    try:
        sim.send(protocol.cmd_ghost(True))
        time.sleep(1.2)
        sim.send(protocol.cmd_start_race())       # firmware ignores this while ghosting
        time.sleep(0.6)
        got = frames(events)
        rpms = [m for m in got if isinstance(m, protocol.RpmMsg)]
        assert {m.driver for m in rpms} == {1, 2}
        assert all(70 <= m.rpm <= 85 for m in rpms)
        assert not any(isinstance(m, protocol.LapMsg) for m in got)

        sim.send(protocol.cmd_ghost(False))
        time.sleep(0.3)
        frames(events)
        time.sleep(0.5)
        assert frames(events) == []                # motors off, no further frames (like firmware)
    finally:
        sim.shutdown()
