"""Config and options flow for NeoSmartBlinds.

One config entry is one physical hub. The blinds on the hub, and the global
timing, repeat and logging options, are managed from the options flow so a blind
can be added, corrected or removed without touching YAML or restarting.
"""

from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    ACTION_CLOSE,
    ACTION_FAVOURITE,
    ACTION_OPEN,
    ACTION_STOP,
    ACTION_TOGGLE,
    CONF_AGGREGATION_PERIOD,
    CONF_BLIND_CODE,
    CONF_BLIND_ID,
    CONF_BLINDS,
    CONF_BUTTON_ACTION,
    CONF_BUTTON_ID,
    CONF_BUTTONS,
    CONF_CLOSE_TIME,
    CONF_COMMAND_BACKOFF,
    CONF_COOLDOWN,
    CONF_COVERS,
    CONF_EVENT_ENTITY,
    CONF_EVENT_TYPE,
    CONF_FAV_IDLE_GUARD,
    CONF_FAV_REPEAT,
    CONF_FAV_SETTLE_TIMEOUT,
    CONF_HUB_ID,
    CONF_IO_TIMEOUT,
    CONF_LOG_COMMANDS,
    CONF_MOTOR_CODE,
    CONF_PARENT,
    CONF_PERCENT_SUPPORT,
    CONF_PROTOCOL,
    CONF_RAIL,
    CONF_REPEAT_COUNT,
    CONF_REPEAT_SPACING,
    CONF_REPEAT_STOP,
    CONF_START_POSITION,
    CONF_TRAVEL_CEILING,
    DEFAULT_AGGREGATION_PERIOD,
    DEFAULT_COMMAND_BACKOFF,
    DEFAULT_COOLDOWN,
    DEFAULT_EVENT_TYPE,
    DEFAULT_FAV_IDLE_GUARD,
    DEFAULT_FAV_REPEAT,
    DEFAULT_FAV_SETTLE_TIMEOUT,
    DEFAULT_IO_TIMEOUT,
    DEFAULT_REPEAT_COUNT,
    DEFAULT_REPEAT_SPACING,
    DEFAULT_REPEAT_STOP,
    DEFAULT_TCP_PORT,
    DEFAULT_TRAVEL_CEILING,
    DOMAIN,
    LEGACY_POSITIONING,
    MAX_REPEAT_COUNT,
    PROTOCOL_HTTP,
    PROTOCOL_TCP,
)

_PROTOCOL_OPTIONS = [
    SelectOptionDict(value=PROTOCOL_TCP, label="TCP (port 8839, recommended)"),
    SelectOptionDict(value=PROTOCOL_HTTP, label="HTTP (port 8838)"),
]

_RAIL_OPTIONS = [
    SelectOptionDict(value="1", label="1 (single or bottom rail)"),
    SelectOptionDict(value="2", label="2 (top rail, top down / bottom up)"),
]

_PERCENT_OPTIONS = [
    SelectOptionDict(value="0", label="0 - open, closed or favourite only (bf motors)"),
    SelectOptionDict(value="1", label="1 - hub positions the blind by percent"),
    SelectOptionDict(value="2", label="2 - integration emulates position by timing"),
]


def _blind_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build the schema for adding or editing one blind."""
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "")): str,
            vol.Required(
                CONF_BLIND_CODE, default=defaults.get(CONF_BLIND_CODE, "")
            ): str,
            vol.Required(
                CONF_MOTOR_CODE, default=defaults.get(CONF_MOTOR_CODE, "bf")
            ): str,
            vol.Required(
                CONF_CLOSE_TIME, default=defaults.get(CONF_CLOSE_TIME, 20)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1, max=300, step=1, mode=NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_RAIL, default=str(defaults.get(CONF_RAIL, 1))
            ): SelectSelector(
                SelectSelectorConfig(
                    options=_RAIL_OPTIONS, mode=SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Required(
                CONF_PERCENT_SUPPORT,
                default=str(defaults.get(CONF_PERCENT_SUPPORT, LEGACY_POSITIONING)),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=_PERCENT_OPTIONS, mode=SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Optional(CONF_PARENT, default=defaults.get(CONF_PARENT, "")): str,
            vol.Optional(
                CONF_START_POSITION,
                description={"suggested_value": defaults.get(CONF_START_POSITION)},
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=100, step=1, mode=NumberSelectorMode.BOX
                )
            ),
        }
    )


def _normalise_blind(user_input: dict[str, Any], blind_id: str) -> dict[str, Any]:
    """Coerce a submitted blind form into the stored shape."""
    data: dict[str, Any] = {
        CONF_BLIND_ID: blind_id,
        CONF_NAME: user_input[CONF_NAME].strip(),
        CONF_BLIND_CODE: user_input[CONF_BLIND_CODE].strip(),
        CONF_MOTOR_CODE: user_input.get(CONF_MOTOR_CODE, "").strip(),
        CONF_CLOSE_TIME: int(user_input[CONF_CLOSE_TIME]),
        CONF_RAIL: int(user_input[CONF_RAIL]),
        CONF_PERCENT_SUPPORT: int(user_input[CONF_PERCENT_SUPPORT]),
        CONF_PARENT: user_input.get(CONF_PARENT, "").strip(),
    }
    start = user_input.get(CONF_START_POSITION)
    if start is not None:
        data[CONF_START_POSITION] = int(start)
    return data


_BUTTON_ACTION_OPTIONS = [
    SelectOptionDict(
        value=ACTION_TOGGLE, label="Toggle (close if any open, else open)"
    ),
    SelectOptionDict(value=ACTION_OPEN, label="Open"),
    SelectOptionDict(value=ACTION_CLOSE, label="Close"),
    SelectOptionDict(value=ACTION_STOP, label="Stop"),
    SelectOptionDict(value=ACTION_FAVOURITE, label="Favourite"),
]


def _button_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build the schema for adding or editing one button binding."""
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "")): str,
            vol.Required(
                CONF_EVENT_ENTITY,
                description={"suggested_value": defaults.get(CONF_EVENT_ENTITY)},
            ): EntitySelector(EntitySelectorConfig(domain="event")),
            vol.Required(
                CONF_EVENT_TYPE,
                default=defaults.get(CONF_EVENT_TYPE, DEFAULT_EVENT_TYPE),
            ): str,
            vol.Required(
                CONF_BUTTON_ACTION,
                default=defaults.get(CONF_BUTTON_ACTION, ACTION_TOGGLE),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=_BUTTON_ACTION_OPTIONS, mode=SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Required(
                CONF_COVERS,
                description={"suggested_value": defaults.get(CONF_COVERS, [])},
            ): EntitySelector(EntitySelectorConfig(domain="cover", multiple=True)),
            vol.Required(
                CONF_COOLDOWN, default=defaults.get(CONF_COOLDOWN, DEFAULT_COOLDOWN)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=120, step=1, mode=NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_TRAVEL_CEILING,
                default=defaults.get(CONF_TRAVEL_CEILING, DEFAULT_TRAVEL_CEILING),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=5, max=180, step=1, mode=NumberSelectorMode.BOX
                )
            ),
        }
    )


def _normalise_button(user_input: dict[str, Any], button_id: str) -> dict[str, Any]:
    """Coerce a submitted button form into the stored shape."""
    return {
        CONF_BUTTON_ID: button_id,
        CONF_NAME: user_input[CONF_NAME].strip(),
        CONF_EVENT_ENTITY: user_input[CONF_EVENT_ENTITY],
        CONF_EVENT_TYPE: user_input.get(CONF_EVENT_TYPE, "").strip(),
        CONF_BUTTON_ACTION: user_input[CONF_BUTTON_ACTION],
        CONF_COVERS: list(user_input.get(CONF_COVERS, [])),
        CONF_COOLDOWN: float(user_input[CONF_COOLDOWN]),
        CONF_TRAVEL_CEILING: float(user_input[CONF_TRAVEL_CEILING]),
    }


class NeoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial hub setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the hub connection details."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_HUB_ID])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={
                    CONF_HOST: user_input[CONF_HOST].strip(),
                    CONF_HUB_ID: user_input[CONF_HUB_ID].strip(),
                    CONF_PROTOCOL: user_input[CONF_PROTOCOL],
                    CONF_PORT: int(user_input[CONF_PORT]),
                },
                options={CONF_BLINDS: []},
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default="Scout Hut Blinds"): str,
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_HUB_ID): str,
                vol.Required(CONF_PROTOCOL, default=PROTOCOL_TCP): SelectSelector(
                    SelectSelectorConfig(
                        options=_PROTOCOL_OPTIONS, mode=SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Required(CONF_PORT, default=DEFAULT_TCP_PORT): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=65535, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> NeoOptionsFlow:
        """Return the options flow."""
        return NeoOptionsFlow()


class NeoOptionsFlow(OptionsFlow):
    """Manage the blind list and global tuning without a restart."""

    def __init__(self) -> None:
        """Initialise a lazy working copy of the options."""
        self._options: dict[str, Any] | None = None
        self._edit_id: str | None = None
        self._edit_button_id: str | None = None

    def _ensure(self) -> None:
        """Copy the stored options into a working buffer once."""
        if self._options is None:
            self._options = deepcopy(dict(self.config_entry.options))
            self._options.setdefault(CONF_BLINDS, [])
            self._options.setdefault(CONF_BUTTONS, [])

    @property
    def _blinds(self) -> list[dict[str, Any]]:
        assert self._options is not None
        return self._options[CONF_BLINDS]

    @property
    def _buttons(self) -> list[dict[str, Any]]:
        assert self._options is not None
        return self._options[CONF_BUTTONS]

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the top level menu."""
        self._ensure()
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "add_blind",
                "edit_select",
                "remove_blind",
                "add_button",
                "edit_button_select",
                "remove_button",
                "tuning",
                "save",
            ],
        )

    async def async_step_save(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Persist the working copy and close the flow."""
        self._ensure()
        return self.async_create_entry(data=self._options)

    async def async_step_add_blind(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a new blind."""
        self._ensure()
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_NAME].strip():
                errors[CONF_NAME] = "required"
            elif not user_input[CONF_BLIND_CODE].strip():
                errors[CONF_BLIND_CODE] = "required"
            else:
                self._blinds.append(_normalise_blind(user_input, uuid.uuid4().hex))
                return await self.async_step_init()
        return self.async_show_form(
            step_id="add_blind", data_schema=_blind_schema({}), errors=errors
        )

    async def async_step_edit_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a blind to edit."""
        self._ensure()
        if not self._blinds:
            return await self.async_step_init()
        if user_input is not None:
            self._edit_id = user_input[CONF_BLIND_ID]
            return await self.async_step_edit_blind()
        return self.async_show_form(
            step_id="edit_select", data_schema=self._select_schema()
        )

    async def async_step_edit_blind(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the chosen blind."""
        self._ensure()
        current = next(
            (b for b in self._blinds if b[CONF_BLIND_ID] == self._edit_id), None
        )
        if current is None:
            return await self.async_step_init()
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_NAME].strip():
                errors[CONF_NAME] = "required"
            elif not user_input[CONF_BLIND_CODE].strip():
                errors[CONF_BLIND_CODE] = "required"
            else:
                updated = _normalise_blind(user_input, current[CONF_BLIND_ID])
                self._options[CONF_BLINDS] = [
                    updated if b[CONF_BLIND_ID] == self._edit_id else b
                    for b in self._blinds
                ]
                self._edit_id = None
                return await self.async_step_init()
        return self.async_show_form(
            step_id="edit_blind",
            data_schema=_blind_schema(current),
            errors=errors,
            description_placeholders={"name": current[CONF_NAME]},
        )

    async def async_step_remove_blind(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove one or more blinds."""
        self._ensure()
        if not self._blinds:
            return await self.async_step_init()
        if user_input is not None:
            remove = set(user_input.get(CONF_BLIND_ID, []))
            self._options[CONF_BLINDS] = [
                b for b in self._blinds if b[CONF_BLIND_ID] not in remove
            ]
            return await self.async_step_init()
        return self.async_show_form(
            step_id="remove_blind", data_schema=self._select_schema(multiple=True)
        )

    async def async_step_add_button(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a new button binding."""
        self._ensure()
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_NAME].strip():
                errors[CONF_NAME] = "required"
            elif not user_input.get(CONF_COVERS):
                errors[CONF_COVERS] = "required"
            else:
                self._buttons.append(_normalise_button(user_input, uuid.uuid4().hex))
                return await self.async_step_init()
        return self.async_show_form(
            step_id="add_button", data_schema=_button_schema({}), errors=errors
        )

    async def async_step_edit_button_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a button binding to edit."""
        self._ensure()
        if not self._buttons:
            return await self.async_step_init()
        if user_input is not None:
            self._edit_button_id = user_input[CONF_BUTTON_ID]
            return await self.async_step_edit_button()
        return self.async_show_form(
            step_id="edit_button_select", data_schema=self._button_select_schema()
        )

    async def async_step_edit_button(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the chosen button binding."""
        self._ensure()
        current = next(
            (b for b in self._buttons if b[CONF_BUTTON_ID] == self._edit_button_id),
            None,
        )
        if current is None:
            return await self.async_step_init()
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_NAME].strip():
                errors[CONF_NAME] = "required"
            elif not user_input.get(CONF_COVERS):
                errors[CONF_COVERS] = "required"
            else:
                updated = _normalise_button(user_input, current[CONF_BUTTON_ID])
                self._options[CONF_BUTTONS] = [
                    updated if b[CONF_BUTTON_ID] == self._edit_button_id else b
                    for b in self._buttons
                ]
                self._edit_button_id = None
                return await self.async_step_init()
        return self.async_show_form(
            step_id="edit_button",
            data_schema=_button_schema(current),
            errors=errors,
            description_placeholders={"name": current[CONF_NAME]},
        )

    async def async_step_remove_button(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove one or more button bindings."""
        self._ensure()
        if not self._buttons:
            return await self.async_step_init()
        if user_input is not None:
            remove = set(user_input.get(CONF_BUTTON_ID, []))
            self._options[CONF_BUTTONS] = [
                b for b in self._buttons if b[CONF_BUTTON_ID] not in remove
            ]
            return await self.async_step_init()
        return self.async_show_form(
            step_id="remove_button",
            data_schema=self._button_select_schema(multiple=True),
        )

    async def async_step_tuning(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the global timing, repeat and logging options."""
        self._ensure()
        if user_input is not None:
            self._options.update(
                {
                    CONF_COMMAND_BACKOFF: float(user_input[CONF_COMMAND_BACKOFF]),
                    CONF_AGGREGATION_PERIOD: float(user_input[CONF_AGGREGATION_PERIOD]),
                    CONF_IO_TIMEOUT: float(user_input[CONF_IO_TIMEOUT]),
                    CONF_REPEAT_COUNT: int(user_input[CONF_REPEAT_COUNT]),
                    CONF_REPEAT_SPACING: float(user_input[CONF_REPEAT_SPACING]),
                    CONF_REPEAT_STOP: bool(user_input[CONF_REPEAT_STOP]),
                    CONF_FAV_REPEAT: bool(user_input[CONF_FAV_REPEAT]),
                    CONF_FAV_IDLE_GUARD: float(user_input[CONF_FAV_IDLE_GUARD]),
                    CONF_FAV_SETTLE_TIMEOUT: float(user_input[CONF_FAV_SETTLE_TIMEOUT]),
                    CONF_LOG_COMMANDS: bool(user_input[CONF_LOG_COMMANDS]),
                }
            )
            return await self.async_step_init()

        o = self._options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_REPEAT_COUNT,
                    default=o.get(CONF_REPEAT_COUNT, DEFAULT_REPEAT_COUNT),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=MAX_REPEAT_COUNT, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_REPEAT_SPACING,
                    default=o.get(CONF_REPEAT_SPACING, DEFAULT_REPEAT_SPACING),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.5, max=300, step=0.5, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_REPEAT_STOP,
                    default=o.get(CONF_REPEAT_STOP, DEFAULT_REPEAT_STOP),
                ): BooleanSelector(),
                vol.Required(
                    CONF_FAV_REPEAT,
                    default=o.get(CONF_FAV_REPEAT, DEFAULT_FAV_REPEAT),
                ): BooleanSelector(),
                vol.Required(
                    CONF_FAV_IDLE_GUARD,
                    default=o.get(CONF_FAV_IDLE_GUARD, DEFAULT_FAV_IDLE_GUARD),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=30, step=0.5, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_FAV_SETTLE_TIMEOUT,
                    default=o.get(CONF_FAV_SETTLE_TIMEOUT, DEFAULT_FAV_SETTLE_TIMEOUT),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=120, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_COMMAND_BACKOFF,
                    default=o.get(CONF_COMMAND_BACKOFF, DEFAULT_COMMAND_BACKOFF),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.5, max=5, step=0.1, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_AGGREGATION_PERIOD,
                    default=o.get(CONF_AGGREGATION_PERIOD, DEFAULT_AGGREGATION_PERIOD),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=10, step=0.5, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_IO_TIMEOUT,
                    default=o.get(CONF_IO_TIMEOUT, DEFAULT_IO_TIMEOUT),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=60, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_LOG_COMMANDS,
                    default=o.get(CONF_LOG_COMMANDS, True),
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="tuning", data_schema=schema)

    def _select_schema(self, multiple: bool = False) -> vol.Schema:
        """Return a select of the configured blinds, keyed by their stable id."""
        options = [
            SelectOptionDict(
                value=b[CONF_BLIND_ID],
                label=f"{b[CONF_NAME]} ({b[CONF_BLIND_CODE]})",
            )
            for b in self._blinds
        ]
        return vol.Schema(
            {
                vol.Required(CONF_BLIND_ID): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        multiple=multiple,
                        mode=SelectSelectorMode.LIST,
                    )
                )
            }
        )

    def _button_select_schema(self, multiple: bool = False) -> vol.Schema:
        """Return a select of the configured button bindings by their id."""
        options = [
            SelectOptionDict(
                value=b[CONF_BUTTON_ID],
                label=f"{b[CONF_NAME]} ({b.get(CONF_BUTTON_ACTION, ACTION_TOGGLE)})",
            )
            for b in self._buttons
        ]
        return vol.Schema(
            {
                vol.Required(CONF_BUTTON_ID): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        multiple=multiple,
                        mode=SelectSelectorMode.LIST,
                    )
                )
            }
        )
