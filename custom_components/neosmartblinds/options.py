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
    CONF_BUTTONS,
    CONF_COMMAND_BACKOFF,
    CONF_FAV_IDLE_GUARD,
    CONF_FAV_REPEAT,
    CONF_FAV_SETTLE_TIMEOUT,
    CONF_IO_TIMEOUT,
    CONF_LOG_COMMANDS,
    CONF_REPEAT_SCHEDULE,
    CONF_REPEAT_STOP,
    DEFAULT_AGGREGATION_PERIOD,
    DEFAULT_COMMAND_BACKOFF,
    DEFAULT_FAV_IDLE_GUARD,
    DEFAULT_FAV_REPEAT,
    DEFAULT_FAV_SETTLE_TIMEOUT,
    DEFAULT_IO_TIMEOUT,
    DEFAULT_REPEAT_SCHEDULE,
    DEFAULT_REPEAT_STOP,
    MAX_REPEAT_ENTRIES,
    MIN_COMMAND_BACKOFF,
    MIN_REPEAT_SPACING,
)
from .models import BlindConfig, ButtonBinding, HubTuning


def parse_repeat_schedule(value: Any) -> list[float]:
    """Turn a stored or typed repeat schedule into a clamped list of delays.

    Accepts a list of numbers or a comma separated string of seconds. Each entry
    is floored at the minimum spacing so a schedule cannot beat the command
    backoff, and the whole thing is capped in length. An empty schedule means no
    repeats.
    """
    if value is None:
        items: list[Any] = list(DEFAULT_REPEAT_SCHEDULE)
    elif isinstance(value, str):
        items = [part.strip() for part in value.split(",") if part.strip()]
    else:
        items = list(value)

    delays: list[float] = []
    for item in items:
        try:
            delay = float(item)
        except (TypeError, ValueError):
            continue
        if delay <= 0:
            continue
        delays.append(max(MIN_REPEAT_SPACING, delay))
    return delays[:MAX_REPEAT_ENTRIES]


def build_tuning(options: Mapping[str, Any]) -> HubTuning:
    """Resolve the timing and repeat options, clamped to safe bounds.

    The backoff floor, the repeat spacing floor and the schedule length cap are
    enforced here so an option typed by hand cannot drive the hub below the
    vendor's 500ms spacing or schedule an unbounded repeat storm.
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
        repeat_schedule=parse_repeat_schedule(options.get(CONF_REPEAT_SCHEDULE)),
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


def buttons_from_options(options: Mapping[str, Any]) -> list[ButtonBinding]:
    """Read the configured button bindings out of the entry options."""
    raw = options.get(CONF_BUTTONS) or []
    return [ButtonBinding.from_dict(item) for item in raw]
