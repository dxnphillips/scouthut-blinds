"""Diagnostics for NeoSmartBlinds.

The whole point of the config entry rewrite: a downloadable, redacted snapshot
of what the hub has actually been doing, so intermittent blind flapping can be
reasoned about from evidence rather than guessed at. The recent command log
shows every frame, repeat, aggregation decision and transport failure in order.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .const import CONF_BLINDS, CONF_HUB_ID
from .hub import NeoHub
from .options import build_tuning

REDACT = {CONF_HOST, CONF_HUB_ID, "host"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return a redacted snapshot of hub state and recent activity."""
    runtime = entry.runtime_data
    hub: NeoHub = runtime.hub
    tuning = build_tuning(entry.options)

    data = {
        "connection": dict(entry.data),
        "tuning": asdict(tuning),
        "blind_count": len(entry.options.get(CONF_BLINDS, [])),
        "hub": hub.diagnostics(),
        "buttons": runtime.buttons.diagnostics(),
    }
    return async_redact_data(data, REDACT)
