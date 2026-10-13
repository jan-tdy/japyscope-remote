from firmware import splash


def test_main_draws_boot_logo_via_simulator_without_crashing(monkeypatch, capsys):
    from firmware.hal.display.simulator import SimulatorDisplay

    monkeypatch.setattr(splash, "make_display", lambda simulate: SimulatorDisplay())
    assert splash.main() == 0
    out = capsys.readouterr().out
    assert "bitmap" in out


def test_main_degrades_gracefully_when_the_display_backend_is_unavailable(monkeypatch):
    def _boom(simulate: bool):
        raise ImportError("no spidev on this host")

    monkeypatch.setattr(splash, "make_display", _boom)
    assert splash.main() == 0
