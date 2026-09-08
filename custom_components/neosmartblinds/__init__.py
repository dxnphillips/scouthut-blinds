"""The NeoSmartBlinds integration.

A UI configured, HACS distributed fork of the original neosmartblinds platform,
tuned for the Scout Hut ``bf`` motor blinds. One config entry is one physical
hub; the blinds on it are added through the options flow.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .hub import NeoHub
from .options import build_tuning

_LOGGER = logging.getLogger(__name__)

# Plain alias rather than a PEP 695 ``type`` statement so the module still
# byte compiles under Python 3.11 tooling; runtime and typing are identical.
NeoConfigEntry = ConfigEntry[NeoHub]


async def async_setup_entry(hass: HomeAssistant, entry: NeoConfigEntry) -> bool:
    """Set up a hub from a config entry."""
    tuning = build_tuning(entry.options)
    hub = NeoHub(hass, entry.entry_id, dict(entry.data), tuning)
    entry.runtime_data = hub

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NeoConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: NeoConfigEntry) -> None:
    """Reload when the blind list or tuning changes in the options flow."""
    await hass.config_entries.async_reload(entry.entry_id)
