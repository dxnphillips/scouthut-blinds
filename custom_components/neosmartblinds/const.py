"""Constants for the NeoSmartBlinds integration.

This is a UI configured (config entry) fork of mtgeekman's neosmartblinds
platform, tuned for the seven ``bf`` motor blinds at the Pelsall Scout Hut and
packaged for HACS. It keeps the hard won reliability behaviour of the original
YAML fork (single hub connection, command backoff, group aggregation, the
guarded favourite and the idempotent end stop repeat) while adding structured
logging and a diagnostics dump so the intermittent blind flapping can actually
be seen and reasoned about.
"""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "neosmartblinds"

# Dispatcher signal, formatted with the config entry id, fired whenever the hub
# transmits, so the diagnostic sensors redraw without polling.
SIGNAL_UPDATE: Final = "neosmartblinds_update_{}"

PLATFORMS: Final[list[Platform]] = [
    Platform.COVER,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
]

# ---------------------------------------------------------------------------
# Configuration keys
#
# The per blind keys deliberately keep the same names the original YAML
# platform used (blind_code, close_time, rail, and so on), so an existing
# configuration reads across unchanged and the mental model does not move.
# ---------------------------------------------------------------------------

# Hub (config entry data)
CONF_HUB_ID: Final = "hub_id"
CONF_PROTOCOL: Final = "protocol"
# CONF_HOST, CONF_PORT and CONF_NAME come from homeassistant.const.

# Per blind (stored as a list under CONF_BLINDS in the entry options)
CONF_BLINDS: Final = "blinds"
CONF_BLIND_ID: Final = "id"
CONF_BLIND_CODE: Final = "blind_code"
CONF_CLOSE_TIME: Final = "close_time"
CONF_RAIL: Final = "rail"
CONF_PERCENT_SUPPORT: Final = "percent_support"
CONF_MOTOR_CODE: Final = "motor_code"
CONF_START_POSITION: Final = "start_position"
CONF_PARENT: Final = "parent_group"

# Global tuning (entry options)
CONF_COMMAND_BACKOFF: Final = "command_backoff"
CONF_AGGREGATION_PERIOD: Final = "aggregation_period"
CONF_IO_TIMEOUT: Final = "io_timeout"
CONF_REPEAT_COUNT: Final = "repeat_count"
CONF_REPEAT_SPACING: Final = "repeat_spacing"
CONF_REPEAT_STOP: Final = "repeat_stop"
CONF_FAV_REPEAT: Final = "favourite_repeat"
CONF_FAV_IDLE_GUARD: Final = "favourite_idle_guard"
CONF_FAV_SETTLE_TIMEOUT: Final = "favourite_settle_timeout"
CONF_LOG_COMMANDS: Final = "log_commands"

# Button controls (entry options)
#
# Each binding maps one press of a physical button (an event entity) to an
# action on a group of covers. This is the consolidation of the external
# "blind group toggle" button blueprint: because the hub already serialises
# every command through one connection with a backoff, the blueprint's whole
# collision avoidance section (a shared mutex, a post send gap, a yield to the
# schedule automations) is unnecessary here. Two buttons pressed together are
# simply queued through the hub lock and both walls travel in parallel.
CONF_BUTTONS: Final = "buttons"
CONF_BUTTON_ID: Final = "id"
CONF_EVENT_ENTITY: Final = "event_entity"
CONF_EVENT_TYPE: Final = "event_type"
CONF_BUTTON_ACTION: Final = "button_action"
CONF_COVERS: Final = "covers"
CONF_COOLDOWN: Final = "cooldown"
CONF_TRAVEL_CEILING: Final = "travel_ceiling"

ACTION_TOGGLE: Final = "toggle"
ACTION_OPEN: Final = "open"
ACTION_CLOSE: Final = "close"
ACTION_STOP: Final = "stop"
ACTION_FAVOURITE: Final = "favourite"
BUTTON_ACTIONS: Final = (
    ACTION_TOGGLE,
    ACTION_OPEN,
    ACTION_CLOSE,
    ACTION_STOP,
    ACTION_FAVOURITE,
)

DEFAULT_EVENT_TYPE: Final = "press"
# How long after a press before another press for the same button is accepted.
# Presses inside this window (and while the group is still travelling) are
# dropped, which is the debounce.
DEFAULT_COOLDOWN: Final = 10.0
# A ceiling on the travel wait, so a stuck blind cannot leave a button dead.
DEFAULT_TRAVEL_CEILING: Final = 45.0
# Position above which a blind counts as open for the toggle rule.
OPEN_THRESHOLD: Final = 50

PROTOCOL_HTTP: Final = "http"
PROTOCOL_TCP: Final = "tcp"

DEFAULT_HTTP_PORT: Final = 8838
DEFAULT_TCP_PORT: Final = 8839

# ---------------------------------------------------------------------------
# Positioning model
# ---------------------------------------------------------------------------
LEGACY_POSITIONING: Final = 0
EXPLICIT_POSITIONING: Final = 1
IMPLICIT_POSITIONING: Final = 2

ACTION_STOPPED: Final = 0
ACTION_OPENING: Final = 1
ACTION_CLOSING: Final = 2

# ---------------------------------------------------------------------------
# Protocol timing defaults
#
# These come from the vendor TCP protocol V1.8 and from testing on the hut
# hardware. Breaking them reintroduces the "missing commands" failures.
# ---------------------------------------------------------------------------
DEFAULT_IO_TIMEOUT: Final = 10.0

# Aggregation only fires when every blind in a group registers the same command
# inside this window. CCA runs one automation per blind and their commands
# arrive spread over a second or more, so a short window missed most whole hall
# commands and fanned them out into individual frames. Individual frames are the
# unreliable path on these motors; the channel 15 group broadcast is the
# reliable one. The cost is that every command waits up to this long before
# transmitting, and a partial group waits the whole window and then sends
# individually anyway.
DEFAULT_AGGREGATION_PERIOD: Final = 2.0

# The hub needs at least 500ms to verify, process and transmit each command.
# Never set the backoff below 0.5; 0.7 is the sensible margin.
DEFAULT_COMMAND_BACKOFF: Final = 0.7
MIN_COMMAND_BACKOFF: Final = 0.5

# ---------------------------------------------------------------------------
# Favourite (gp) guards
#
# bf motors ignore gp unless the blind has been stopped for about 3 seconds.
# The vendor app enforces roughly 3s; we match that so gp stops failing when
# fired straight after a move.
# ---------------------------------------------------------------------------
DEFAULT_FAV_IDLE_GUARD: Final = 3.0
# How long to wait for a moving blind to settle before sending gp. If it is
# still moving after this, we send anyway rather than hang forever.
DEFAULT_FAV_SETTLE_TIMEOUT: Final = 40.0
# Margin added on top of a full travel before the delayed favourite repeat, so
# the repeat always lands on a genuinely stationary motor.
FAV_REPEAT_MARGIN: Final = 2.0
DEFAULT_FAV_REPEAT: Final = True

# ---------------------------------------------------------------------------
# End stop repeat scheduler
#
# The RF hop from hub to motor is lossy and misses are frequent, but up/dn drive
# to a hard end stop, so re-sending them is idempotent and safe WHILE the blind
# is still travelling to that end stop.
#
# Flapping change (this fork): the earlier YAML fork spread eight repeats across
# roughly seventeen minutes on the theory that local interference arrives in
# bursts. That is the most likely cause of the blinds appearing to move on their
# own: these motors give no position feedback, so a repeat fired minutes after
# the original re-drives the blind to an end stop regardless of anything the
# user did with the physical remote or the vendor app in the meantime, and
# regardless of any command that arrived from a source this integration cannot
# see. A late idempotent re-send is only genuinely safe within the travel
# window. The default is therefore a small number of closely spaced repeats that
# stay inside a normal travel, and the whole thing is tunable (and can be turned
# off) from the options so it can be dialled in against the new diagnostics.
DEFAULT_REPEAT_COUNT: Final = 2
DEFAULT_REPEAT_SPACING: Final = 6.0
MAX_REPEAT_COUNT: Final = 10
# Stop is idempotent too (a stop to a stationary blind is a no op) but a stop
# rarely benefits from more than the original, and a repeated stop cannot help a
# blind that already stopped. Off by default; opt in if a lost stop is seen.
DEFAULT_REPEAT_STOP: Final = False

# How many recent command records the hub keeps for the diagnostics dump.
COMMAND_LOG_SIZE: Final = 200

# ---------------------------------------------------------------------------
# Motor command codes (vendor protocol)
# ---------------------------------------------------------------------------
CMD_UP: Final = "up"
CMD_DOWN: Final = "dn"
CMD_MICRO_UP: Final = "mu"
CMD_MICRO_DOWN: Final = "md"
CMD_STOP: Final = "sp"
CMD_FAV: Final = "gp"
CMD_FAV_1: Final = "i1"
CMD_FAV_2: Final = "i2"

# Not exposed through Home Assistant yet.
CMD_SET_FAV: Final = "pp"
CMD_REVERSE: Final = "rv"
CMD_CONFIRM: Final = "sc"
CMD_LIMIT: Final = "ld"

# Rail 2 (the top rail on top down / bottom up blinds).
CMD_UP2: Final = "u2"
CMD_DOWN2: Final = "d2"
CMD_MICRO_UP2: Final = "o2"
CMD_MICRO_DOWN2: Final = "c2"

# Rail 3 (both rails at once).
CMD_UP3: Final = "u3"
CMD_DOWN3: Final = "d3"

# Fully open / close a top down / bottom up blind.
CMD_TDBU_OPEN: Final = "op"
CMD_TDBU_CLOSE: Final = "cl"

# Commands that are safe to repeat. up/dn/up2/dn2 are idempotent drives to a
# hard end stop; sp is idempotent too but is only repeated when opted in.
REPEATABLE_DRIVES: Final = frozenset({CMD_UP, CMD_UP2, CMD_DOWN, CMD_DOWN2})
