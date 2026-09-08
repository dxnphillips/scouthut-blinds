# NeoSmartBlinds (Scout Hut)

A UI configurable, HACS distributed Home Assistant integration for the
NeoSmartBlinds controller at the Pelsall Scout Hut. It is a config entry fork of
[mtgeekman's neosmartblinds platform](https://github.com/mtgeekman/Home_Assistant_NeoSmartBlinds),
carrying over the hard won reliability behaviour for these ``bf`` motor blinds
and adding the two things the original could not give: structured logging and a
downloadable diagnostics dump.

## Why this exists

The blinds are open loop over lossy 433MHz RF. The hub echoes receipt of the
bytes it was sent, but nothing ever confirms the motor heard the RF, and the
motors report no position. Every earlier fix lived in a script that had to be
copied over the top of the folder by hand, with no version, no release and no
way to see what the hub had actually been doing.

This version is installed and updated through HACS by tagging a release, is
configured entirely in the UI, and records every frame it sends. When the blinds
flap, there is now evidence to look at rather than a guess to make.

## What it keeps from the original fork

- **One connection to the hub at a time.** The hub tolerates only one or a few
  simultaneous TCP connections; a single lock is held around the whole open,
  write, read, close cycle so only one ever exists.
- **A command backoff.** The hub needs at least 500ms to process each frame, so
  command starts are spaced (0.7s by default).
- **Group aggregation.** When every blind in a room registers the same command
  inside a short window, one channel 15 group broadcast is sent instead of one
  frame per blind. The broadcast is the reliable delivery path on these motors.
- **The guarded favourite.** ``bf`` motors ignore ``gp`` unless the blind has
  been stopped for about three seconds, so the favourite path waits for the
  blind to settle, waits out the worst case travel, then enforces the idle guard
  before sending ``gp``. Only ``gp`` is ever sent; the second favourite (``i2``)
  is a ``no`` motor command these motors drop.
- **The honest three state model.** ``bf`` motors can only reach a hard end stop
  (open or closed) or the single stored favourite. Position 0 closes, 100 opens,
  50 recalls the favourite, and any other position is rejected with a warning
  rather than silently dropped.

## What changed, and why (the flapping)

The single most likely cause of the blinds appearing to move on their own is the
**end stop repeat**. Because up and down drive to a hard end stop, the original
fork re-sent them several times to beat RF loss. That is safe only while the
blind is still travelling to that end stop. The earlier fork spread eight
repeats across roughly **seventeen minutes**, on the theory that local
interference arrives in bursts. The cost of that is exactly the flapping: these
motors have no feedback, so a repeat fired minutes later re-drives the blind to
an end stop regardless of anything done with the physical remote or the vendor
app in the meantime, and regardless of any command from a source Home Assistant
cannot see.

So in this version the repeat is **short and tunable**:

- Default: **2 repeats, 6 seconds apart** (both configurable), which keeps every
  repeat inside a normal travel.
- The repeat count can be set to **0 to switch repeats off entirely** while
  diagnosing.
- Stop is no longer repeated by default.
- The favourite still gets a single delayed repeat, and that can be turned off
  too.

None of this is a guess to leave in place. The new diagnostics show whether the
repeats are helping or hurting, and the numbers can then be dialled in from
evidence. Start with repeats off, watch the diagnostics, and only add repeats
back if genuine RF loss (not late re-drives) is visible.

## Installation

1. In HACS, add this repository as a **custom repository**, category
   **Integration**.
2. Download it, then restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration** and choose
   **NeoSmartBlinds**.

## Setup

**Add the hub.** Enter a name, the controller IP, the 24 character hub ID from
the NeoSmartBlinds app, the protocol and the port. **TCP on port 8839 is
recommended.** The HTTP path derives its deduplication hash from the microsecond
clock, which is weaker than the vendor recommends and can silently drop a frame
on a hash collision.

**Add your blinds** from the integration's **Configure** button. For each blind:

| Field | Notes |
| --- | --- |
| Name | The entity name in Home Assistant |
| Blind code | From the app, for example ``021.230-04`` |
| Motor code | Usually ``bf``. Must never be blank on these blinds |
| Close time | The real full travel, timed with a stopwatch. Never guess low |
| Rail | 1 for a single or bottom rail, 2 for a top down / bottom up top rail |
| Positioning mode | 0 for open / closed / favourite only (the ``bf`` default) |
| Group code | The room code (channel 15), for example ``021.230-15``, optional |
| Start position | Only used in a positioning mode |

Give the hall blinds the **same group code** so whole hall commands aggregate
into one broadcast.

## Options and tuning

The **Configure** dialog also has a **Command timing and repeats** page:

| Option | Default | Purpose |
| --- | --- | --- |
| End stop repeats | 2 | Re-sends of a drive after the original. 0 disables |
| Seconds between repeats | 6 | Spacing. Keep repeats inside one travel |
| Also repeat stop commands | off | Re-send stop as well |
| Send one delayed favourite repeat | on | One ``gp`` re-send after a full travel |
| Favourite idle guard | 3 | Seconds a blind must be stopped before ``gp`` |
| Favourite settle timeout | 40 | Seconds to wait for a moving blind before ``gp`` |
| Minimum seconds between commands | 0.7 | The backoff. Never below 0.5 |
| Group aggregation window | 2 | How long to collect a group command |
| Connection timeout | 10 | Per frame I/O timeout |
| Log every transmitted command | on | Info level Tx/Rx logging |

Changes apply on save without a restart.

## Diagnostics

This is the reason for the rewrite.

- **Download diagnostics** from the integration's device page for a redacted
  snapshot: the resolved tuning, the live group membership, the pending repeats,
  the counters and the **last 50 commands in order** with their kind (command,
  repeat, group, aggregated), reason and result.
- **Diagnostic sensors** on the hub device: commands sent, repeats sent, group
  broadcasts, aggregated commands, transport failures, echo warnings, a last
  command sensor with the full record in its attributes, and a hub connectivity
  binary sensor.
- **Debug logging**, for a live trace:

  ```yaml
  logger:
    logs:
      custom_components.neosmartblinds: debug
  ```

When a blind flaps, the last commands log shows whether a repeat, a group
broadcast or an ordinary command drove it, and when.

## Services

- **`neosmartblinds.set_favourite`** — send a blind to its stored favourite
  (``gp``) through the guarded path. Target a cover entity.
- **`neosmartblinds.send_command`** — send a raw motor command (``up``, ``dn``,
  ``sp``, ``gp``) straight to a blind, bypassing the position model. For
  troubleshooting only.

## Protocol constraints (do not violate these)

These come from the vendor TCP protocol V1.8 and from testing on the hut
hardware. Breaking them reintroduces the missing command failures.

- **One connection at a time.** Do not remove the connection lock.
- **500ms minimum between commands.** Never set the backoff below 0.5.
- **The echo is not delivery.** The hub echoes before it validates and transmits
  the RF, so a clean Tx/Rx pair confirms only that the hub received your bytes,
  never that the blind moved. The integration reads the echo only to log a
  warning on a mismatch.
- **Motor code must never be blank.** The frame format is a fixed width
  including the ``!bf`` suffix.
- **Close time must be at or above the real travel.** The delayed favourite
  repeat's safety rests on close time genuinely covering a full travel.
- **Stay on TCP (port 8839)** unless you have a reason not to.

## The favourite delivery limit

Empirically these motors receive the room code broadcast (channel 15) reliably
but individual blind code ``gp`` unicasts poorly. Forcing ``gp`` onto the
broadcast only works for an all blinds favourite, because channel 15 moves the
whole room. A per wall favourite can neither aggregate to the whole room nor
broadcast without moving blinds that should stay put, so per wall favourite
shading is not reliably achievable on an unsplittable room, and no software
change overcomes it.

Down only shading (drive to closed) is the most robust option, because down
drives to a hard end stop and survives individual unicasts far better than
``gp``. Keep ``gp`` where it is naturally a single idle blind. If the room is
ever split into separate group codes, per wall favourite shading becomes
reliable through each wall's own broadcast.

## Setting the favourite

This integration recalls the favourite but does not set it. Store it in the
NeoSmartBlinds app using **Set Favorite 1** on each blind; ``gp`` targets
favourite 1. Favourite 2 (``i2``) is unreachable on these motors.
