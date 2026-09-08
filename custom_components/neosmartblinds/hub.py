"""The NeoSmartBlinds hub.

Everything that must be coordinated across every blind on one physical hub lives
here, on a single object owned by the config entry: the one at a time connection
to the hub, the global command backoff, the group aggregation, the idempotent
end stop repeat scheduler, and the diagnostic command log and counters.

The original YAML fork kept all of this in module globals keyed by device code.
That worked, but it leaked across reloads (the child counter never reset, so
group aggregation silently stopped firing) and it could not be inspected. Moving
it onto a per entry object fixes the reload leak by construction and lets the
diagnostics dump read live state.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from datetime import datetime

import aiohttp
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CMD_DOWN,
    CMD_DOWN2,
    CMD_FAV,
    CMD_MICRO_DOWN,
    CMD_MICRO_DOWN2,
    CMD_MICRO_UP,
    CMD_MICRO_UP2,
    CMD_STOP,
    CMD_UP,
    CMD_UP2,
    COMMAND_LOG_SIZE,
    CONF_HUB_ID,
    CONF_PROTOCOL,
    FAV_REPEAT_MARGIN,
    PROTOCOL_TCP,
    REPEATABLE_DRIVES,
    SIGNAL_UPDATE,
)
from .models import BlindConfig, CommandRecord, HubCounters, HubTuning

_LOGGER = logging.getLogger(__name__)

# Aggregation outcomes.
_USE_DEVICE = 0
_CHANGE_DEVICE = 1
_IGNORE = 2


class _Aggregator:
    """Collects the same command arriving for several blinds in one group.

    When every blind in a group registers the same command inside the
    aggregation window, one channel 15 group broadcast is sent instead of one
    frame per blind. This is the reliable delivery path on these motors.
    """

    def __init__(self, period: float) -> None:
        """Initialise for a group with the given aggregation window."""
        self._period = period
        self._child_count = 0
        self._intent = 0
        self._fulfilled = False
        self._deadline: float | None = None
        self._intended_command: str | None = None
        self._wait = asyncio.Event()

    def add_child(self) -> None:
        """Register a blind as a member of this group."""
        self._child_count += 1

    def remove_child(self) -> None:
        """Drop a blind from this group, clamped at zero."""
        if self._child_count > 0:
            self._child_count -= 1

    @property
    def child_count(self) -> int:
        """Number of blinds currently in the group."""
        return self._child_count

    def register_intent(self, command: str) -> bool:
        """Note that a blind wants ``command``. False if it clashes."""
        if self._intended_command is None:
            self._intended_command = command
        if self._intended_command != command:
            self._wait.set()
            return False
        self._intent += 1
        if self._intent >= self._child_count:
            self._fulfilled = True
            self._wait.set()
        if self._deadline is None:
            self._deadline = time.monotonic() + self._period
        return True

    def unregister_intent(self) -> None:
        """Release a blind's intent once it has been acted on."""
        self._intent -= 1
        if self._intent <= 0:
            self._intent = 0
            self._fulfilled = False
            self._deadline = None
            self._intended_command = None
            self._wait.clear()

    def act_on_intent(self) -> int:
        """Decide what a blind should do now the window has closed."""
        if not self._fulfilled:
            return _USE_DEVICE
        if self._intent == self._child_count:
            return _CHANGE_DEVICE
        return _IGNORE

    async def async_wait_window(self) -> None:
        """Wait for the aggregation window, or for the group to fill early."""
        if self._deadline is None:
            return
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._wait.wait(), remaining)


class BlindClient:
    """Per blind command facade, backed by the shared hub."""

    def __init__(self, hub: NeoHub, blind: BlindConfig) -> None:
        """Bind a blind's configuration to its hub."""
        self._hub = hub
        self._blind = blind
        # The delayed favourite repeat must land after the worst case travel,
        # plus the motor's own idle requirement, plus a margin.
        self.gp_repeat_delay = (
            float(blind.close_time)
            + hub.tuning.favourite_idle_guard
            + FAV_REPEAT_MARGIN
        )

    @property
    def device(self) -> str:
        """Return this blind's own device code."""
        return self._blind.blind_code

    @property
    def parent_code(self) -> str:
        """The group (room) code this blind belongs to, or ''."""
        return self._blind.parent_group

    @property
    def motor_code(self) -> str:
        """The motor code suffix (for example ``bf``)."""
        return self._blind.motor_code

    @property
    def rail(self) -> int:
        """The rail this blind drives."""
        return self._blind.rail

    @property
    def tuning(self) -> HubTuning:
        """The hub's resolved timing and repeat options."""
        return self._hub.tuning

    def unique_id(self, prefix: str) -> str:
        """Stable unique id for the cover entity."""
        return f"{prefix}.{self._blind.blind_id}"

    async def async_send(self, command: str, *, reason: str = "command") -> bool:
        """Send a command for this blind through the hub."""
        return await self._hub.async_send(self, command, reason=reason)

    def cancel_pending_repeats(self) -> None:
        """Cancel this blind's (and its group's) pending repeat tail now."""
        self._hub.cancel_conflicting_repeats(self.device, self.parent_code)

    # -- rail aware command helpers ---------------------------------------

    async def async_stop_command(self) -> bool:
        """Stop the blind."""
        return await self.async_send(CMD_STOP, reason="stop")

    async def async_up_command(self) -> bool:
        """Drive the blind fully open on its rail."""
        cmd = CMD_UP if self.rail == 1 else CMD_UP2 if self.rail == 2 else None
        if cmd is None:
            return False
        return await self.async_send(cmd, reason="open")

    async def async_down_command(self) -> bool:
        """Drive the blind fully closed on its rail."""
        cmd = CMD_DOWN if self.rail == 1 else CMD_DOWN2 if self.rail == 2 else None
        if cmd is None:
            return False
        return await self.async_send(cmd, reason="close")

    async def async_favourite_command(self) -> bool:
        """Recall the single stored favourite (gp).

        Only ever ``gp`` is sent. ``i2`` (the second favourite) is a ``no``
        motor command that bf motors silently drop, so it is never used.
        """
        return await self.async_send(CMD_FAV, reason="favourite")

    async def async_open_cover_tilt(self) -> bool:
        """Micro up on this blind's rail."""
        cmd = (
            CMD_MICRO_UP
            if self.rail == 1
            else CMD_MICRO_UP2
            if self.rail == 2
            else None
        )
        if cmd is None:
            return False
        return await self.async_send(cmd, reason="tilt open")

    async def async_close_cover_tilt(self) -> bool:
        """Micro down on this blind's rail."""
        cmd = (
            CMD_MICRO_DOWN
            if self.rail == 1
            else CMD_MICRO_DOWN2
            if self.rail == 2
            else None
        )
        if cmd is None:
            return False
        return await self.async_send(cmd, reason="tilt close")

    async def async_set_position_by_percent(self, pos: int) -> bool:
        """Send an absolute percent target to the hub.

        NeoSmartBlinds works in percent closed while Home Assistant works in
        percent open, so the value is inverted and zero padded.
        """
        closed = 100 - int(pos)
        return await self.async_send(f"{closed:02}", reason="position")

    async def async_send_raw(self, command: str) -> bool:
        """Send an arbitrary raw command, for the manual service."""
        return await self.async_send(command, reason="manual service")


class NeoHub:
    """Owns the shared state for one physical NeoSmartBlinds hub."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        connection: dict,
        tuning: HubTuning,
    ) -> None:
        """Initialise the hub from its config entry data and tuning."""
        self._hass = hass
        self._entry_id = entry_id
        self._host = connection[CONF_HOST]
        self._port = int(connection[CONF_PORT])
        self._hub_id = connection[CONF_HUB_ID]
        self._protocol = str(connection[CONF_PROTOCOL]).lower()
        self.tuning = tuning

        self._lock = asyncio.Lock()
        self._time_of_last_command = time.monotonic()

        self._parents: dict[str, _Aggregator] = {}
        self._group_children: dict[str, set[str]] = {}
        self._child_senders: dict[str, BlindClient] = {}
        self._repeat_tasks: dict[str, dict] = {}

        self.counters = HubCounters()
        self._log: deque[CommandRecord] = deque(maxlen=COMMAND_LOG_SIZE)
        self._connected: bool | None = None
        self._last_record: CommandRecord | None = None

    # -- lifecycle ---------------------------------------------------------

    def client_for(self, blind: BlindConfig) -> BlindClient:
        """Create and register a command client for a blind."""
        client = BlindClient(self, blind)
        if client.parent_code:
            agg = self._parents.get(client.parent_code)
            if agg is None:
                agg = _Aggregator(self.tuning.aggregation_period)
                self._parents[client.parent_code] = agg
            agg.add_child()
            self._group_children.setdefault(client.parent_code, set()).add(
                client.device
            )
            self._child_senders[client.device] = client
        return client

    def release(self, client: BlindClient) -> None:
        """Deregister a client on entity removal so group state stays true."""
        self._cancel_repeats(client.device)
        self._child_senders.pop(client.device, None)
        parent = client.parent_code
        if parent:
            children = self._group_children.get(parent)
            if children is not None:
                children.discard(client.device)
            agg = self._parents.get(parent)
            if agg is not None:
                agg.remove_child()
                if agg.child_count <= 0:
                    self._cancel_repeats(parent)
                    self._group_children.pop(parent, None)
                    self._parents.pop(parent, None)

    async def async_shutdown(self) -> None:
        """Cancel every pending repeat when the entry unloads."""
        for record in list(self._repeat_tasks.values()):
            task = record.get("task")
            if task is not None and not task.done():
                task.cancel()
        self._repeat_tasks.clear()

    # -- diagnostics -------------------------------------------------------

    @property
    def connected(self) -> bool | None:
        """Last known reachability of the hub, None until first contact."""
        return self._connected

    @property
    def last_record(self) -> CommandRecord | None:
        """The most recent command record, for the sensors."""
        return self._last_record

    def recent(self, limit: int = 50) -> list[dict]:
        """Recent command records, newest last, for the diagnostics dump."""
        records = list(self._log)[-limit:]
        return [r.as_dict() for r in records]

    def diagnostics(self) -> dict:
        """Return a redactable snapshot of hub state."""
        return {
            "host": self._host,
            "port": self._port,
            "protocol": self._protocol,
            "connected": self._connected,
            "counters": self.counters.as_dict(),
            "groups": {
                code: {
                    "children": sorted(self._group_children.get(code, set())),
                    "child_count": agg.child_count,
                }
                for code, agg in self._parents.items()
            },
            "pending_repeats": sorted(self._repeat_tasks),
            "recent_commands": self.recent(),
        }

    # -- sending -----------------------------------------------------------

    async def async_send(
        self, client: BlindClient, command: str, *, reason: str = "command"
    ) -> bool:
        """Send a command for a blind, aggregating and scheduling repeats.

        A new command first supersedes any pending repeats for this blind, its
        group, and (if this blind IS being broadcast to its group) its children,
        so a stop can never be chased by a stale repeat of the move it stopped.
        """
        device = client.device
        parent = client.parent_code
        self.cancel_conflicting_repeats(device, parent)

        action = _USE_DEVICE
        if parent and parent in self._parents:
            agg = self._parents[parent]
            if agg.register_intent(command):
                await agg.async_wait_window()
                action = agg.act_on_intent()
                agg.unregister_intent()

        if action == _CHANGE_DEVICE:
            await self._backoff()
            ok = await self._transmit(
                parent, command, client.motor_code, "group", "group broadcast"
            )
            self.counters.group_broadcasts += 1
            self._schedule_repeats(client, command, parent)
            return ok
        if action == _IGNORE:
            self.counters.aggregated += 1
            self._record(
                device, command, "aggregated", "aggregated into group broadcast", True
            )
            return True

        await self._backoff()
        ok = await self._transmit(device, command, client.motor_code, "command", reason)
        self._schedule_repeats(client, command, device)
        return ok

    async def _backoff(self) -> None:
        """Hold each command start at least the backoff apart."""
        now = time.monotonic()
        since = now - self._time_of_last_command
        sleep = 0.0
        if since < self.tuning.command_backoff:
            sleep = self.tuning.command_backoff - since
        self._time_of_last_command = now + sleep
        if sleep > 0:
            await asyncio.sleep(sleep)

    # -- repeats -----------------------------------------------------------

    def _repeat_delays(self, client: BlindClient, command: str) -> list[float]:
        """Delays (each after the previous attempt) for a command's repeats."""
        if command in REPEATABLE_DRIVES:
            count = self.tuning.repeat_count
            return [self.tuning.repeat_spacing] * count
        if command == CMD_STOP and self.tuning.repeat_stop:
            count = self.tuning.repeat_count
            return [self.tuning.repeat_spacing] * count
        if command == CMD_FAV and self.tuning.favourite_repeat:
            return [client.gp_repeat_delay]
        return []

    def _schedule_repeats(self, client: BlindClient, command: str, device: str) -> None:
        """Schedule a command's repeat tail against a device."""
        delays = self._repeat_delays(client, command)
        if delays:
            self._schedule_repeats_with_delays(client, command, device, delays)

    def _schedule_repeats_with_delays(
        self, client: BlindClient, command: str, device: str, delays: list[float]
    ) -> None:
        """Install a repeat tail, replacing any existing one for the device."""
        if not delays:
            return
        self._cancel_repeats(device)
        record: dict = {
            "command": command,
            "client": client,
            "remaining": list(delays),
            "task": None,
        }
        self._repeat_tasks[device] = record
        record["task"] = self._hass.async_create_task(
            self._repeat_later(client, command, device, list(delays), record)
        )

    async def _repeat_later(
        self,
        client: BlindClient,
        command: str,
        device: str,
        delays: list[float],
        record: dict,
    ) -> None:
        """Re-send a command once per delay, cancelled by any new command.

        These blinds give no position feedback, so a repeat is never skipped on
        the assumption the blind arrived. Every re-send flows through the same
        backoff and connection lock, so the protocol constraints hold.
        """
        try:
            for attempt, delay in enumerate(delays):
                await asyncio.sleep(delay)
                record["remaining"] = list(delays[attempt + 1 :])
                await self._backoff()
                await self._transmit(
                    device,
                    command,
                    client.motor_code,
                    "repeat",
                    f"repeat {attempt + 1}/{len(delays)}",
                )
                self.counters.repeats_sent += 1
        except asyncio.CancelledError:
            pass
        finally:
            if self._repeat_tasks.get(device) is record:
                self._repeat_tasks.pop(device, None)

    def _cancel_repeats(self, device: str) -> dict | None:
        """Cancel and return the pending repeat record for a device."""
        record = self._repeat_tasks.pop(device, None)
        if record is not None:
            task = record.get("task")
            if task is not None and not task.done():
                task.cancel()
        return record

    def cancel_conflicting_repeats(self, device: str, parent: str) -> None:
        """Cancel every pending repeat a new command for ``device`` supersedes.

        The device's own repeats, its group's repeats (an individual command
        invalidates a broadcast intent), and, when the command IS the group, all
        of its children's repeats. When an individual command cancels a group
        tail, the group's intent is still valid for every OTHER blind in the
        group, so the remaining tail is re-issued to them individually rather
        than thrown away.
        """
        self._cancel_repeats(device)

        if parent:
            group_record = self._cancel_repeats(parent)
            if group_record is not None:
                remaining = group_record.get("remaining") or []
                command = group_record.get("command")
                if remaining and command is not None:
                    for child in self._group_children.get(parent, ()):
                        if child == device:
                            continue
                        child_client = self._child_senders.get(child)
                        if child_client is None:
                            continue
                        self._schedule_repeats_with_delays(
                            child_client, command, child, list(remaining)
                        )

        for child in self._group_children.get(device, ()):  # device may be a group
            self._cancel_repeats(child)

    # -- transport ---------------------------------------------------------

    async def _transmit(
        self, device: str, command: str, motor_code: str, kind: str, reason: str
    ) -> bool:
        """Send one frame to the hub under the single connection lock."""
        mc = f"!{motor_code}" if motor_code else ""
        ok = False
        detail = ""
        try:
            async with self._lock:
                if self._protocol == PROTOCOL_TCP:
                    detail = await self._tcp_send(device, command, mc)
                else:
                    detail = await self._http_send(device, command, mc)
            ok = True
        except Exception as err:
            detail = repr(err)
            _LOGGER.warning("%s, transport failure for %s: %s", device, command, detail)

        self._on_io_complete(device, ok, detail)
        if kind == "command":
            self.counters.commands_sent += 1
            self.counters.by_command[command] = (
                self.counters.by_command.get(command, 0) + 1
            )
        if not ok:
            self.counters.transport_failures += 1
        self._record(device, command, kind, reason, ok, detail if not ok else "")
        return ok

    async def _tcp_send(self, device: str, command: str, mc: str) -> str:
        """Transmit over TCP. Returns the decoded echo for diagnostics."""

        async def _io() -> str:
            reader, writer = await asyncio.open_connection(self._host, self._port)
            frame = f"{device}-{command}{mc}\r\n"
            if self.tuning.log_commands:
                _LOGGER.info("%s, Tx: %s", device, frame.strip())
            writer.write(frame.encode())
            await writer.drain()
            response = await reader.read()
            decoded = response.decode(errors="replace")
            if self.tuning.log_commands:
                _LOGGER.info("%s, Rx: %s", device, decoded.strip())
            # The hub echoes even invalid commands and includes the motor code
            # where the doc shows it stripped, so the echo cannot gate success.
            # An empty or mismatched echo is still worth a warning for diagnosis.
            expected = f"{device}-{command}"
            if not decoded.strip():
                self.counters.echo_warnings += 1
                _LOGGER.warning("%s, no echo received for %s", device, command)
            elif expected not in decoded:
                self.counters.echo_warnings += 1
                _LOGGER.warning(
                    "%s, echo mismatch: sent %s, got %s",
                    device,
                    expected,
                    decoded.strip(),
                )
            writer.close()
            await writer.wait_closed()
            return decoded.strip()

        return await asyncio.wait_for(_io(), timeout=self.tuning.io_timeout)

    async def _http_send(self, device: str, command: str, mc: str) -> str:
        """Transmit over HTTP. Returns the response body for diagnostics."""
        session = async_get_clientsession(self._hass)
        url = f"http://{self._host}:{self._port}/neo/v1/transmit"
        params = {
            "id": self._hub_id,
            "command": f"{device}-{command}{mc}",
            "hash": str(datetime.now().microsecond).zfill(7),
        }
        timeout = aiohttp.ClientTimeout(total=self.tuning.io_timeout)
        async with session.get(
            url, params=params, timeout=timeout, raise_for_status=True
        ) as resp:
            body = await resp.text()
            if self.tuning.log_commands:
                _LOGGER.info("%s, Tx: %s", device, resp.url)
                _LOGGER.info("%s, Rx: %s - %s", device, resp.status, body.strip())
            return body.strip()

    def _on_io_complete(self, device: str, ok: bool, detail: str) -> None:
        """Track reachability, logging only on change."""
        if ok:
            if not self._connected:
                _LOGGER.info("%s, connected to hub", device)
            self._connected = True
        else:
            if self._connected or self._connected is None:
                _LOGGER.warning("%s, disconnected from hub: %s", device, detail)
            self._connected = False

    def _record(
        self,
        device: str,
        command: str,
        kind: str,
        reason: str,
        ok: bool | None,
        detail: str = "",
    ) -> None:
        """Append a command record and notify the sensors."""
        record = CommandRecord(
            at=time.time(),
            monotonic=time.monotonic(),
            device=device,
            command=command,
            kind=kind,
            reason=reason,
            ok=ok,
            detail=detail,
        )
        self._log.append(record)
        self._last_record = record
        async_dispatcher_send(self._hass, SIGNAL_UPDATE.format(self._entry_id))
