"""Connectivity binary sensor for the NeoSmartBlinds hub."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import NeoHubEntity
from .hub import NeoHub


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the hub connectivity sensor."""
    hub: NeoHub = entry.runtime_data
    async_add_entities([NeoHubConnectivity(hub, entry)])


class NeoHubConnectivity(NeoHubEntity, BinarySensorEntity):
    """Reports whether the last transmission reached the hub."""

    _attr_name = "Hub connectivity"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hub: NeoHub, entry: ConfigEntry) -> None:
        """Initialise."""
        super().__init__(hub, entry, "connectivity")

    @property
    def is_on(self) -> bool | None:
        """True when the hub is reachable, None until first contact."""
        return self.hub.connected

    @property
    def available(self) -> bool:
        """Unknown until the first command has been attempted."""
        return self.hub.connected is not None
