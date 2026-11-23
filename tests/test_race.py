import pytest

from slotcar.race import LapRejected, Phase, Race


def run(race, laps):
    out = None
    for lane, t in laps:
        out = race.record_lap(lane, t)
    return out


def test_auto_numbered_laps_and_winner():
    r = Race("Ann", "Bob")
    r.arm()
    r.go()
    out = run(r, [(1, 5.0), (2, 5.5), (1, 5.1), (2, 4.9), (1, 5.2)])
    assert out.driver_finished and not out.race_finished
    assert r.winner is None
    out = r.record_lap(2, 5.0)
    assert out.race_finished
    assert r.winner == 1            # 15.3 vs 15.4
    assert r.phase is Phase.FINISHED


def test_tie_goes_to_lane_one():
    r = Race()
    run(r, [(1, 5.0), (1, 5.0), (1, 5.0), (2, 5.0), (2, 5.0), (2, 5.0)])
    assert r.winner == 1


def test_fourth_lap_rejected():
    r = Race()
    run(r, [(1, 5.0), (1, 5.0), (1, 5.0)])
    with pytest.raises(LapRejected):
        r.record_lap(1, 5.0)


def test_explicit_lap_number_overwrites():
    r = Race()
    r.record_lap(1, 6.0, lap=2)
    r.record_lap(1, 5.0, lap=2)
    assert r.drivers[1].laps == {2: 5.0}


def test_personal_best_and_fastest_flags():
    r = Race()
    a = r.record_lap(1, 6.0)
    assert a.personal_best and a.fastest_overall
    b = r.record_lap(2, 6.5)
    assert b.personal_best and not b.fastest_overall
    c = r.record_lap(2, 5.5)
    assert c.personal_best and c.fastest_overall
    assert r.fastest_lap == (2, 5.5)


def test_gap_compares_equal_lap_counts():
    r = Race()
    run(r, [(1, 5.0), (2, 5.3), (1, 5.0)])
    assert r.gap(1) == pytest.approx(-0.3)
    assert r.gap(2) == pytest.approx(0.3)


def test_lap_before_start_moves_to_racing():
    r = Race()
    r.record_lap(1, 5.0)
    assert r.phase is Phase.RACING
