"""The end stop repeat policy and cancellation, the flapping surface."""

from __future__ import annotations

import asyncio

from scout_testkit import FakeHass, make_blind, make_hub

from custom_components.neosmartblinds.const import (
    CMD_DOWN,
    CMD_FAV,
    CMD_STOP,
    CMD_UP,
    CONF_FAV_REPEAT,
    CONF_REPEAT_STOP,
)


def test_drive_repeats_follow_count_and_spacing() -> None:
    hub = make_hub(FakeHass(), repeat_count=3, repeat_spacing=5)
    client = hub.client_for(make_blind())
    assert hub._repeat_delays(client, CMD_UP) == [5, 5, 5]
    assert hub._repeat_delays(client, CMD_DOWN) == [5, 5, 5]


def test_zero_repeats_disables_drive_repeats() -> None:
    """The flapping switch: a count of zero schedules no drive repeats."""
    hub = make_hub(FakeHass(), repeat_count=0)
    client = hub.client_for(make_blind())
    assert hub._repeat_delays(client, CMD_UP) == []
    assert hub._repeat_delays(client, CMD_DOWN) == []


def test_all_repeats_can_be_switched_off() -> None:
    """Drive repeats off and favourite repeat off leaves nothing scheduled."""
    hub = make_hub(FakeHass(), repeat_count=0, **{CONF_FAV_REPEAT: False})
    client = hub.client_for(make_blind())
    assert hub._repeat_delays(client, CMD_UP) == []
    assert hub._repeat_delays(client, CMD_FAV) == []


def test_stop_not_repeated_by_default() -> None:
    hub = make_hub(FakeHass(), repeat_count=2)
    client = hub.client_for(make_blind())
    assert hub._repeat_delays(client, CMD_STOP) == []


def test_stop_repeated_when_opted_in() -> None:
    hub = make_hub(
        FakeHass(), repeat_count=2, repeat_spacing=4, **{CONF_REPEAT_STOP: True}
    )
    client = hub.client_for(make_blind())
    assert hub._repeat_delays(client, CMD_STOP) == [4, 4]


def test_favourite_gets_one_delayed_repeat() -> None:
    hub = make_hub(FakeHass(), close_time=20)
    client = hub.client_for(make_blind(close_time=20))
    delays = hub._repeat_delays(client, CMD_FAV)
    assert delays == [client.gp_repeat_delay]
    # The single repeat lands after a full travel plus the idle guard.
    assert delays[0] > 20


def test_favourite_repeat_can_be_disabled() -> None:
    hub = make_hub(FakeHass(), **{CONF_FAV_REPEAT: False})
    client = hub.client_for(make_blind())
    assert hub._repeat_delays(client, CMD_FAV) == []


def test_a_new_command_cancels_pending_repeats() -> None:
    async def _run() -> None:
        # Long spacing so the scheduled repeat never fires during the test.
        hub = make_hub(FakeHass(), repeat_count=2, repeat_spacing=100)
        client = hub.client_for(make_blind(blind_code="021.230-01"))
        hub._schedule_repeats(client, CMD_UP, client.device)
        assert client.device in hub._repeat_tasks
        # Any new command for the blind supersedes the pending repeats.
        hub.cancel_conflicting_repeats(client.device, "")
        assert client.device not in hub._repeat_tasks
        await hub.async_shutdown()

    asyncio.run(_run())


def test_group_tail_is_inherited_by_siblings() -> None:
    """An individual command cancels the group tail but hands it to siblings."""

    async def _run() -> None:
        hub = make_hub(FakeHass(), repeat_count=2, repeat_spacing=100)
        group = "021.230-15"
        c1 = hub.client_for(
            make_blind(blind_id="b1", blind_code="021.230-01", parent_group=group)
        )
        c2 = hub.client_for(
            make_blind(blind_id="b2", blind_code="021.230-02", parent_group=group)
        )
        # A group broadcast schedules a repeat keyed to the group code.
        hub._schedule_repeats(c1, CMD_UP, group)
        assert group in hub._repeat_tasks

        # An individual command for one blind supersedes the group intent, but
        # the tail is still valid for the other blind, so it inherits it.
        hub.cancel_conflicting_repeats(c1.device, group)
        assert group not in hub._repeat_tasks
        assert c1.device not in hub._repeat_tasks
        assert c2.device in hub._repeat_tasks
        await hub.async_shutdown()

    asyncio.run(_run())


def test_send_transmits_once_and_counts() -> None:
    async def _run() -> None:
        hub = make_hub(FakeHass(), repeat_count=0)
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
        # No repeats scheduled with the count at zero.
        assert client.device not in hub._repeat_tasks

    asyncio.run(_run())


def test_repeats_are_scheduled_when_enabled() -> None:
    async def _run() -> None:
        hub = make_hub(FakeHass(), repeat_count=2, repeat_spacing=100)
        client = hub.client_for(make_blind())

        async def fake_tcp(device: str, command: str, mc: str) -> str:
            return f"{device}-{command}"

        hub._tcp_send = fake_tcp
        await hub.async_send(client, CMD_UP)
        assert client.device in hub._repeat_tasks
        await hub.async_shutdown()

    asyncio.run(_run())
