"""Low-precision alt/az math for showing a catalog object's current
altitude on the display — good enough for "is this above the horizon
right now", not for actually pointing the mount (the INDI driver does its
own math for that). Self-contained (no astropy/skyfield — too heavy for a
Pi Zero and not already a dependency); this is the standard low-precision
GMST -> local sidereal time -> hour angle -> altitude formula.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Optional


def _sexagesimal_tokens(value: str) -> Optional[tuple[float, list[float]]]:
    """`-1` if the string has a minus sign (ASCII `-` or Unicode `−`),
    else `1`, plus every number found in it, in order. `None` if there's
    nothing to parse."""
    if not value or not value.strip():
        return None
    sign = -1.0 if re.search(r"[-−]", value) else 1.0
    tokens = re.findall(r"\d+(?:\.\d+)?", value)
    if not tokens:
        return None
    return sign, [float(t) for t in tokens]


def ra_to_degrees(ra: str) -> Optional[float]:
    """`"16h41m41s"` or colon-separated `"16:41:41"`-style sexagesimal
    (hours) -- custom catalog items entered through the Web UI use either
    -- or a single bare decimal-degree number, e.g. CDS Sesame's
    `jradeg`. Multiple numbers with no `h`/`m`/`s` letters are still
    sexagesimal hours (colon-separated); a lone number is ambiguous
    between hours and degrees, but Sesame's `jradeg` is always a single
    bare number, so that's the one case treated as decimal degrees."""
    parsed = _sexagesimal_tokens(ra)
    if parsed is None:
        return None
    sign, nums = parsed
    if len(nums) >= 2 or "h" in ra.lower():
        h = nums[0] if nums else 0.0
        m = nums[1] if len(nums) > 1 else 0.0
        s = nums[2] if len(nums) > 2 else 0.0
        return (sign * (h + m / 60 + s / 3600) * 15) % 360
    return (sign * nums[0]) % 360


def dec_to_degrees(dec: str) -> Optional[float]:
    """`"+36°28′"`-style sexagesimal (degrees/minutes, with or without
    seconds), or a plain decimal-degree string — e.g. CDS Sesame's
    `jdedeg`."""
    parsed = _sexagesimal_tokens(dec)
    if parsed is None:
        return None
    sign, nums = parsed
    d = nums[0]
    m = nums[1] if len(nums) > 1 else 0.0
    s = nums[2] if len(nums) > 2 else 0.0
    value = sign * (d + m / 60 + s / 3600)
    return max(-90.0, min(90.0, value))


def _julian_date(when_utc: datetime) -> float:
    y, mo = when_utc.year, when_utc.month
    if mo <= 2:
        y -= 1
        mo += 12
    a = y // 100
    b = 2 - a + a // 4
    day = when_utc.day + (when_utc.hour + when_utc.minute / 60 + when_utc.second / 3600) / 24
    return int(365.25 * (y + 4716)) + int(30.6001 * (mo + 1)) + day + b - 1524.5


def _gmst_degrees(when_utc: datetime) -> float:
    jd = _julian_date(when_utc)
    t = (jd - 2451545.0) / 36525.0
    gmst = (
        280.46061837
        + 360.98564736629 * (jd - 2451545.0)
        + 0.000387933 * t**2
        - t**3 / 38710000.0
    )
    return gmst % 360.0


def altitude_degrees(
    ra_deg: float,
    dec_deg: float,
    latitude_deg: float,
    longitude_deg: float,
    when_epoch: float,
) -> float:
    """Topocentric altitude, in degrees, of (`ra_deg`, `dec_deg`) for an
    observer at (`latitude_deg`, `longitude_deg` east-positive) at
    `when_epoch` (Unix timestamp, i.e. `ControllerUI.clock()`)."""
    when_utc = datetime.fromtimestamp(when_epoch, tz=timezone.utc)
    lst = (_gmst_degrees(when_utc) + longitude_deg) % 360.0
    hour_angle = math.radians((lst - ra_deg + 540) % 360 - 180)
    lat = math.radians(latitude_deg)
    dec = math.radians(dec_deg)
    sin_alt = math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec) * math.cos(hour_angle)
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_alt))))
