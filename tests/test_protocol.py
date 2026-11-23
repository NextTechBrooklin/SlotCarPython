import pytest

from slotcar import protocol as P


@pytest.mark.parametrize("frame, expected", [
    ("<C1,14.752", P.LapMsg(1, 14.752)),
    ("<C2,15.1", P.LapMsg(2, 15.1)),
    ("<c2, 9", P.LapMsg(2, 9.0)),
    ("<R1,72", P.RpmMsg(1, 72.0)),
    ("<R2,45.5", P.RpmMsg(2, 45.5)),
    ("LAP,right,3,9000", P.LapMsg(2, 9.0, 3)),
    ("RPM,car1,72.0", P.RpmMsg(1, 72.0)),
    ("START", P.StartMsg()),
    ("start", P.StartMsg()),
    ("LAP,1,2,14752", P.LapMsg(1, 14.752, 2)),
    ("lap,lane2,1,8000", P.LapMsg(2, 8.0, 1)),
    ("RPM,2,67.5", P.RpmMsg(2, 67.5)),
    ("RPM,left,10", P.RpmMsg(1, 10.0)),
])
def test_parse_valid(frame, expected):
    assert P.parse_frame(frame) == expected


@pytest.mark.parametrize("frame", [
    "", "   ", "<C3,1.0", "<C1,abc", "<C1,", "<X1,5", "<C1,0", "hello",
    "LAP,1,4,100", "LAP,9,1,100", "LAP,1,1,0",
    # JSON is not supported (removed in v4.1) - must be ignored, not misparsed
    '{"type":"start"}', '{"type":"lap","driver":1,"lap":2,"time_ms":14752}', '{"type":"rpm","driver":1,"rpm":5}',
    "LAP,1,2", "RPM,3,50", "LAP,1,0,1000",
])
def test_parse_invalid(frame):
    assert P.parse_frame(frame) is None


def test_assembler_handles_lfcr_and_split_chunks():
    a = P.FrameAssembler()
    assert a.feed("<C1,14.") == []
    assert a.feed("752\n") == ["<C1,14.752"]
    assert a.feed("\r<R1,5") == []
    assert a.feed("0\n\r<R2,1\r\n") == ["<R1,50", "<R2,1"]
    assert a.pending == ""


def test_assembler_bounds_runaway_buffer():
    a = P.FrameAssembler()
    a.feed("x" * 5000)
    assert len(a.pending) <= P.FrameAssembler.MAX_BUFFER


def test_outbound_commands_match_firmware():
    assert P.cmd_start_race() == b"START_RACE"
    assert P.cmd_ghost(True) == b"GHOST:5\r\n"
    assert P.cmd_ghost(False) == b"GHOST:0\r\n"
    assert P.cmd_practice(True) == b"PRACTICE:45\r\n"
    assert P.cmd_practice(False) == b"PRACTICE:0\r\n"


@pytest.mark.parametrize("name, expected", [
    ("SlotCarMasters", True), ("slot", True), ("SLOT-01", True), ("  Slot Racer", True),
    ("MySlotCar", False), ("Slo", False), ("", False), (None, False), ("OBSMyWine", False),
])
def test_slot_device_name_filter(name, expected):
    from slotcar.ble import is_slot_device
    assert is_slot_device(name) is expected
