from typing import Optional

from firmware.hal.input.base import InputHAL
from firmware.hal.input.composite import CompositeInput
from firmware.hal.input.keys import ENC_PUSH


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
