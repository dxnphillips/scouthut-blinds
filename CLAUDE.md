# CLAUDE.md

Context for Claude Code working on this repository.

## What this is

A Home Assistant custom integration, distributed via HACS, that controls the
NeoSmartBlinds blinds at the Pelsall Scout Hut. It is a config entry fork of
mtgeekman's neosmartblinds platform, tuned for the seven ``bf`` motor blinds and
packaged so it can be released and updated rather than copied over the folder.

The blinds are open loop over lossy 433MHz RF. The hub echoes the bytes it
received but never confirms the motor heard the RF, and the motors report no
position. Every command is therefore one way and unconfirmable. Hold that fact
in mind before changing anything: you cannot know where a blind actually is.

## Architecture

```
config entry (one hub)
    |
    v
hub.py: NeoHub          one connection lock, command backoff, group
    |                   aggregation, repeat scheduler, transport,
    |                   command log and counters
    |  BlindClient (one per blind)
    v
cover.py: NeoSmartBlindsCover   position model, honest three state gate,
                                guarded favourite
```

Everything that must be coordinated **across** blinds on one hub lives on
``NeoHub`` (one per config entry). Anything about a single blind's position and
state lives on its cover entity. Keep that boundary.

## Module map

| File | Responsibility |
| --- | --- |
| `const.py` | Domain, config keys, defaults, command codes, timing constants |
| `models.py` | `BlindConfig`, `CommandRecord`, `HubTuning`, `HubCounters` |
| `options.py` | Turn stored options into `HubTuning` and the blind list |
| `hub.py` | Connection lock, backoff, aggregation, repeats, transport, diagnostics |
| `config_flow.py` | Hub setup step, and the options flow that manages blinds and tuning |
| `cover.py` | Cover entities, positioning, three state gate, favourite, services |
| `entity.py` | Base diagnostic entity, dispatcher subscription |
| `sensor.py` / `binary_sensor.py` | Diagnostic sensors and hub connectivity |
| `diagnostics.py` | Redacted state and recent command dump |

## Design decisions, and why

Read these before changing behaviour. Each exists for a reason not obvious from
the code.

**The echo is not delivery.** The hub returns its echo before it validates and
transmits the RF, so a clean Tx/Rx pair confirms only that the hub received the
bytes. Never gate success on the echo. Repeats, not the echo, are the delivery
insurance. The echo is read only to log a mismatch warning.

**One connection at a time, and a 500ms floor.** The hub tolerates one or a few
TCP connections and needs at least 500ms per frame. The connection lock and the
backoff enforce this. Never remove the lock; never set the backoff below 0.5.

**End stop repeats must stay inside a travel.** up and down drive to a hard end
stop, so a re-send is idempotent **while the blind is still travelling**. Once
the blind is at rest, a repeat re-drives it, and because there is no feedback it
does this regardless of any manual, app or unseen command since. That late
re-drive is the prime suspect for the flapping. The repeat window is deliberately
short (two repeats, six seconds apart by default) and fully tunable, and can be
set to zero. Do not restore a minutes long escalating schedule without evidence
from the diagnostics that genuine RF loss (not late re-drives) needs it.

**The favourite is guarded.** ``bf`` motors ignore ``gp`` unless stopped for
about three seconds. The favourite path waits for settle, waits out the worst
case travel, then enforces the idle guard. It cancels pending repeats first so
no drive repeat can start a new travel while it waits. Only ``gp`` is sent;
``i2`` is a ``no`` motor command these motors drop.

**The honest three state gate.** ``bf`` motors reach only a hard end stop or the
single favourite. `SET_POSITION` is advertised (Home Assistant blocks the service
entirely without it, and some callers reach the favourite through position 50),
but the handler accepts only 0, 100 and 50/51 and rejects everything else with a
warning rather than dropping it silently. Do not re-add tilt: the original
upstream repurposed the tilt slider to fire favourites.

**Per entry state, not module globals.** The original fork kept the aggregation
counter, repeat registry, lock and backoff in module globals keyed by device
code. That leaked across reloads: the child counter never reset, so group
broadcast silently stopped firing. All of it is now on `NeoHub`, so a reload
starts clean. Do not move coordination state back to module scope.

**A new command supersedes pending repeats.** Before sending, a command cancels
pending repeats for the blind, its group, and (if it is a group broadcast) its
children, so a stop can never be chased by a stale repeat of the move it
stopped. When an individual command cancels a group tail, the tail is re-issued
to the group's other blinds rather than thrown away.

## Conventions

- British English in comments, docstrings and user facing strings.
- No hyphens or dashes in prose. Code identifiers are exempt.
- Ruff for lint and format. Run `ruff check` and `ruff format` before
  committing. Config is in `pyproject.toml` (line length 88, docstrings on).
- Type hints everywhere. `from __future__ import annotations` at the top.
- Home Assistant minimum 2024.12.0 (config entry `runtime_data`).

## Testing

Tests run offline, without Home Assistant installed. `tests/conftest.py` stubs
the small slice of the HA surface the tested modules import, so `pytest` runs on
plain Python 3.11+. Highest value first:

1. The repeat policy. `_repeat_delays` for each command under each tuning, and
   that a count of zero produces no repeats.
2. Cancellation. A new command cancels the right pending repeats, and a group
   tail is inherited by siblings.
3. Aggregation. The same command from every child broadcasts; a clash does not.
4. Options clamping. The backoff floor and repeat cap hold.

The cover's position model and config flow are exercised in Home Assistant, not
offline, because importing them pulls in the full HA cover and selector surface.

## Known unknowns

Check these against the live hut hardware. Do not assume the code is right.

- Whether the short repeat window actually beats the RF loss, or whether the
  flapping stops entirely with repeats off. This is the open question the whole
  rewrite exists to answer. Watch the diagnostics.
- Whether a group ``gp`` broadcast (channel 15) is honoured by these motors. It
  is inferred, not documented. Down only shading avoids relying on it.
- Whether any command source outside Home Assistant (the physical remote, the
  vendor app, a scene) is contributing to the flapping. The integration cannot
  see those, and a late repeat fighting one of them would look identical.
