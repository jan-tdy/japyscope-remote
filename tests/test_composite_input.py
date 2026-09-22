from typing import Optional

from firmware.hal.input.base import InputHAL
from firmware.hal.input.composite import CompositeInput
from firmware.hal.input.keys import ENC_PUSH, JOY_LEFT


class FakeSource(InputHAL):
    def __init__(self, events=None):
        self.events = list(events or [])
        self.closed = False

    def poll(self, timeout: float = 0.1) -> Optional[str]:
        return self.events.pop(0) if self.events else None

    def close(self) -> None:
        self.closed = True


def test_same_source_shortcut_polls_once_unfiltered():
    shared = FakeSource(["5"])
    composite = CompositeInput(shared, shared)
    assert composite.poll() == "5"


def test_mixed_sources_route_by_key_type():
    keypad = FakeSource(["7"])
    encoder = FakeSource([ENC_PUSH])
    composite = CompositeInput(keypad, encoder)
    assert composite.poll() == "7"
    assert composite.poll() == ENC_PUSH


def test_mixed_sources_ignore_events_of_the_wrong_role():
    # A misbehaving/mislabeled source shouldn't be trusted blindly.
    keypad = FakeSource([ENC_PUSH])  # wrong role, must be filtered out
    encoder = FakeSource([])
    composite = CompositeInput(keypad, encoder)
    assert composite.poll() is None


def test_close_closes_both_distinct_sources_but_not_twice_when_shared():
    keypad = FakeSource()
    encoder = FakeSource()
    CompositeInput(keypad, encoder).close()
    assert keypad.closed and encoder.closed

    shared = FakeSource()
    CompositeInput(shared, shared).close()
    assert shared.closed  # single close() call, no error from double-closing


def test_no_joystick_source_is_backward_compatible():
    keypad = FakeSource(["7"])
    encoder = FakeSource([ENC_PUSH])
    composite = CompositeInput(keypad, encoder)
    assert composite._joystick_source is None
    assert composite.poll() == "7"
    assert composite.poll() == ENC_PUSH


def test_distinct_joystick_source_routes_its_own_codes():
    keypad = FakeSource([])
    encoder = FakeSource([])
    joystick = FakeSource([JOY_LEFT])
    composite = CompositeInput(keypad, encoder, joystick)
    assert composite.poll() == JOY_LEFT


def test_joystick_reusing_encoder_role_codes_is_accepted():
    # The joystick's Y-axis/push button emit the same codes as the KY-040
    # encoder (see keys.py) even when it's a distinct source object from the
    # encoder — not just its own JOY_LEFT/JOY_RIGHT.
    keypad = FakeSource([])
    encoder = FakeSource([])
    joystick = FakeSource([ENC_PUSH])
    composite = CompositeInput(keypad, encoder, joystick)
    assert composite.poll() == ENC_PUSH


def test_joystick_source_ignores_keypad_only_keys():
    # A misbehaving/mislabeled joystick source shouldn't be trusted blindly,
    # same principle as test_mixed_sources_ignore_events_of_the_wrong_role.
    keypad = FakeSource([])
    encoder = FakeSource([])
    joystick = FakeSource(["7"])
    composite = CompositeInput(keypad, encoder, joystick)
    assert composite.poll() is None


def test_all_three_shared_one_source_polls_once_unfiltered():
    shared = FakeSource(["5"])
    composite = CompositeInput(shared, shared, shared)
    assert composite.poll() == "5"


def test_close_closes_distinct_joystick_source_too():
    keypad = FakeSource()
    encoder = FakeSource()
    joystick = FakeSource()
    CompositeInput(keypad, encoder, joystick).close()
    assert keypad.closed and encoder.closed and joystick.closed
