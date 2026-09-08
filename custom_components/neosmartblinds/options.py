"""Helpers that turn stored entry options into typed runtime objects.

Kept separate from ``__init__`` so tests and the config flow can build the same
tuning without importing the platform setup.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .const import (
    CONF_AGGREGATION_PERIOD,
    CONF_BLINDS,
    CONF_COMMAND_BACKOFF,
    CONF_FAV_IDLE_GUARD,
    CONF_FAV_REPEAT,
    CONF_FAV_SETTLE_TIMEOUT,
    CONF_IO_TIMEOUT,
    CONF_LOG_COMMANDS,
    CONF_REPEAT_COUNT,
    CONF_REPEAT_SPACING,
    CONF_REPEAT_STOP,
    DEFAULT_AGGREGATION_PERIOD,
    DEFAULT_COMMAND_BACKOFF,
    DEFAULT_FAV_IDLE_GUARD,
    DEFAULT_FAV_REPEAT,
    DEFAULT_FAV_SETTLE_TIMEOUT,
    DEFAULT_IO_TIMEOUT,
    DEFAULT_REPEAT_COUNT,
    DEFAULT_REPEAT_SPACING,
    DEFAULT_REPEAT_STOP,
    MAX_REPEAT_COUNT,
    MIN_COMMAND_BACKOFF,
)
from .models import BlindConfig, HubTuning


def build_tuning(options: Mapping[str, Any]) -> HubTuning:
    """Resolve the timing and repeat options, clamped to safe bounds.

    The backoff floor and the repeat count cap are enforced here so an option
    typed by hand cannot drive the hub below the vendor's 500ms spacing or
    schedule an unbounded repeat storm.
    """
    return HubTuning(
        command_backoff=max(
            MIN_COMMAND_BACKOFF,
            float(options.get(CONF_COMMAND_BACKOFF, DEFAULT_COMMAND_BACKOFF)),
        ),
        aggregation_period=max(
            0.0, float(options.get(CONF_AGGREGATION_PERIOD, DEFAULT_AGGREGATION_PERIOD))
        ),
        io_timeout=max(1.0, float(options.get(CONF_IO_TIMEOUT, DEFAULT_IO_TIMEOUT))),
        repeat_count=min(
            MAX_REPEAT_COUNT,
            max(0, int(options.get(CONF_REPEAT_COUNT, DEFAULT_REPEAT_COUNT))),
        ),
        repeat_spacing=max(
            0.5, float(options.get(CONF_REPEAT_SPACING, DEFAULT_REPEAT_SPACING))
        ),
        repeat_stop=bool(options.get(CONF_REPEAT_STOP, DEFAULT_REPEAT_STOP)),
        favourite_repeat=bool(options.get(CONF_FAV_REPEAT, DEFAULT_FAV_REPEAT)),
        favourite_idle_guard=max(
            0.0, float(options.get(CONF_FAV_IDLE_GUARD, DEFAULT_FAV_IDLE_GUARD))
        ),
        favourite_settle_timeout=max(
            0.0,
            float(options.get(CONF_FAV_SETTLE_TIMEOUT, DEFAULT_FAV_SETTLE_TIMEOUT)),
        ),
        log_commands=bool(options.get(CONF_LOG_COMMANDS, True)),
    )


def blinds_from_options(options: Mapping[str, Any]) -> list[BlindConfig]:
    """Read the configured blinds out of the entry options."""
    raw = options.get(CONF_BLINDS) or []
    return [BlindConfig.from_dict(item) for item in raw]
