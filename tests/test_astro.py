import datetime

from shared import astro


def test_ra_parses_hms_and_colon_and_decimal():
    assert astro.ra_to_degrees("16h41m41s") == astro.ra_to_degrees("16:41:41")
    assert round(astro.ra_to_degrees("16h41m41s"), 4) == round((16 + 41 / 60 + 41 / 3600) * 15, 4)
    # A single bare number (CDS Sesame's jradeg) is already decimal degrees.
    assert astro.ra_to_degrees("250.42") == 250.42


def test_dec_parses_symbol_and_colon_and_decimal():
    assert astro.dec_to_degrees("+36°28′") == astro.dec_to_degrees("+36:28")
    assert astro.dec_to_degrees("−06°40′") < 0
    assert astro.dec_to_degrees("-6.6667") == -6.6667


def test_ra_dec_return_none_for_garbage():
    assert astro.ra_to_degrees("") is None
    assert astro.ra_to_degrees("not a coordinate") is None
    assert astro.dec_to_degrees("") is None


def test_altitude_is_90_at_zenith():
    when_epoch = 1_700_000_000.0
    when_utc = datetime.datetime.fromtimestamp(when_epoch, tz=datetime.timezone.utc)
    lst_deg = astro._gmst_degrees(when_utc)  # observer longitude 0 => LST == GMST
    latitude = 45.0
    # An object whose RA equals the local sidereal time and whose Dec
    # equals the observer's latitude is, by definition, at the zenith.
    alt = astro.altitude_degrees(lst_deg, latitude, latitude, 0.0, when_epoch)
    assert round(alt, 6) == 90.0


def test_altitude_below_horizon_for_opposite_declination():
    when_epoch = 1_700_000_000.0
    when_utc = datetime.datetime.fromtimestamp(when_epoch, tz=datetime.timezone.utc)
    lst_deg = astro._gmst_degrees(when_utc)
    # At the north pole, anything south of the celestial equator never rises.
    alt = astro.altitude_degrees(lst_deg, -30.0, 90.0, 0.0, when_epoch)
    assert alt < 0


def test_precess_j2000_to_date_is_identity_at_j2000():
    # t == 0 at the J2000.0 epoch itself -- zeta/z/theta all vanish, so the
    # coordinates must come back unchanged (within floating-point noise).
    j2000_epoch = datetime.datetime(2000, 1, 1, 12, tzinfo=datetime.timezone.utc).timestamp()
    ra, dec = astro.precess_j2000_to_date(123.456, -17.5, j2000_epoch)
    assert round(ra, 6) == 123.456
    assert round(dec, 6) == -17.5


def test_precess_j2000_to_date_matches_known_rate_by_2026():
    # Precession moves the equinox ~50"/year; by 2026 (~26 years past
    # J2000.0) a star near the celestial equator should have drifted on
    # the order of 0.3-0.4 degrees -- not zero, and not wildly more.
    when_epoch = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc).timestamp()
    ra, dec = astro.precess_j2000_to_date(250.42, -6.6667, when_epoch)
    assert 0.2 < abs(ra - 250.42) < 0.6
    assert abs(dec - (-6.6667)) < 0.3
