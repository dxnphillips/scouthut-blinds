"""Option resolution and clamping."""

from __future__ import annotations

from custom_components.neosmartblinds.const import (
    CONF_BLINDS,
    CONF_COMMAND_BACKOFF,
    CONF_REPEAT_SCHEDULE,
    DEFAULT_COMMAND_BACKOFF,
    DEFAULT_REPEAT_SCHEDULE,
    MAX_REPEAT_ENTRIES,
    MIN_COMMAND_BACKOFF,
    MIN_REPEAT_SPACING,
)
from custom_components.neosmartblinds.models import BlindConfig
from custom_components.neosmartblinds.options import (
    blinds_from_options,
    build_tuning,
    parse_repeat_schedule,
)


def test_defaults() -> None:
    tuning = build_tuning({})
    assert tuning.command_backoff == DEFAULT_COMMAND_BACKOFF
    assert tuning.repeat_schedule == list(DEFAULT_REPEAT_SCHEDULE)
    assert tuning.log_commands is True


def test_backoff_floor() -> None:
    """The backoff can never drop below the vendor 500ms floor."""
    tuning = build_tuning({CONF_COMMAND_BACKOFF: 0.1})
    assert tuning.command_backoff == MIN_COMMAND_BACKOFF


def test_schedule_parsing() -> None:
    """A schedule reads from a list or a comma string, and is clamped."""
    assert parse_repeat_schedule([4, 15, 45]) == [4, 15, 45]
    assert parse_repeat_schedule("4, 15, 45") == [4, 15, 45]
    # Blank means no repeats.
    assert parse_repeat_schedule("") == []
    assert parse_repeat_schedule([]) == []
    # Each entry is floored at the minimum spacing, and junk is dropped.
    assert parse_repeat_schedule("0.1, x, 5") == [MIN_REPEAT_SPACING, 5]
    # Length is capped.
    assert len(parse_repeat_schedule([1] * 50)) == MAX_REPEAT_ENTRIES


def test_schedule_through_build_tuning() -> None:
    assert build_tuning({CONF_REPEAT_SCHEDULE: "4, 8"}).repeat_schedule == [4, 8]
    assert build_tuning({CONF_REPEAT_SCHEDULE: ""}).repeat_schedule == []


def test_favourite_multipliers() -> None:
    """Favourite multipliers default to the escalating list and floor at one."""
    from custom_components.neosmartblinds.const import (
        DEFAULT_FAV_REPEAT_MULTIPLIERS,
        MIN_FAV_MULTIPLIER,
    )
    from custom_components.neosmartblinds.options import parse_fav_multipliers

    assert parse_fav_multipliers(None) == list(DEFAULT_FAV_REPEAT_MULTIPLIERS)
    assert parse_fav_multipliers("1, 2, 4") == [1, 2, 4]
    assert parse_fav_multipliers("") == []
    # Below one would fire gp mid travel, so it is floored.
    assert parse_fav_multipliers("0.2, 3") == [MIN_FAV_MULTIPLIER, 3]
    assert build_tuning({}).favourite_repeat_multipliers == list(
        DEFAULT_FAV_REPEAT_MULTIPLIERS
    )


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
