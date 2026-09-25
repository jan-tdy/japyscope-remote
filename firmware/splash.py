"""Best-effort static e-paper boot splash for the systemd oneshot."""
import logging

from firmware.hal.display import make_display


def main() -> int:
    try:
        make_display(False).draw_lines(["JapyScope Remote", "by JapySoft", "", "Starting…"])
    except (ImportError, NotImplementedError, OSError, TimeoutError) as exc:
        logging.warning("Display splash unavailable until panel setup is finalized: %s", exc)
    return 0


if __name__ == "__main__": raise SystemExit(main())
