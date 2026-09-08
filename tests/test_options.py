"""Option resolution and clamping."""

from __future__ import annotations

from custom_components.neosmartblinds.const import (
    CONF_BLINDS,
    CONF_COMMAND_BACKOFF,
    CONF_REPEAT_COUNT,
    DEFAULT_COMMAND_BACKOFF,
    DEFAULT_REPEAT_COUNT,
    MAX_REPEAT_COUNT,
    MIN_COMMAND_BACKOFF,
)
from custom_components.neosmartblinds.models import BlindConfig
from custom_components.neosmartblinds.options import blinds_from_options, build_tuning


def test_defaults() -> None:
    tuning = build_tuning({})
    assert tuning.command_backoff == DEFAULT_COMMAND_BACKOFF
    assert tuning.repeat_count == DEFAULT_REPEAT_COUNT
    assert tuning.log_commands is True


def test_backoff_floor() -> None:
    """The backoff can never drop below the vendor 500ms floor."""
    tuning = build_tuning({CONF_COMMAND_BACKOFF: 0.1})
    assert tuning.command_backoff == MIN_COMMAND_BACKOFF


def test_repeat_count_bounds() -> None:
    """A repeat count is clamped to a sane range, and zero is allowed."""
    assert build_tuning({CONF_REPEAT_COUNT: -5}).repeat_count == 0
    assert build_tuning({CONF_REPEAT_COUNT: 0}).repeat_count == 0
    assert build_tuning({CONF_REPEAT_COUNT: 999}).repeat_count == MAX_REPEAT_COUNT


def test_blinds_roundtrip() -> None:
    """A stored blind survives a serialise and parse unchanged."""
    blind = BlindConfig(
        blind_id="abc",
        name="Hall Left",
        blind_code="021.230-04",
        motor_code="bf",
        close_time=25,
        rail=1,
        parent_group="021.230-15",
        start_position=50,
    )
    options = {CONF_BLINDS: [blind.as_dict()]}
    parsed = blinds_from_options(options)
    assert len(parsed) == 1
    assert parsed[0] == blind


def test_blinds_empty() -> None:
    assert blinds_from_options({}) == []
