from firmware.hal.display.boot_logo import render
from firmware.hal.display.profiles import PROFILE_2_13, PROFILE_4_26
from firmware.hal.display.rasterizer import stride_for


def _is_black(bitmap: bytes, stride: int, x: int, y: int) -> bool:
    return not (bitmap[y * stride + x // 8] >> (7 - (x % 8))) & 1


def test_render_output_size_matches_profile():
    bitmap = render(PROFILE_2_13)
    assert len(bitmap) == stride_for(PROFILE_2_13.width) * PROFILE_2_13.height


def test_render_draws_something_on_every_profile():
    # Not a pixel-exact golden image (hand-picked coordinates, no hardware
    # to confirm orientation against yet — see module docstring); just
    # confirms both profiles produce actual ink, not a blank or all-black
    # frame, and never raise/index out of range.
    for profile in (PROFILE_2_13, PROFILE_4_26):
        bitmap = render(profile)
        # Per-byte zero-bit count, not per-pixel-of-width — undercounts
        # slightly at non-multiple-of-8 widths, but is enough to tell "some
        # ink" from "none".
        black = sum(bin(b).count("0") for b in bitmap)
        assert 0 < black < len(bitmap) * 8


def test_render_is_symmetric_left_right():
    # The logo (planet + tilted orbit ring + centered wordmark/caption) has
    # no left/right-asymmetric element by design, so the inked-column count
    # on each half should match — a cheap check that centering math didn't
    # silently push everything to one side.
    profile = PROFILE_2_13
    bitmap = render(profile)
    stride = stride_for(profile.width)
    left_ink = sum(1 for y in range(profile.height) for x in range(profile.width // 2) if _is_black(bitmap, stride, x, y))
    right_ink = sum(
        1
        for y in range(profile.height)
        for x in range(profile.width - profile.width // 2, profile.width)
        if _is_black(bitmap, stride, x, y)
    )
    # The tilted orbit ring and its moon dot aren't left/right-symmetric
    # pixel-for-pixel, so allow headroom rather than asserting equality.
    assert left_ink > 0 and right_ink > 0
    assert abs(left_ink - right_ink) < 0.35 * max(left_ink, right_ink)
