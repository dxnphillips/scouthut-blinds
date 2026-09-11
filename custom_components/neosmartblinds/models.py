"""Dataclasses shared across the NeoSmartBlinds integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.const import CONF_NAME

from .const import (
    ACTION_TOGGLE,
    CONF_BLIND_CODE,
    CONF_BLIND_ID,
    CONF_BUTTON_ACTION,
    CONF_BUTTON_ID,
    CONF_CLOSE_TIME,
    CONF_COOLDOWN,
    CONF_COVERS,
    CONF_EVENT_ENTITY,
    CONF_EVENT_TYPE,
    CONF_MOTOR_CODE,
    CONF_PARENT,
    CONF_PERCENT_SUPPORT,
    CONF_RAIL,
    CONF_START_POSITION,
    CONF_TRAVEL_CEILING,
    DEFAULT_COOLDOWN,
    DEFAULT_EVENT_TYPE,
    DEFAULT_TRAVEL_CEILING,
    LEGACY_POSITIONING,
)


@dataclass(slots=True)
class BlindConfig:
    """One blind, as configured through the options flow.

    ``blind_id`` is a stable internal identifier minted when the blind is added,
    so a blind can be renamed or its code corrected without its entity being
    torn down and recreated. Everything else mirrors the original YAML keys.
    """

    blind_id: str
    name: str
    blind_code: str
    close_time: int = 20
    rail: int = 1
    percent_support: int = LEGACY_POSITIONING
    motor_code: str = ""
    start_position: int | None = None
    parent_group: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BlindConfig:
        """Build a blind from its stored options dict."""
        start = data.get(CONF_START_POSITION)
        return cls(
            blind_id=str(data[CONF_BLIND_ID]),
            name=str(data[CONF_NAME]),
            blind_code=str(data[CONF_BLIND_CODE]),
            close_time=int(data.get(CONF_CLOSE_TIME, 20)),
            rail=int(data.get(CONF_RAIL, 1)),
            percent_support=int(data.get(CONF_PERCENT_SUPPORT, LEGACY_POSITIONING)),
            motor_code=str(data.get(CONF_MOTOR_CODE, "") or ""),
            start_position=int(start) if start is not None else None,
            parent_group=str(data.get(CONF_PARENT, "") or ""),
        )

    def as_dict(self) -> dict[str, Any]:
        """Serialise back to the stored options form."""
        data: dict[str, Any] = {
            CONF_BLIND_ID: self.blind_id,
            CONF_NAME: self.name,
            CONF_BLIND_CODE: self.blind_code,
            CONF_CLOSE_TIME: self.close_time,
            CONF_RAIL: self.rail,
            CONF_PERCENT_SUPPORT: self.percent_support,
            CONF_MOTOR_CODE: self.motor_code,
            CONF_PARENT: self.parent_group,
        }
        if self.start_position is not None:
            data[CONF_START_POSITION] = self.start_position
        return data


@dataclass(slots=True)
class ButtonBinding:
    """One physical button press mapped to an action on a group of covers.

    ``button_id`` is a stable internal identifier, so a binding can be renamed
    or repointed without losing its place. ``event_type`` is matched against the
    event entity's ``event_type`` attribute; an empty value matches any press.
    """

    button_id: str
    name: str
    event_entity: str
    event_type: str = DEFAULT_EVENT_TYPE
    action: str = ACTION_TOGGLE
    covers: list[str] = field(default_factory=list)
    cooldown: float = DEFAULT_COOLDOWN
    travel_ceiling: float = DEFAULT_TRAVEL_CEILING

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ButtonBinding:
        """Build a binding from its stored options dict."""
        return cls(
            button_id=str(data[CONF_BUTTON_ID]),
            name=str(data[CONF_NAME]),
            event_entity=str(data[CONF_EVENT_ENTITY]),
            event_type=str(data.get(CONF_EVENT_TYPE, DEFAULT_EVENT_TYPE) or ""),
            action=str(data.get(CONF_BUTTON_ACTION, ACTION_TOGGLE)),
            covers=list(data.get(CONF_COVERS, []) or []),
            cooldown=float(data.get(CONF_COOLDOWN, DEFAULT_COOLDOWN)),
            travel_ceiling=float(data.get(CONF_TRAVEL_CEILING, DEFAULT_TRAVEL_CEILING)),
        )

    def as_dict(self) -> dict[str, Any]:
        """Serialise back to the stored options form."""
        return {
            CONF_BUTTON_ID: self.button_id,
            CONF_NAME: self.name,
            CONF_EVENT_ENTITY: self.event_entity,
            CONF_EVENT_TYPE: self.event_type,
            CONF_BUTTON_ACTION: self.action,
            CONF_COVERS: list(self.covers),
            CONF_COOLDOWN: self.cooldown,
            CONF_TRAVEL_CEILING: self.travel_ceiling,
        }


@dataclass(slots=True)
class CommandRecord:
    """A single transmitted (or attempted) command, kept for diagnostics."""

    at: float
    monotonic: float
    device: str
    command: str
    kind: str  # "command", "repeat", "aggregated", "group"
    reason: str
    ok: bool | None = None
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        """Serialise for the diagnostics dump."""
        return {
            "at": self.at,
            "device": self.device,
            "command": self.command,
            "kind": self.kind,
            "reason": self.reason,
            "ok": self.ok,
            "detail": self.detail,
        }


@dataclass(slots=True)
class HubTuning:
    """Resolved timing and repeat options for a hub."""

    command_backoff: float
    aggregation_period: float
    io_timeout: float
    repeat_schedule: list[float]
    repeat_stop: bool
    favourite_repeat_multipliers: list[float]
    favourite_idle_guard: float
    favourite_settle_timeout: float
    log_commands: bool


@dataclass(slots=True)
class HubCounters:
    """Running totals surfaced through diagnostics and sensors."""

    commands_sent: int = 0
    repeats_sent: int = 0
    aggregated: int = 0
    group_broadcasts: int = 0
    transport_failures: int = 0
    echo_warnings: int = 0
    by_command: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Serialise for the diagnostics dump."""
        return {
            "commands_sent": self.commands_sent,
            "repeats_sent": self.repeats_sent,
            "aggregated": self.aggregated,
            "group_broadcasts": self.group_broadcasts,
            "transport_failures": self.transport_failures,
            "echo_warnings": self.echo_warnings,
            "by_command": dict(self.by_command),
        }
