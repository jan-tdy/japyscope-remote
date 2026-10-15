from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_shutdown_splash_is_ordered_before_app_service_not_after():
    # systemd stops units in the REVERSE of their start order. Before=
    # japyscope-app.service here means this unit starts before the app but
    # is stopped AFTER it — so its ExecStop (paints the boot logo) runs
    # once the app has already stopped and can't draw over it again.
    # After=japyscope-app.service (the bug this guards against) would
    # reverse that: the splash would paint, then the app's own shutdown
    # screen would paint over it as the app stops — defeating the feature.
    unit = (ROOT / "install/systemd/japyscope-shutdown-splash.service").read_text(encoding="utf-8")
    assert "Before=japyscope-app.service" in unit
    assert "After=japyscope-app.service" not in unit
