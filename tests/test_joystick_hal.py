"""JoystickInput's hardware-independent logic — converting ADS1115 readings
into direction codes, and the register bytes sent to the ADC. The real
JoystickInput class needs RPi.GPIO/smbus2 (only importable on a Pi, lazily
imported inside __init__), same as encoder.py/keypad.py, so it isn't
exercised directly here — see tests/test_make_input.py for that, via a
monkeypatched stand-in."""
from firmware.hal.input.joystick import (
    JOY_X_CHANNEL,
    JOY_Y_CHANNEL,
    _Ads1115,
    _direction_from_axes,
)
from firmware.hal.input.keys import ENC_DOWN, ENC_UP, JOY_LEFT, JOY_RIGHT


def test_centered_stick_reports_no_direction():
    assert _direction_from_axes(0, 0) is None
    assert _direction_from_axes(500, -500) is None  # inside the dead zone


def test_axis_deflection_maps_to_direction():
    assert _direction_from_axes(20000, 0) == JOY_RIGHT
    assert _direction_from_axes(-20000, 0) == JOY_LEFT
    assert _direction_from_axes(0, 20000) == ENC_DOWN
    assert _direction_from_axes(0, -20000) == ENC_UP


def test_diagonal_deflection_is_not_supported():
    # Both axes past the dead zone at once = diagonal push — ignored rather
    # than guessed at, since the mount only jogs one cardinal direction at
    # a time (see docs/CODES.md).
    assert _direction_from_axes(20000, 20000) is None
    assert _direction_from_axes(-20000, 20000) is None
    assert _direction_from_axes(20000, -7000) is None


class FakeBus:
    def __init__(self, conversion=(0x80, 0x00)):
        self.writes = []
        self._conversion = conversion

    def write_i2c_block_data(self, address, register, data):
        self.writes.append((address, register, data))

    def read_i2c_block_data(self, address, register, length):
        assert length == 2
        return list(self._conversion)


def test_read_channel_selects_the_requested_mux_and_returns_conversion():
    bus = FakeBus(conversion=(0x12, 0x34))
    adc = _Ads1115(bus)

    value = adc.read_channel(JOY_X_CHANNEL)

    assert value == 0x1234
    [(address, register, data)] = bus.writes
    assert address == 0x48
    assert register == 0x01
    config = (data[0] << 8) | data[1]
    assert config & 0x7000 == 0x4000  # AIN0 vs GND (channel 0)


def test_read_channel_uses_a_different_mux_per_channel():
    bus = FakeBus()
    adc = _Ads1115(bus)
    adc.read_channel(JOY_X_CHANNEL)
    adc.read_channel(JOY_Y_CHANNEL)
    config_x = (bus.writes[0][2][0] << 8) | bus.writes[0][2][1]
    config_y = (bus.writes[1][2][0] << 8) | bus.writes[1][2][1]
    assert config_x & 0x7000 != config_y & 0x7000
