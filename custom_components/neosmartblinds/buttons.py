"""Physical button handling, moved in from the external toggle blueprint.

Each binding maps one press of an event entity to an action on a group of
covers. The integration drives the whole group in a single service call, so the
hub coalesces it into one group command where the blinds share a room code, and
serialises everything through its one connection. That is why none of the
blueprint's collision avoidance (a shared mutex, a post send gap, a yield to the
schedule automations) is reproduced here: the hub already guarantees it, so two
buttons pressed together just travel in parallel instead of one waiting on the
other.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    STATE_CLOSING,
    STATE_OPEN,
    STATE_OPENING,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    ACTION_CLOSE,
    ACTION_FAVOURITE,
    ACTION_OPEN,
    ACTION_STOP,
    ACTION_TOGGLE,
    DOMAIN,
    OPEN_THRESHOLD,
)
from .models import ButtonBinding

_LOGGER = logging.getLogger(__name__)

_MOVING = (STATE_OPENING, STATE_CLOSING)
_ABSENT = (None, STATE_UNAVAILABLE, STATE_UNKNOWN)

# Map a resolved action to the cover service that carries it out.
_SERVICE = {
    ACTION_OPEN: "open_cover",
    ACTION_CLOSE: "close_cover",
    ACTION_STOP: "stop_cover",
}


def is_real_press(
    old_state: str | None,
    new_state: str | None,
    new_event_type: str | None,
    want_event_type: str,
) -> bool:
    """Decide whether a state change on an event entity is a press we want.

    An event entity carries the event timestamp as its state, so a real press
    always lands as a new, non empty state. This filters attribute only updates,
    startup noise and unavailability, and requires the press type to match when
    one was configured.
    """
    if old_state is None or new_state is None:
        return False
    if new_state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return False
    if new_state == old_state:
        return False
    # When a press type is configured, it must match the entity's attribute.
    return not (want_event_type and new_event_type != want_event_type)


def any_open(cover_states: list[tuple[str | None, int | None]]) -> bool:
    """Return True if any cover in the group counts as open.

    A cover is open if its reported position is above the threshold, or, when it
    reports no position, if its state is open. This is the blueprint's rule, so
    the group always converges to a consistent state even from a mixed start.
    """
    for state, position in cover_states:
        if position is not None:
            if int(position) > OPEN_THRESHOLD:
                return True
        elif state == STATE_OPEN:
            return True
    return False


def resolve_target(
    action: str, cover_states: list[tuple[str | None, int | None]]
) -> str:
    """Resolve a binding's action into a concrete target for the group.

    Toggle becomes close when anything is open, and open only when everything is
    closed. Every other action passes straight through.
    """
    if action == ACTION_TOGGLE:
        return ACTION_CLOSE if any_open(cover_states) else ACTION_OPEN
    return action


class ButtonController:
    """Listens to button event entities and drives cover groups."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, bindings: list[ButtonBinding]
    ) -> None:
        """Initialise with the configured bindings."""
        self._hass = hass
        self._entry = entry
        self._bindings = bindings
        self._unsubs: list[Callable[[], None]] = []
        self._busy: set[str] = set()
        self._last: dict | None = None

    @callback
    def async_start(self) -> None:
        """Subscribe to every configured button's event entity."""
        for binding in self._bindings:
            if not binding.event_entity or not binding.covers:
                continue
            self._unsubs.append(
                async_track_state_change_event(
                    self._hass, [binding.event_entity], self._make_handler(binding)
                )
            )

    @callback
    def async_stop(self) -> None:
        """Unsubscribe every listener."""
        while self._unsubs:
            self._unsubs.pop()()

    def diagnostics(self) -> dict:
        """Return a snapshot of the button bindings and last activity."""
        return {
            "bindings": [
                {
                    "name": b.name,
                    "event_entity": b.event_entity,
                    "event_type": b.event_type,
                    "action": b.action,
                    "covers": list(b.covers),
                }
                for b in self._bindings
            ],
            "last": self._last,
            "busy": sorted(self._busy),
        }

    def _make_handler(self, binding: ButtonBinding) -> Callable[[Event], None]:
        """Build the state change handler bound to one button."""

        @callback
        def _handler(event: Event) -> None:
            self._handle(binding, event)

        return _handler

    @callback
    def _handle(self, binding: ButtonBinding, event: Event) -> None:
        """Act on a state change of a button's event entity."""
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        old_state = old.state if old else None
        new_state = new.state if new else None
        new_type = new.attributes.get("event_type") if new else None
        if not is_real_press(old_state, new_state, new_type, binding.event_type):
            return

        if binding.button_id in self._busy:
            _LOGGER.debug("%s: press ignored, still busy", binding.name)
            return

        states = {c: self._state_position(c) for c in binding.covers}
        reachable = [c for c in binding.covers if states[c][0] not in _ABSENT]
        if not reachable:
            _LOGGER.warning("%s: no reachable covers to command", binding.name)
            return
        if any(states[c][0] in _MOVING for c in reachable):
            _LOGGER.debug("%s: press ignored, a cover is already moving", binding.name)
            return

        target = resolve_target(binding.action, [states[c] for c in reachable])
        self._busy.add(binding.button_id)
        self._last = {
            "name": binding.name,
            "action": binding.action,
            "target": target,
            "covers": reachable,
            "at": time.time(),
        }
        self._hass.async_create_task(self._run(binding, target, reachable))

    def _state_position(self, entity_id: str) -> tuple[str | None, int | None]:
        """Return the (state, current_position) of a cover."""
        state = self._hass.states.get(entity_id)
        if state is None:
            return (None, None)
        return (state.state, state.attributes.get("current_position"))

    async def _run(self, binding: ButtonBinding, target: str, live: list[str]) -> None:
        """Drive the group, wait out the travel, then hold off for the cooldown.

        Staying inside this coroutine while the group travels and cools down is
        the debounce: any press that arrives meanwhile finds the button busy and
        is dropped.
        """
        try:
            await self._drive(target, live)
            await self._wait_travel(binding, live)
            if binding.cooldown > 0:
                await asyncio.sleep(binding.cooldown)
        except Exception:
            # A button must never wedge on an error, or it would stay busy and
            # ignore every future press.
            _LOGGER.exception("%s: button action failed", binding.name)
        finally:
            self._busy.discard(binding.button_id)

    async def _drive(self, target: str, live: list[str]) -> None:
        """Command the whole group in a single service call."""
        _LOGGER.info("Button drive %s on %s", target, live)
        if target in _SERVICE:
            await self._hass.services.async_call(
                "cover", _SERVICE[target], {"entity_id": live}, blocking=False
            )
        elif target == ACTION_FAVOURITE:
            await self._hass.services.async_call(
                DOMAIN, "set_favourite", {"entity_id": live}, blocking=False
            )

    async def _wait_travel(self, binding: ButtonBinding, live: list[str]) -> None:
        """Wait for the group to stop, bounded by the travel ceiling."""
        # Give the covers a moment to enter a moving state.
        await asyncio.sleep(min(2.0, binding.travel_ceiling))
        deadline = time.monotonic() + binding.travel_ceiling
        while time.monotonic() < deadline:
            if not self._any_moving(live):
                return
            await asyncio.sleep(0.5)

    def _any_moving(self, live: list[str]) -> bool:
        """Return True if any cover in the group is still travelling."""
        for entity_id in live:
            state = self._hass.states.get(entity_id)
            if state is not None and state.state in _MOVING:
                return True
        return False
