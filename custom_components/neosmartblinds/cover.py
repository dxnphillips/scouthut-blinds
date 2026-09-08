"""NeoSmartBlinds cover platform, built from a config entry."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

import voluptuous as vol
from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    ACTION_CLOSING,
    ACTION_OPENING,
    ACTION_STOPPED,
    DOMAIN,
    EXPLICIT_POSITIONING,
    FAV_REPEAT_MARGIN,
    LEGACY_POSITIONING,
)
from .hub import BlindClient, NeoHub
from .models import BlindConfig
from .options import blinds_from_options

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

SERVICE_SET_FAVOURITE = "set_favourite"
SERVICE_SEND_COMMAND = "send_command"

# Three state model for bf motors, enforced in the handler rather than by hiding
# the feature. SET_POSITION is advertised because some callers (CCA, a kitchen
# handle clearance automation) reach the favourite through position 50, and Home
# Assistant blocks the service entirely on entities without the flag. The handler
# accepts only the reachable targets and rejects the rest with a warning. Tilt is
# not advertised: the original upstream repurposed the tilt slider to fire
# favourites, so a stray tilt request moved the blind.
SUPPORT_NEOSMARTBLINDS = (
    CoverEntityFeature.OPEN
    | CoverEntityFeature.CLOSE
    | CoverEntityFeature.STOP
    | CoverEntityFeature.SET_POSITION
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the covers for a hub from its configured blinds."""
    hub: NeoHub = entry.runtime_data

    covers = [
        NeoSmartBlindsCover(hass, entry, blind, hub.client_for(blind))
        for blind in blinds_from_options(entry.options)
    ]
    async_add_entities(covers)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SET_FAVOURITE, {}, "async_set_favourite"
    )
    platform.async_register_entity_service(
        SERVICE_SEND_COMMAND,
        {vol.Required("command"): cv.string},
        "async_send_raw_command",
    )


def compute_wait_time(larger: float, smaller: float, close_time: float) -> float:
    """Estimate how long a move between two percentages takes.

    The caller determines direction and passes the larger value. Always returns
    a non negative number.
    """
    return abs(((larger - smaller) * close_time) / 100)


class PositioningRequest:
    """Monitors and reacts to an emulated blind position change."""

    def __init__(
        self, target_position: int, starting_position: int, needs_stop: bool
    ) -> None:
        """Start tracking a move to ``target_position``."""
        self._target_position = target_position
        self._starting_position = starting_position
        self._interrupt = asyncio.Event()
        self._start = time.monotonic()
        self._active_wait: float | None = None
        self._adjusted_wait: float | None = None
        self._needs_stop = needs_stop

    @property
    def needs_stop(self) -> bool:
        """Whether an explicit stop is required once the move completes."""
        return self._needs_stop

    @property
    def target_position(self) -> int:
        """The position this request is driving toward."""
        return self._target_position

    @property
    def starting_position(self) -> int:
        """The position the blind started from."""
        return self._starting_position

    async def async_wait(self, reason: str, cover: NeoSmartBlindsCover) -> float:
        """Wait for the move, honouring interrupts and adjustments."""
        elapsed = 0.0
        while True:
            await asyncio.wait_for(
                asyncio.create_task(self._interrupt.wait()),
                self._active_wait - elapsed,
            )
            elapsed = time.monotonic() - self._start
            if self._adjusted_wait is not None:
                self._active_wait = self._adjusted_wait
                self._adjusted_wait = None
                self._interrupt.clear()
            else:
                break
        return elapsed

    async def async_wait_for_move_up(self, cover: NeoSmartBlindsCover) -> bool:
        """Wait for an upward move. True if interrupted and re-targeted."""
        was_interrupted = False
        self._active_wait = compute_wait_time(
            self._target_position, self._starting_position, cover.close_time
        )
        try:
            elapsed = await self.async_wait("open", cover)
            if elapsed < self._active_wait:
                self._target_position = int(
                    self._starting_position
                    + (self._target_position - self._starting_position)
                    * elapsed
                    / self._active_wait
                )
                was_interrupted = True
        except TimeoutError:
            pass
        return was_interrupted

    async def async_wait_for_move_down(self, cover: NeoSmartBlindsCover) -> bool:
        """Wait for a downward move. True if interrupted and re-targeted."""
        was_interrupted = False
        self._active_wait = compute_wait_time(
            self._starting_position, self._target_position, cover.close_time
        )
        try:
            elapsed = await self.async_wait("close", cover)
            if elapsed < self._active_wait:
                self._target_position = int(
                    self._starting_position
                    - (self._starting_position - self._target_position)
                    * elapsed
                    / self._active_wait
                )
                was_interrupted = True
        except TimeoutError:
            pass
        return was_interrupted

    def is_moving_up(self) -> bool:
        """Whether the blind is moving up."""
        return self._target_position > self._starting_position

    def estimate_current_position(self) -> int:
        """Estimate the live position from elapsed time."""
        if not self._active_wait:
            return self._starting_position
        elapsed = time.monotonic() - self._start
        if self.is_moving_up():
            return int(
                self._starting_position
                + (self._target_position - self._starting_position)
                * elapsed
                / self._active_wait
            )
        return int(
            self._starting_position
            - (self._starting_position - self._target_position)
            * elapsed
            / self._active_wait
        )

    def adjust(self, target_position: int, cover: NeoSmartBlindsCover) -> int | None:
        """Try to adjust the in flight target. Returns estimate if it cannot."""
        cur = self.estimate_current_position()
        if self.is_moving_up():
            if cur <= target_position:
                self._target_position = target_position
                self._adjusted_wait = compute_wait_time(
                    target_position, self._starting_position, cover.close_time
                )
                self.interrupt()
                return None
        else:
            if cur >= target_position:
                self._target_position = target_position
                self._adjusted_wait = compute_wait_time(
                    self._starting_position, target_position, cover.close_time
                )
                self.interrupt()
                return None
        return cur

    def interrupt(self) -> None:
        """Interrupt the in flight wait."""
        self._interrupt.set()


class NeoSmartBlindsCover(CoverEntity, RestoreEntity):
    """A NeoSmartBlinds cover entity."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = "blind"
    _attr_supported_features = SUPPORT_NEOSMARTBLINDS

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        blind: BlindConfig,
        client: BlindClient,
    ) -> None:
        """Initialise from the blind's configuration."""
        self.hass = hass
        self._entry = entry
        self._blind = blind
        self._client = client

        self._attr_name = blind.name
        self._attr_unique_id = client.unique_id(DOMAIN)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "NeoSmartBlinds",
            "model": "Smart Controller",
        }

        self._percent_support = blind.percent_support
        self._close_time = int(blind.close_time)
        if self._percent_support > LEGACY_POSITIONING:
            self._current_position = blind.start_position
        else:
            self._current_position = 50
        self._current_action = ACTION_STOPPED
        # Wall clock time (monotonic) the blind last came to rest and the last
        # drive was issued, used by the favourite guards.
        self._last_stopped = time.monotonic()
        self._last_drive_issued = 0.0
        self._pending_positioning_command: PositioningRequest | None = None
        self._stopped: asyncio.Event | None = None

    # -- properties --------------------------------------------------------

    @property
    def close_time(self) -> int:
        """Full travel time in seconds."""
        return self._close_time

    @property
    def pending_positioning_command(self) -> PositioningRequest | None:
        """The in flight positioning request, if any."""
        return self._pending_positioning_command

    @property
    def is_closed(self) -> bool | None:
        """Whether the cover is fully closed."""
        if self._current_position is None:
            return None
        return self._current_position == 0

    @property
    def is_closing(self) -> bool:
        """Whether the cover is closing."""
        return self._current_action == ACTION_CLOSING

    @property
    def is_opening(self) -> bool:
        """Whether the cover is opening."""
        return self._current_action == ACTION_OPENING

    @property
    def current_cover_position(self) -> int | None:
        """The current (estimated) position."""
        return self._current_position

    # -- lifecycle ---------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        """Restore the last position where nothing else set one."""
        await super().async_added_to_hass()
        if self._current_position is None:
            last_state = await self.async_get_last_state()
            if (
                last_state is not None
                and ATTR_CURRENT_POSITION in last_state.attributes
            ):
                self._current_position = last_state.attributes[ATTR_CURRENT_POSITION]
            else:
                self._current_position = 50

    async def async_will_remove_from_hass(self) -> None:
        """Release this blind's hub registration on removal."""
        await super().async_will_remove_from_hass()
        # Never let teardown raise.
        with contextlib.suppress(Exception):
            self._client.cancel_pending_repeats()

    # -- open / close ------------------------------------------------------

    async def async_close_cover(self, **kwargs) -> None:
        """Fully close the cover."""
        if self._pending_positioning_command is not None:
            await self.async_stop_cover_partially()
        await self.async_close_cover_to(0)

    async def async_close_cover_to(self, target_position, move_command=None) -> None:
        """Close to ``target_position``. Caller ensures a close is required."""
        self._stopped = asyncio.Event()
        self._pending_positioning_command = PositioningRequest(
            target_position,
            self._current_position,
            not (target_position == 0 or move_command),
        )
        self._current_position = target_position
        self._current_action = ACTION_CLOSING
        self._last_drive_issued = time.monotonic()

        moved = (
            await self._client.async_down_command()
            if move_command is None
            else await move_command()
        )
        if moved:
            self.hass.async_create_task(self.async_cover_closed_to_position())
            self.async_write_ha_state()
        else:
            self.cover_change_complete(False)

    async def async_open_cover(self, **kwargs) -> None:
        """Fully open the cover."""
        if self._pending_positioning_command is not None:
            await self.async_stop_cover_partially()
        await self.async_open_cover_to(100)

    async def async_open_cover_to(self, target_position, move_command=None) -> None:
        """Open to ``target_position``. Caller ensures an open is required."""
        self._stopped = asyncio.Event()
        self._pending_positioning_command = PositioningRequest(
            target_position,
            self._current_position,
            not (target_position == 100 or move_command),
        )
        self._current_position = target_position
        self._current_action = ACTION_OPENING
        self._last_drive_issued = time.monotonic()

        moved = (
            await self._client.async_up_command()
            if move_command is None
            else await move_command()
        )
        if moved:
            self.hass.async_create_task(self.async_cover_opened_to_position())
            self.async_write_ha_state()
        else:
            self.cover_change_complete(False)

    async def async_cover_closed_to_position(self) -> None:
        """Complete a downward positioning request."""
        interrupted = await self.pending_positioning_command.async_wait_for_move_down(
            self
        )
        if not interrupted and self.pending_positioning_command.needs_stop:
            await self._client.async_stop_command()
        self.cover_change_complete()

    async def async_cover_opened_to_position(self) -> None:
        """Complete an upward positioning request."""
        interrupted = await self.pending_positioning_command.async_wait_for_move_up(
            self
        )
        if not interrupted and self.pending_positioning_command.needs_stop:
            await self._client.async_stop_command()
        self.cover_change_complete()

    def cover_change_complete(self, result: bool = True) -> None:
        """Clean up once a positioning request finishes."""
        if self.pending_positioning_command is not None:
            self._current_action = ACTION_STOPPED
            self._last_stopped = time.monotonic()
            if result:
                self._current_position = (
                    self.pending_positioning_command.target_position
                )
            else:
                self._current_position = (
                    self.pending_positioning_command.starting_position
                )
            self._pending_positioning_command = None
            if self._stopped is None:
                if result:
                    _LOGGER.error("%s move done but state broken", self._attr_name)
            else:
                self._stopped.set()
            self.async_write_ha_state()

    # -- stop --------------------------------------------------------------

    async def async_stop_cover(self, **kwargs) -> None:
        """Stop the cover and clear any pending request."""
        await self.async_stop_cover_partially()
        if self.pending_positioning_command is not None:
            self._pending_positioning_command = None
            self._stopped = None

    async def async_stop_cover_partially(self) -> None:
        """Stop the cover, interrupting any in flight positioning."""
        await self._client.async_stop_command()
        if self.pending_positioning_command is not None:
            self.pending_positioning_command.interrupt()
            await self._stopped.wait()
            self._stopped = None
        else:
            self._current_action = ACTION_STOPPED

    # -- position / favourite ---------------------------------------------

    async def async_set_cover_position(self, **kwargs) -> None:
        """Move the cover to a specific position."""
        await self.async_adjust_blind(kwargs["position"])

    async def async_set_favourite(self) -> None:
        """Send the blind to its single stored favourite (gp), guarded.

        The target position is declared immediately, before the settle, travel
        and idle waits below, which can run to a couple of minutes. If the state
        write happened only at the end, the dashboard would show the stale pre
        favourite position the whole time. These blinds report no real position,
        so every value is a declared intent that the delayed gp repeat converges.
        """
        self._current_position = 50
        self.async_write_ha_state()

        # Once the favourite is requested, no further end stop repeat may start a
        # new travel, which bounds the wait below to a single travel time.
        with contextlib.suppress(Exception):
            self._client.cancel_pending_repeats()

        settle_timeout = self._client.tuning.favourite_settle_timeout
        idle_guard = self._client.tuning.favourite_idle_guard

        # bf motors ignore gp unless the blind has been stopped for the idle
        # guard. If mid move, wait for it to settle before sending.
        waited = 0.0
        while self._current_action != ACTION_STOPPED and waited < settle_timeout:
            await asyncio.sleep(0.5)
            waited += 0.5

        # A blind that missed the first drive frame and caught a late repeat is
        # physically still travelling after the entity says it stopped. Wait out
        # the worst case (drive time plus margin) so gp lands on a stationary
        # motor. Costs nothing when no recent drive has happened.
        safe_after = self._last_drive_issued + self._close_time + FAV_REPEAT_MARGIN
        remaining = safe_after - time.monotonic()
        if remaining > 0:
            await asyncio.sleep(remaining)

        idle_for = time.monotonic() - self._last_stopped
        if idle_for < idle_guard:
            await asyncio.sleep(idle_guard - idle_for)

        await self._client.async_favourite_command()

    async def async_send_raw_command(self, command: str) -> None:
        """Send an arbitrary raw command to this blind, for troubleshooting."""
        _LOGGER.info("%s, manual command: %s", self._attr_name, command)
        await self._client.async_send_raw(command)

    async def async_adjust_blind(self, pos: int) -> None:
        """Route a set_position request per the blind's positioning mode.

        In the honest three state mode (percent_support 0) bf motors can only
        reach a hard end stop (up/dn) or the single stored favourite (gp), so
        anything else is rejected loudly rather than silently dropped. In percent
        modes the request is emulated or delegated to the hub as before.
        """
        if self._percent_support == LEGACY_POSITIONING:
            if pos >= 98:
                await self.async_open_cover()
            elif pos <= 2:
                await self.async_close_cover()
            elif pos in (50, 51):
                await self.async_set_favourite()
            else:
                _LOGGER.warning(
                    "%s: position %s is unreachable on bf motors and was ignored. "
                    "Valid targets are 0 (close), 100 (open) and 50 (favourite).",
                    self._attr_name,
                    pos,
                )
            return

        await self._async_position_to(pos)

    async def _async_position_to(self, target: int) -> None:
        """Emulated or delegated percent positioning (modes 1 and 2)."""
        target = max(0, min(100, int(target)))
        if self._current_position is None:
            self._current_position = 50
        if (
            target == self._current_position
            and self._pending_positioning_command is None
        ):
            return

        if self._pending_positioning_command is not None:
            await self.async_stop_cover_partially()

        explicit = self._percent_support == EXPLICIT_POSITIONING
        if target > self._current_position:
            move = (
                (lambda: self._client.async_set_position_by_percent(target))
                if explicit
                else None
            )
            await self.async_open_cover_to(target, move_command=move)
        else:
            move = (
                (lambda: self._client.async_set_position_by_percent(target))
                if explicit
                else None
            )
            await self.async_close_cover_to(target, move_command=move)
