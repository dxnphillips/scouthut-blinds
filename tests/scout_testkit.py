"""Shared builders for the offline tests."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from custom_components.neosmartblinds.hub import NeoHub
from custom_components.neosmartblinds.models import BlindConfig
from custom_components.neosmartblinds.options import build_tuning


class FakeHass:
    """Just enough Home Assistant for the hub to schedule repeat tasks."""

    def async_create_task(self, coro, *args, **kwargs):
        """Schedule a coroutine on the running loop."""
        return asyncio.ensure_future(coro)


CONNECTION = {
    "host": "192.168.0.13",
    "port": 8839,
    "hub_id": "440036000447393032323330",
    "protocol": "tcp",
}


def make_hub(hass: Any, **options: Any) -> NeoHub:
    """Build a hub with the given tuning options and no live transport."""
    tuning = build_tuning(options)
    hub = NeoHub(hass, "entry1", dict(CONNECTION), tuning)
    # Skip the real backoff sleeps in unit tests by pretending the last command
    # was long ago; individual tests that care about backoff override this.
    hub._time_of_last_command = time.monotonic() - 100
    return hub


def make_blind(
    blind_id: str = "b1",
    name: str = "Blind 1",
    blind_code: str = "021.230-01",
    motor_code: str = "bf",
    close_time: int = 20,
    rail: int = 1,
    parent_group: str = "",
) -> BlindConfig:
    """Build a blind configuration."""
    return BlindConfig(
        blind_id=blind_id,
        name=name,
        blind_code=blind_code,
        motor_code=motor_code,
        close_time=close_time,
        rail=rail,
        parent_group=parent_group,
    )
