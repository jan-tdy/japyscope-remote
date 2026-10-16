"""Best-effort e-paper shutdown splash: redraws the same orbit-wordmark
logo as the boot splash (firmware/splash.py), but with a "Shutting down…"
caption instead of the JapySoft/Bombol.Space credit, right as the system
powers off — triggered from japyscope-shutdown-splash.service's ExecStop,
the standard systemd idiom for "run something during shutdown" (an
always-on oneshot unit whose real work lives in ExecStop, since systemd
stops every unit as part of a shutdown/reboot). That fires however
shutdown was actually triggered (this device's own menu, the Web UI,
`sudo poweroff` over SSH, the power button via logind), not just one path
through the firmware's own UI code.

The caption swap matters because e-ink holds its last image with no
power: this is what stays on the panel through the whole power-off
sequence, not just a brief flash, so it needs to read as "the device is
off", not as a hung boot screen. Reuses splash.py's cached-bitmap helper
for the same reason it exists there: fast, no Pillow import needed — just
pointed at the ``shutdown`` variant instead.
"""
from __future__ import annotations

import logging

from firmware.hal.display import make_display
from firmware.splash import _cached_bitmap


def main() -> int:
    try:
        display = make_display(False)
        bitmap = _cached_bitmap(display.profile, variant="shutdown")
        if bitmap is None:
            from firmware.hal.display.boot_logo import render_shutdown

            bitmap = render_shutdown(display.profile)
        display.draw_bitmap(bitmap)
    except (ImportError, NotImplementedError, OSError, TimeoutError) as exc:
        logging.warning("Shutdown splash unavailable: %s", exc)
    return 0


if __name__ == "__main__": raise SystemExit(main())
