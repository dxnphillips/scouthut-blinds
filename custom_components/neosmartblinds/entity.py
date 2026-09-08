"""Base entity for the NeoSmartBlinds diagnostic platforms."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, SIGNAL_UPDATE
from .hub import NeoHub


class NeoHubEntity(Entity):
    """A diagnostic entity that redraws when the hub transmits."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: NeoHub, entry: ConfigEntry, key: str) -> None:
        """Initialise against the hub and config entry."""
        self.hub = hub
        self.entry = entry
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="NeoSmartBlinds",
            model="Smart Controller",
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to hub updates."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_UPDATE.format(self.entry.entry_id),
                self.async_write_ha_state,
            )
        )
