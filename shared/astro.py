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


def _hour_angle_radians(ra_deg: float, longitude_deg: float, when_epoch: float) -> float:
    when_utc = datetime.fromtimestamp(when_epoch, tz=timezone.utc)
    lst = (_gmst_degrees(when_utc) + longitude_deg) % 360.0
    return math.radians((lst - ra_deg + 540) % 360 - 180)


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
    hour_angle = _hour_angle_radians(ra_deg, longitude_deg, when_epoch)
    lat = math.radians(latitude_deg)
    dec = math.radians(dec_deg)
    sin_alt = math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec) * math.cos(hour_angle)
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_alt))))


def azimuth_degrees(
    ra_deg: float,
    dec_deg: float,
    latitude_deg: float,
    longitude_deg: float,
    when_epoch: float,
) -> float:
    """Topocentric azimuth, in degrees (0 = North, 90 = East), of
    (`ra_deg`, `dec_deg`) for the same observer/time as
    `altitude_degrees` -- same standard hour-angle-based spherical
    astronomy conversion."""
    hour_angle = _hour_angle_radians(ra_deg, longitude_deg, when_epoch)
    lat = math.radians(latitude_deg)
    dec = math.radians(dec_deg)
    az = math.atan2(
        -math.sin(hour_angle),
        math.cos(lat) * math.tan(dec) - math.sin(lat) * math.cos(hour_angle),
    )
    return math.degrees(az) % 360.0


def ra_dec_from_alt_az(
    alt_deg: float,
    az_deg: float,
    latitude_deg: float,
    longitude_deg: float,
    when_epoch: float,
) -> tuple[float, float]:
    """Inverse of `altitude_degrees()`/`azimuth_degrees()`: the RA/Dec
    (both in degrees, RA in 0-360) currently at horizontal position
    (`alt_deg`, `az_deg`, same 0=North/90=East convention) for an
    observer at (`latitude_deg`, `longitude_deg`) at `when_epoch`.
    Standard reciprocal spherical-astronomy transform to the pair above
    (round-trip verified to floating-point noise) -- this is already in
    the equinox of date (uses the current sidereal time directly, not a
    catalog epoch), so unlike catalog RA/Dec it must NOT be passed through
    `precess_j2000_to_date()` again."""
    alt = math.radians(alt_deg)
    az = math.radians(az_deg)
    lat = math.radians(latitude_deg)

    sin_dec = math.sin(alt) * math.sin(lat) + math.cos(alt) * math.cos(lat) * math.cos(az)
    dec = math.asin(max(-1.0, min(1.0, sin_dec)))
    cos_dec = math.cos(dec)
    cos_lat = math.cos(lat)

    if abs(cos_dec) < 1e-9 or abs(cos_lat) < 1e-9:
        # At the celestial pole (alt=90 at this latitude) or an observer
        # at the geographic pole, the hour angle -- and so RA -- is
        # genuinely undefined; 0 is as good as any other value.
        hour_angle = 0.0
    else:
        sin_h = -math.sin(az) * math.cos(alt) / cos_dec
        cos_h = (math.sin(alt) - math.sin(lat) * math.sin(dec)) / (cos_lat * cos_dec)
        hour_angle = math.atan2(sin_h, cos_h)

    when_utc = datetime.fromtimestamp(when_epoch, tz=timezone.utc)
    lst_deg = _gmst_degrees(when_utc) + longitude_deg
    ra_deg_result = (lst_deg - math.degrees(hour_angle)) % 360.0
    return ra_deg_result, math.degrees(dec)


def precess_j2000_to_date(ra_deg: float, dec_deg: float, when_epoch: float) -> tuple[float, float]:
    """Precess (`ra_deg`, `dec_deg`) from the J2000.0 equinox -- what this
    project's catalogs and alignment stars are stored in -- to the
    equinox of `when_epoch`, i.e. "epoch of date"/JNow, which is what
    INDI's EQUATORIAL_EOD_COORD expects (confirmed against
    libs/indibase/inditelescope.cpp's own property comment and general
    INDI convention -- EOD literally stands for that). By 2026 this is
    already a ~0.37 degree difference, growing ~50"/year -- small next to
    this project's other low-precision math, but large enough to matter
    for GOTO accuracy if left uncorrected.

    Standard low-precision precession (Meeus, *Astronomical Algorithms*
    2nd ed., ch. 21, IAU 1976 model) -- accurate to a few arcseconds over
    a century, far more than this device needs."""
    when_utc = datetime.fromtimestamp(when_epoch, tz=timezone.utc)
    jd = _julian_date(when_utc)
    t = (jd - 2451545.0) / 36525.0  # Julian centuries since J2000.0

    arcsec = math.pi / (180.0 * 3600.0)
    zeta = (2306.2181 * t + 0.30188 * t**2 + 0.017998 * t**3) * arcsec
    z = (2306.2181 * t + 1.09468 * t**2 + 0.018203 * t**3) * arcsec
    theta = (2004.3109 * t - 0.42665 * t**2 - 0.041833 * t**3) * arcsec

    ra0 = math.radians(ra_deg)
    dec0 = math.radians(dec_deg)

    a = math.cos(dec0) * math.sin(ra0 + zeta)
    b = math.cos(theta) * math.cos(dec0) * math.cos(ra0 + zeta) - math.sin(theta) * math.sin(dec0)
    c = math.sin(theta) * math.cos(dec0) * math.cos(ra0 + zeta) + math.cos(theta) * math.sin(dec0)

    ra = (math.degrees(math.atan2(a, b)) + math.degrees(z)) % 360.0
    dec = math.degrees(math.asin(max(-1.0, min(1.0, c))))
    return ra, dec
