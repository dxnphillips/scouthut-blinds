"""Diagnostic sensors for the NeoSmartBlinds hub."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import NeoHubEntity
from .hub import NeoHub
from .models import HubCounters


@dataclass(frozen=True, kw_only=True)
class NeoCounterDescription:
    """Describes one counter sensor."""

    key: str
    name: str
    value: Callable[[HubCounters], int]


COUNTERS: tuple[NeoCounterDescription, ...] = (
    NeoCounterDescription(
        key="commands_sent", name="Commands sent", value=lambda c: c.commands_sent
    ),
    NeoCounterDescription(
        key="repeats_sent", name="Repeats sent", value=lambda c: c.repeats_sent
    ),
    NeoCounterDescription(
        key="group_broadcasts",
        name="Group broadcasts",
        value=lambda c: c.group_broadcasts,
    ),
    NeoCounterDescription(
        key="aggregated", name="Aggregated commands", value=lambda c: c.aggregated
    ),
    NeoCounterDescription(
        key="transport_failures",
        name="Transport failures",
        value=lambda c: c.transport_failures,
    ),
    NeoCounterDescription(
        key="echo_warnings", name="Echo warnings", value=lambda c: c.echo_warnings
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the diagnostic sensors."""
    hub: NeoHub = entry.runtime_data
    entities: list[SensorEntity] = [
        NeoCounterSensor(hub, entry, desc) for desc in COUNTERS
    ]
    entities.append(NeoLastCommandSensor(hub, entry))
    async_add_entities(entities)


class NeoCounterSensor(NeoHubEntity, SensorEntity):
    """A running total transmitted by the hub."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(
        self, hub: NeoHub, entry: ConfigEntry, description: NeoCounterDescription
    ) -> None:
        """Initialise from a counter description."""
        super().__init__(hub, entry, description.key)
        self._description = description
        self._attr_name = description.name

    @property
    def native_value(self) -> int:
        """The current counter value."""
        return self._description.value(self.hub.counters)


class NeoLastCommandSensor(NeoHubEntity, SensorEntity):
    """The most recent command the hub sent, with detail attributes."""

    _attr_name = "Last command"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hub: NeoHub, entry: ConfigEntry) -> None:
        """Initialise."""
        super().__init__(hub, entry, "last_command")

    @property
    def native_value(self) -> str | None:
        """A short human label for the last command."""
        record = self.hub.last_record
        if record is None:
            return None
        return f"{record.device} {record.command}"

    @property
    def extra_state_attributes(self) -> dict[str, object] | None:
        """The full last command record."""
        record = self.hub.last_record
        if record is None:
            return None
        return {
            "device": record.device,
            "command": record.command,
            "kind": record.kind,
            "reason": record.reason,
            "ok": record.ok,
            "detail": record.detail,
            "at": datetime.fromtimestamp(record.at, tz=UTC).isoformat(),
        }
