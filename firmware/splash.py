"""Best-effort e-paper boot splash (the orbit-wordmark logo) for the
systemd oneshot."""
import logging

from firmware.hal.display import make_display
from firmware.hal.display.boot_logo import render as render_boot_logo


def main() -> int:
    try:
        display = make_display(False)
        display.draw_bitmap(render_boot_logo(display.profile))
    except (ImportError, NotImplementedError, OSError, TimeoutError) as exc:
        logging.warning("Display splash unavailable until panel setup is finalized: %s", exc)
    return 0


if __name__ == "__main__": raise SystemExit(main())
