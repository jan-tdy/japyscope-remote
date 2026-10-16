"""Best-effort e-paper boot splash (the orbit-wordmark logo) for the
systemd oneshot (japyscope-splash.service, After=local-fs.target, Before=
japyscope-app.service) — the whole point is pixels on the panel as fast as
possible after boot, so this reads the precomputed bitmap in
firmware/hal/display/boot_logo_cache/ rather than calling boot_logo.render()
directly: that would pull in Pillow, whose own import is noticeably slow on
the Pi Zero W's single ARMv6 core (see rasterizer.py's module docstring).
Only falls back to a live render (and the Pillow import that comes with it)
when there's no usable cached bitmap for the active profile.
"""
from __future__ import annotations

import logging

from firmware.hal.display import make_display
from firmware.hal.display.boot_logo import CACHE_DIR


def _cached_bitmap(profile) -> bytes | None:
    path = CACHE_DIR / f"{profile.name}.bin"
    try:
        data = path.read_bytes()
    except OSError:
        return None
    expected = ((profile.width + 7) // 8) * profile.height
    return data if len(data) == expected else None


def main() -> int:
    try:
        display = make_display(False)
        bitmap = _cached_bitmap(display.profile)
        if bitmap is None:
            from firmware.hal.display.boot_logo import render as render_boot_logo

            bitmap = render_boot_logo(display.profile)
        display.draw_bitmap(bitmap)
    except (ImportError, NotImplementedError, OSError, TimeoutError) as exc:
        logging.warning("Display splash unavailable until panel setup is finalized: %s", exc)
    return 0


if __name__ == "__main__": raise SystemExit(main())
