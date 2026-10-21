import queue

from firmware.hal.input.base import key_up
from firmware.hal.input.encoder import EncoderInput
from firmware.hal.input.joystick import JoystickInput
from firmware.hal.input.keypad import KeypadInput
from firmware.hal.input.keys import ENC_PUSH, JOY_RIGHT
from firmware.hal.input.simulator import SimulatorInput


def test_keypad_emits_key_up_after_existing_stable_release_debounce():
    keypad = KeypadInput.__new__(KeypadInput)
    keypad._queue = queue.Queue()
    keypad._raw_pressed = {"2": False}
    keypad._changed_at = {"2": 0.0}
    keypad._active = {"2": False}

    keypad._update_key("2", True, 0.01)
    keypad._update_key("2", True, 0.07)
    assert keypad._queue.get_nowait() == "2"
    keypad._update_key("2", False, 0.08)
    keypad._update_key("2", False, 0.14)
    assert keypad._queue.get_nowait() == key_up("2")


class FakeGPIO:
    LOW = 0
    HIGH = 1

    def __init__(self):
        self.level = self.HIGH

    def input(self, pin):
        return self.level


def test_encoder_button_emits_key_up_after_existing_debounce(monkeypatch):
    import firmware.hal.input.encoder as module

    encoder = EncoderInput.__new__(EncoderInput)
    encoder._gpio = FakeGPIO()
    encoder._queue = queue.Queue()
    encoder._sw_raw = encoder._gpio.HIGH
    encoder._sw_changed_at = 0.0
    encoder._sw_pressed = False
    now = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])

    encoder._gpio.level = encoder._gpio.LOW
    encoder._scan_switch()
    now[0] = module._DEBOUNCE_S + 0.01
    encoder._scan_switch()
    assert encoder._queue.get_nowait() == ENC_PUSH
    encoder._gpio.level = encoder._gpio.HIGH
    encoder._scan_switch()
    now[0] += module._DEBOUNCE_S + 0.01
    encoder._scan_switch()
    assert encoder._queue.get_nowait() == key_up(ENC_PUSH)


class FakeADC:
    def __init__(self):
        self.x = 32768
        self.y = 32768

    def read_channel(self, channel):
        return self.x if channel == 0 else self.y


def test_joystick_axis_emits_press_and_release_after_stability_debounce(monkeypatch):
    import firmware.hal.input.joystick as module

    joystick = JoystickInput.__new__(JoystickInput)
    joystick._adc = FakeADC()
    joystick._queue = queue.Queue()
    joystick._active_direction = None
    joystick._direction_candidate = None
    joystick._direction_candidate_at = 0.0
    now = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])

    joystick._adc.x += module._DEAD_ZONE + 1
    joystick._scan_axes()
    now[0] = module._DEBOUNCE_S + 0.01
    joystick._scan_axes()
    assert joystick._queue.get_nowait() == JOY_RIGHT

    joystick._adc.x = 32768
    now[0] += 0.01
    joystick._scan_axes()
    now[0] += module._DEBOUNCE_S + 0.01
    joystick._scan_axes()
    assert joystick._queue.get_nowait() == key_up(JOY_RIGHT)


def test_simulator_infers_release_after_terminal_repeat_stops(monkeypatch):
    import firmware.hal.input.simulator as module

    simulator = SimulatorInput.__new__(SimulatorInput)
    simulator._queue = queue.Queue()
    simulator._held_jog_key = "2"
    simulator._last_jog_event = 0.0
    monkeypatch.setattr(module.time, "monotonic", lambda: module._SIMULATED_RELEASE_S)

    assert simulator.poll(timeout=0) == key_up("2")
