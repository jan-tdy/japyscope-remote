"""make_input()'s branching logic — real KeypadInput/EncoderInput/
JoystickInput need RPi.GPIO/smbus2 (only importable on a Pi), so real
branches are exercised with a monkeypatched stand-in class instead of
actual hardware."""
from typing import Optional

import firmware.hal.input.encoder as encoder_module
import firmware.hal.input.joystick as joystick_module
import firmware.hal.input.keypad as keypad_module
from firmware.hal.input import make_input
from firmware.hal.input.base import InputHAL
from firmware.hal.input.composite import CompositeInput
from firmware.hal.input.simulator import SimulatorInput


class FakeGpioSource(InputHAL):
    def __init__(self):
        self.closed = False

    def poll(self, timeout: float = 0.1) -> Optional[str]:
        return None

    def close(self) -> None:
        self.closed = True


def test_both_simulated_share_one_terminal_reader(monkeypatch):
    result = make_input(keypad_simulated=True, encoder_simulated=True)
    try:
        assert isinstance(result, CompositeInput)
        assert result._same_source
        assert isinstance(result._keypad_source, SimulatorInput)
    finally:
        result.close()


def test_both_real_uses_independent_gpio_sources(monkeypatch):
    monkeypatch.setattr(keypad_module, "KeypadInput", FakeGpioSource)
    monkeypatch.setattr(encoder_module, "EncoderInput", FakeGpioSource)
    result = make_input(keypad_simulated=False, encoder_simulated=False)
    assert isinstance(result, CompositeInput)
    assert not result._same_source
    assert isinstance(result._keypad_source, FakeGpioSource)
    assert isinstance(result._encoder_source, FakeGpioSource)


def test_mixed_keypad_real_encoder_simulated(monkeypatch):
    monkeypatch.setattr(keypad_module, "KeypadInput", FakeGpioSource)
    result = make_input(keypad_simulated=False, encoder_simulated=True)
    try:
        assert isinstance(result._keypad_source, FakeGpioSource)
        assert isinstance(result._encoder_source, SimulatorInput)
    finally:
        result.close()


def test_joystick_disabled_by_default_builds_no_joystick_source(monkeypatch):
    monkeypatch.setattr(keypad_module, "KeypadInput", FakeGpioSource)
    monkeypatch.setattr(encoder_module, "EncoderInput", FakeGpioSource)
    result = make_input(keypad_simulated=False, encoder_simulated=False)
    assert result._joystick_source is None


def test_joystick_real_uses_its_own_hardware_source(monkeypatch):
    monkeypatch.setattr(keypad_module, "KeypadInput", FakeGpioSource)
    monkeypatch.setattr(encoder_module, "EncoderInput", FakeGpioSource)
    monkeypatch.setattr(joystick_module, "JoystickInput", FakeGpioSource)
    result = make_input(keypad_simulated=False, encoder_simulated=False, joystick_simulated=False)
    assert isinstance(result._joystick_source, FakeGpioSource)
    assert result._joystick_source is not result._keypad_source


def test_joystick_simulated_alone_gets_its_own_terminal_reader(monkeypatch):
    monkeypatch.setattr(keypad_module, "KeypadInput", FakeGpioSource)
    monkeypatch.setattr(encoder_module, "EncoderInput", FakeGpioSource)
    result = make_input(keypad_simulated=False, encoder_simulated=False, joystick_simulated=True)
    try:
        assert isinstance(result._joystick_source, SimulatorInput)
        assert isinstance(result._keypad_source, FakeGpioSource)
    finally:
        result.close()


def test_all_three_simulated_share_one_terminal_reader(monkeypatch):
    result = make_input(keypad_simulated=True, encoder_simulated=True, joystick_simulated=True)
    try:
        assert result._keypad_source is result._encoder_source is result._joystick_source
        assert isinstance(result._keypad_source, SimulatorInput)
    finally:
        result.close()
