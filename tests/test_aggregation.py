"""Group aggregation decisions."""

from __future__ import annotations

from custom_components.neosmartblinds.hub import (
    _CHANGE_DEVICE,
    _IGNORE,
    _USE_DEVICE,
    _Aggregator,
)


def _group_of(size: int) -> _Aggregator:
    agg = _Aggregator(2.0)
    for _ in range(size):
        agg.add_child()
    return agg


def test_single_child_sends_individually() -> None:
    """One blind in a group is not aggregated."""
    agg = _group_of(1)
    assert agg.register_intent("up") is True
    assert agg.act_on_intent() == _CHANGE_DEVICE


def test_partial_group_uses_device() -> None:
    """A blind whose group did not fill sends its own frame."""
    agg = _group_of(3)
    assert agg.register_intent("up") is True
    # Only one of three registered before the window closed.
    assert agg.act_on_intent() == _USE_DEVICE


def test_full_group_broadcasts_once() -> None:
    """When every child agrees, exactly one broadcasts and the rest defer."""
    agg = _group_of(2)
    assert agg.register_intent("up") is True
    assert agg.register_intent("up") is True

    first = agg.act_on_intent()
    agg.unregister_intent()
    second = agg.act_on_intent()
    agg.unregister_intent()

    assert {first, second} == {_CHANGE_DEVICE, _IGNORE}


def test_clashing_commands_abandon_aggregation() -> None:
    """A different command from a sibling breaks the group intent."""
    agg = _group_of(2)
    assert agg.register_intent("up") is True
    assert agg.register_intent("dn") is False
