"""Button binding decision logic."""

from __future__ import annotations

from custom_components.neosmartblinds.buttons import (
    any_open,
    is_real_press,
    resolve_target,
)
from custom_components.neosmartblinds.const import (
    ACTION_CLOSE,
    ACTION_OPEN,
    ACTION_STOP,
    ACTION_TOGGLE,
    CONF_BUTTONS,
)
from custom_components.neosmartblinds.models import ButtonBinding
from custom_components.neosmartblinds.options import buttons_from_options


def test_real_press_needs_a_new_state() -> None:
    # A genuine press changes the timestamp state.
    assert is_real_press("t1", "t2", "press", "press") is True
    # No change is not a press.
    assert is_real_press("t1", "t1", "press", "press") is False
    # Startup and unavailability are filtered.
    assert is_real_press(None, "t2", "press", "press") is False
    assert is_real_press("t1", "unavailable", "press", "press") is False


def test_real_press_matches_event_type() -> None:
    assert is_real_press("t1", "t2", "double_press", "press") is False
    assert is_real_press("t1", "t2", "double_press", "double_press") is True
    # An empty configured type accepts any press.
    assert is_real_press("t1", "t2", "long_press", "") is True


def test_any_open_by_position_and_state() -> None:
    assert any_open([("open", 100)]) is True
    assert any_open([("closed", 0)]) is False
    # The favourite midpoint is not counted as open.
    assert any_open([("open", 50)]) is False
    # Falls back to the state when no position is reported.
    assert any_open([("open", None)]) is True
    assert any_open([("closed", None)]) is False
    # Any one open blind opens the whole group's toggle to close.
    assert any_open([("closed", 0), ("open", 100)]) is True


def test_toggle_converges_the_group() -> None:
    # Anything open closes the lot.
    assert resolve_target(ACTION_TOGGLE, [("closed", 0), ("open", 100)]) == ACTION_CLOSE
    # Only a fully closed group opens.
    assert resolve_target(ACTION_TOGGLE, [("closed", 0), ("closed", 0)]) == ACTION_OPEN


def test_fixed_actions_pass_through() -> None:
    assert resolve_target(ACTION_OPEN, [("closed", 0)]) == ACTION_OPEN
    assert resolve_target(ACTION_STOP, [("open", 100)]) == ACTION_STOP


def test_button_binding_roundtrip() -> None:
    binding = ButtonBinding(
        button_id="x1",
        name="Hall Front",
        event_entity="event.hall_switch_button_1",
        event_type="press",
        action=ACTION_TOGGLE,
        covers=["cover.hall_front_left", "cover.hall_front_right"],
        cooldown=10,
        travel_ceiling=45,
    )
    parsed = buttons_from_options({CONF_BUTTONS: [binding.as_dict()]})
    assert parsed == [binding]
