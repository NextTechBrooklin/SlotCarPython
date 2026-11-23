from slotcar.ui.fireworks import FireworksShow


def test_show_runs_and_renders_at_requested_size():
    show = FireworksShow(320, 200, ["#22d3ee", "#ffb21c"], finale_at=2.0, seed=1)
    exploded = False
    for _ in range(150):  # 5 s at 30 fps, including the finale
        show.step(1 / 30)
        img = show.render()
        exploded |= any(s.max_life > 0.5 for s in show.sparks)
    assert img.size == (320, 200) and img.mode == "RGB"
    assert exploded
    assert len(show.sparks) <= FireworksShow.MAX_SPARKS + 200  # exhaust embers may top up between bursts


def test_large_dt_is_clamped():
    show = FireworksShow(200, 120, ["#ffffff"], seed=2)
    show.step(10.0)
    assert show.t <= 0.05 + 1e-9
