"""Regression: Ghost mode / Practice must be switched off when a race starts.

Before the fix the buttons stayed "ON" through the race, so the first click
after a race sent GHOST:0 instead of re-enabling ghost mode.
"""

import pytest

from slotcar import protocol
from slotcar.ble import ConnState


class FakeLink:
    device_name = "fake"
    state = ConnState.CONNECTED
    connected = True
    scanning = False

    def __init__(self):
        self.sent = []

    def send(self, payload):
        self.sent.append(payload)

    def disconnect(self): ...
    def shutdown(self, timeout=0): ...


@pytest.fixture
def app():
    tk = pytest.importorskip("tkinter")
    try:
        from slotcar.ui.app import RaceApp
        a = RaceApp()
    except tk.TclError:
        pytest.skip("no display available")
    a.withdraw()
    a.audio.set_muted(True)
    a.link = FakeLink()
    yield a
    a.lights.cancel()
    a._on_close()


def test_race_start_ends_ghost_and_practice_then_one_click_reenables(app):
    app.toggle_ghost()
    app.toggle_practice()
    assert app.ghost_on and app.practice_on

    app.start_race()
    assert not app.ghost_on and not app.practice_on
    assert app.link.sent == [protocol.cmd_ghost(True), protocol.cmd_practice(True),
                             protocol.cmd_ghost(False), protocol.cmd_practice(False)]
    assert app.ghost_btn.cget("text") == "Ghost mode"

    for frame in ["<C1,5.1", "<C2,5.3", "<C1,5.0", "<C2,5.2", "<C1,5.0", "<C2,5.1"]:
        app._handle_frame(frame)  # run the race to the chequered flag
    app.celebration.close(notify=False)

    app.link.sent.clear()
    app.toggle_ghost()  # a single click after the race turns ghost mode back on
    assert app.ghost_on
    assert app.link.sent == [protocol.cmd_ghost(True)]
    assert app.cards[1].chip._label.cget("text") == "GHOST CAR"
    assert app.phase_label.cget("text") == "GHOST RUN"


def test_race_start_sends_nothing_extra_when_modes_are_off(app):
    app.start_race()
    assert app.link.sent == []  # START_RACE itself goes out later, at lights-out



def test_ghost_refused_while_race_running(app):
    app.start_race()
    app.toggle_ghost()
    assert not app.ghost_on
    assert app.link.sent == []


def test_ghost_off_zeroes_gauges(app):
    app.toggle_ghost()
    for card in app.cards.values():
        card.tacho.set_target(80)
        card.tacho.value = 80
    app.toggle_ghost()
    assert all(c.tacho.value == 0 and c.tacho.target == 0 for c in app.cards.values())
