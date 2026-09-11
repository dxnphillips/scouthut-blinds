"""The end stop repeat policy and cancellation, the flapping surface.

The repeats themselves are essential: the RF is lossy enough that it can take the
whole escalating schedule for every blind to catch a frame. So these tests fix
on the real invariant, that no physical blind is ever left with two pending
tails driving it opposite ways.
"""

from __future__ import annotations

import asyncio

from scout_testkit import FakeHass, make_blind, make_hub

from custom_components.neosmartblinds.const import (
    CMD_DOWN,
    CMD_FAV,
    CMD_STOP,
    CMD_UP,
    CONF_FAV_REPEAT_MULTIPLIERS,
    CONF_REPEAT_STOP,
    DEFAULT_FAV_REPEAT_MULTIPLIERS,
    DEFAULT_REPEAT_SCHEDULE,
)


def test_drive_repeats_use_the_schedule() -> None:
    hub = make_hub(FakeHass(), repeat_schedule=[5, 5, 5])
    client = hub.client_for(make_blind())
    assert hub._repeat_delays(client, CMD_UP) == [5, 5, 5]
    assert hub._repeat_delays(client, CMD_DOWN) == [5, 5, 5]


def test_default_schedule_is_the_escalating_one() -> None:
    """Out of the box the long escalating schedule is used, the hut needs it."""
    hub = make_hub(FakeHass())
    client = hub.client_for(make_blind())
    assert hub._repeat_delays(client, CMD_UP) == list(DEFAULT_REPEAT_SCHEDULE)


def test_empty_schedule_disables_drive_repeats() -> None:
    hub = make_hub(FakeHass(), repeat_schedule=[])
    client = hub.client_for(make_blind())
    assert hub._repeat_delays(client, CMD_UP) == []
    assert hub._repeat_delays(client, CMD_DOWN) == []


def test_stop_not_repeated_by_default() -> None:
    hub = make_hub(FakeHass(), repeat_schedule=[5, 5])
    client = hub.client_for(make_blind())
    assert hub._repeat_delays(client, CMD_STOP) == []


def test_stop_repeated_when_opted_in() -> None:
    hub = make_hub(FakeHass(), repeat_schedule=[4, 4], **{CONF_REPEAT_STOP: True})
    client = hub.client_for(make_blind())
    assert hub._repeat_delays(client, CMD_STOP) == [4, 4]


def test_favourite_repeats_escalate() -> None:
    """The favourite needs many repeats, spaced by multiples of a full travel."""
    hub = make_hub(FakeHass())
    client = hub.client_for(make_blind(close_time=20))
    delays = hub._repeat_delays(client, CMD_FAV)
    assert delays == [
        m * client.gp_repeat_delay for m in DEFAULT_FAV_REPEAT_MULTIPLIERS
    ]
    # Six attempts, every one at least a full travel apart so gp lands stationary.
    assert len(delays) == 6
    assert min(delays) >= client.gp_repeat_delay


def test_favourite_repeats_can_be_disabled() -> None:
    hub = make_hub(FakeHass(), **{CONF_FAV_REPEAT_MULTIPLIERS: []})
    client = hub.client_for(make_blind())
    assert hub._repeat_delays(client, CMD_FAV) == []


def test_an_individual_command_supersedes_its_own_tail() -> None:
    async def _run() -> None:
        hub = make_hub(FakeHass(), repeat_schedule=[100])
        client = hub.client_for(make_blind(blind_code="021.230-01"))
        hub._schedule_repeats(client, CMD_UP, client.device)
        assert client.device in hub._repeat_tasks
        hub.supersede_individual(client.device, "")
        assert client.device not in hub._repeat_tasks
        await hub.async_shutdown()

    asyncio.run(_run())


def test_individual_command_hands_the_group_tail_to_siblings() -> None:
    """Redirecting one blind keeps the group intent alive for the others."""

    async def _run() -> None:
        hub = make_hub(FakeHass(), repeat_schedule=[100])
        group = "040.001-15"
        c1 = hub.client_for(
            make_blind(blind_id="b1", blind_code="040.001-01", parent_group=group)
        )
        c2 = hub.client_for(
            make_blind(blind_id="b2", blind_code="040.001-02", parent_group=group)
        )
        hub._schedule_repeats(c1, CMD_UP, group)
        assert group in hub._repeat_tasks

        hub.supersede_individual(c1.device, group)
        assert group not in hub._repeat_tasks
        assert c1.device not in hub._repeat_tasks
        # The sibling inherits the group intent as its own individual tail.
        assert c2.device in hub._repeat_tasks
        await hub.async_shutdown()

    asyncio.run(_run())


def test_group_broadcast_clears_every_member_tail() -> None:
    """The opposite-direction guard: a broadcast leaves no stale member tail.

    Two members are given opposite individual tails (a mixed state). A fresh
    whole hall broadcast must cancel both, with nothing inherited, so neither
    member is left being driven the other way while channel 15 drives them all.
    """

    async def _run() -> None:
        hub = make_hub(FakeHass(), repeat_schedule=[100])
        group = "040.001-15"
        c1 = hub.client_for(
            make_blind(blind_id="b1", blind_code="040.001-01", parent_group=group)
        )
        c2 = hub.client_for(
            make_blind(blind_id="b2", blind_code="040.001-02", parent_group=group)
        )
        hub._schedule_repeats_with_delays(c1, CMD_DOWN, c1.device, [100])
        hub._schedule_repeats_with_delays(c2, CMD_UP, c2.device, [100])
        assert c1.device in hub._repeat_tasks
        assert c2.device in hub._repeat_tasks

        hub._supersede_group(group)

        assert c1.device not in hub._repeat_tasks
        assert c2.device not in hub._repeat_tasks
        assert group not in hub._repeat_tasks
        await hub.async_shutdown()

    asyncio.run(_run())


def test_send_transmits_once_and_counts() -> None:
    async def _run() -> None:
        hub = make_hub(FakeHass(), repeat_schedule=[])
        client = hub.client_for(make_blind())
        sent: list[tuple[str, str, str]] = []

        async def fake_tcp(device: str, command: str, mc: str) -> str:
            sent.append((device, command, mc))
            return f"{device}-{command}"

        hub._tcp_send = fake_tcp
        ok = await hub.async_send(client, CMD_UP)

        assert ok is True
        assert sent == [("021.230-01", "up", "!bf")]
        assert hub.counters.commands_sent == 1
        assert hub.counters.by_command["up"] == 1
        assert client.device not in hub._repeat_tasks

    asyncio.run(_run())


def test_repeats_are_scheduled_when_enabled() -> None:
    async def _run() -> None:
        hub = make_hub(FakeHass(), repeat_schedule=[100])
        client = hub.client_for(make_blind())

        async def fake_tcp(device: str, command: str, mc: str) -> str:
            return f"{device}-{command}"

        hub._tcp_send = fake_tcp
        await hub.async_send(client, CMD_UP)
        assert client.device in hub._repeat_tasks
        await hub.async_shutdown()

    asyncio.run(_run())
