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


def test_ra_dec_from_alt_az_round_trips_with_altitude_azimuth():
    # Reciprocal pair: converting an RA/Dec to alt/az and back must
    # return the original RA/Dec (within floating-point noise), across
    # a spread of latitudes, azimuths, and times.
    when_epoch = 1_700_000_000.0
    for latitude in (-60.0, -10.0, 10.0, 60.0):
        for ra_deg in (12.3, 123.4, 250.7, 340.1):
            for dec_deg in (-70.0, -5.0, 40.0, 80.0):
                alt = astro.altitude_degrees(ra_deg, dec_deg, latitude, 17.0, when_epoch)
                if alt < 0:
                    continue  # below the horizon -- not a meaningful round trip
                az = astro.azimuth_degrees(ra_deg, dec_deg, latitude, 17.0, when_epoch)
                ra2, dec2 = astro.ra_dec_from_alt_az(alt, az, latitude, 17.0, when_epoch)
                ra_err = min(abs(ra2 - ra_deg), 360 - abs(ra2 - ra_deg))
                assert ra_err < 0.001
                assert abs(dec2 - dec_deg) < 0.001


def test_ra_dec_from_alt_az_at_zenith_does_not_crash():
    # At the zenith the hour angle (and so RA) is genuinely undefined --
    # must return a finite result, not raise or divide by zero.
    ra_deg, dec_deg = astro.ra_dec_from_alt_az(90.0, 0.0, 48.0, 17.0, 1_700_000_000.0)
    assert round(dec_deg, 6) == 48.0  # straight up at latitude L has dec == L
    assert 0.0 <= ra_deg < 360.0
