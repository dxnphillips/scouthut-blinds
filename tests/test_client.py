"""Per blind command building and transport bookkeeping."""

from __future__ import annotations

import asyncio

from scout_testkit import FakeHass, make_blind, make_hub

from custom_components.neosmartblinds.const import CONF_FAV_REPEAT_MULTIPLIERS


def _capture_hub():
    """A hub whose transport records frames and whose backoff is a no op."""
    hub = make_hub(FakeHass(), repeat_schedule=[], **{CONF_FAV_REPEAT_MULTIPLIERS: []})
    sent: list[tuple[str, str, str]] = []

    async def fake_tcp(device: str, command: str, mc: str) -> str:
        sent.append((device, command, mc))
        return f"{device}-{command}"

    async def no_backoff() -> None:
        return None

    hub._tcp_send = fake_tcp
    hub._backoff = no_backoff
    return hub, sent


def test_rail_one_open_close() -> None:
    async def _run() -> None:
        hub, sent = _capture_hub()
        client = hub.client_for(make_blind(rail=1))
        await client.async_up_command()
        await client.async_down_command()
        await client.async_stop_command()
        assert [c for _, c, _ in sent] == ["up", "dn", "sp"]

    asyncio.run(_run())


def test_rail_two_uses_second_rail_codes() -> None:
    async def _run() -> None:
        hub, sent = _capture_hub()
        client = hub.client_for(make_blind(rail=2))
        await client.async_up_command()
        await client.async_down_command()
        assert [c for _, c, _ in sent] == ["u2", "d2"]

    asyncio.run(_run())


def test_favourite_only_sends_gp() -> None:
    async def _run() -> None:
        hub, sent = _capture_hub()
        client = hub.client_for(make_blind())
        await client.async_favourite_command()
        assert [c for _, c, _ in sent] == ["gp"]

    asyncio.run(_run())


def test_percent_is_inverted_and_padded() -> None:
    """Home Assistant percent open becomes the hub's percent closed, zero padded."""

    async def _run() -> None:
        hub, sent = _capture_hub()
        client = hub.client_for(make_blind())
        await client.async_set_position_by_percent(30)
        await client.async_set_position_by_percent(100)
        assert [c for _, c, _ in sent] == ["70", "00"]

    asyncio.run(_run())


def test_motor_code_suffix() -> None:
    async def _run() -> None:
        hub, sent = _capture_hub()
        client = hub.client_for(make_blind(motor_code="bf"))
        await client.async_up_command()
        assert sent[-1][2] == "!bf"

    asyncio.run(_run())


def test_transport_failure_is_counted() -> None:
    async def _run() -> None:
        hub = make_hub(FakeHass(), repeat_schedule=[])

        async def failing_tcp(device: str, command: str, mc: str) -> str:
            raise OSError("connection refused")

        async def no_backoff() -> None:
            return None

        hub._tcp_send = failing_tcp
        hub._backoff = no_backoff
        client = hub.client_for(make_blind())
        ok = await client.async_up_command()
        assert ok is False
        assert hub.counters.transport_failures == 1
        assert hub.connected is False

    asyncio.run(_run())
