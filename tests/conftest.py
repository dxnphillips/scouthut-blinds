"""Offline test harness.

These tests run without Home Assistant installed. The integration modules under
test (const, models, options, hub) import only a small slice of the Home
Assistant surface, so that slice is stubbed here into ``sys.modules`` before the
package is imported. The cover and config flow, which pull in the full HA cover
and selector surface, are exercised inside Home Assistant, not here.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

# Make ``custom_components.neosmartblinds`` importable from the repo root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _install_stub(
    name: str, *, package: bool = False, **attrs: object
) -> types.ModuleType:
    """Install a stub module (or package) into sys.modules and return it."""
    module = types.ModuleType(name)
    if package:
        module.__path__ = []  # marks it importable as a package
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _stub_homeassistant() -> None:
    """Stub the minimal Home Assistant and aiohttp surface for the unit tests."""
    if "homeassistant" in sys.modules:
        return

    class _Platform:
        COVER = "cover"
        BINARY_SENSOR = "binary_sensor"
        SENSOR = "sensor"

    class _HomeAssistant:
        """Placeholder Home Assistant type."""

    class _ConfigEntry:
        """Placeholder config entry that supports ConfigEntry[...] subscripting."""

        def __class_getitem__(cls, item):
            return cls

    class _ClientTimeout:
        def __init__(self, total: float | None = None) -> None:
            self.total = total

    _install_stub("homeassistant", package=True)
    _install_stub(
        "homeassistant.const",
        Platform=_Platform,
        CONF_HOST="host",
        CONF_PORT="port",
        CONF_NAME="name",
    )
    _install_stub("homeassistant.core", HomeAssistant=_HomeAssistant)
    _install_stub("homeassistant.config_entries", ConfigEntry=_ConfigEntry)
    _install_stub("homeassistant.helpers", package=True)
    _install_stub(
        "homeassistant.helpers.aiohttp_client",
        async_get_clientsession=lambda hass: None,
    )
    _install_stub(
        "homeassistant.helpers.dispatcher",
        async_dispatcher_send=lambda *args, **kwargs: None,
    )
    _install_stub("aiohttp", ClientTimeout=_ClientTimeout)


_stub_homeassistant()
