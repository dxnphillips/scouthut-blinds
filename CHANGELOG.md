# Changelog

All notable changes to NeoSmartBlinds (Scout Hut) are recorded here. This
project follows [semantic versioning](https://semver.org).

## 3.3.0

- **Fix missed favourite and shading commands.** 3.2.0 restored the long
  escalating schedule for open and close but left the favourite (`gp`) with only
  a single delayed repeat, down from the original fork's six. Shading drives the
  blinds to the favourite, and `gp` is the worst delivered command on these
  motors (a per wall shade cannot use the reliable channel 15 broadcast, so it
  unicasts and lands roughly one time in five), so shading missed far more often:
  two attempts land about 35 percent of the time against about 80 percent for
  seven. The escalating favourite repeat schedule is restored, `1, 1, 2, 4, 8, 8`
  multiples of a full travel by default (so every repeat lands on a stationary
  blind, which `gp` requires), and is now a configurable list (blank disables).
  Open and close are unchanged.

## 3.2.0

- **Flapping fix, and the repeats are kept long.** The RF loss is severe enough
  that it can take the whole escalating window for every blind to catch a frame
  and open, so the eight attempt, roughly seventeen minute schedule is restored
  as the default (now one configurable schedule field, blank to disable). The
  flap was never the schedule's length. A repeat keyed to a group code and one
  keyed to an individual code can both drive the same physical blind, because a
  channel 15 broadcast reaches every member, and the old cancellation could
  leave those two carrying opposite directions at once, so a blind got
  group-down, individual-up, group-down. Cancellation is now scope aware: a whole
  hall broadcast clears the old group tail and every member's individual tail
  (channel 15 becomes the single source of truth), while an individual command
  clears its own and the group tail and hands the group intent to the other
  members only. A blind can never hold two opposite tails, so the long repeats
  are safe. Full analysis in `docs/FLAPPING.md`.

## 3.1.0

- **Entity ids are preserved from the YAML platform.** Each blind is now its own
  device with the cover as its primary entity, so a blind named Hall Front Left
  yields `cover.hall_front_left`, the id the old platform produced and the id the
  CCA automations, the cover group and the button bindings reference. A migration
  guide for moving off the YAML platform without breaking those references is in
  `docs/MIGRATION.md`.
- **Button controls in the integration.** Map a physical button (an event
  entity) to toggle, open, close, stop or favourite on a group of blinds,
  configured in the options flow. This replaces the external group toggle
  blueprint and, with it, the whole reason that blueprint carried a shared hub
  mutex, a post send gap and a yield to the schedule automations: the hub
  already serialises every command, so two buttons pressed together drive their
  walls in parallel instead of one waiting out the other. Toggle uses the same
  converge rule as before, if any blind is open a press closes the group, and
  each binding debounces itself through the travel and a cooldown. The bindings
  and their last activity appear in the diagnostics dump.

## 3.0.0

First release as a UI configurable, HACS distributed integration. Replaces the
copy over the folder script fork with a config entry, and adds the logging and
diagnostics the script could not provide.

- **Config flow.** The hub and every blind are added and edited in the UI, no
  YAML. One config entry is one physical hub; blinds are managed from the
  options flow. The domain stays ``neosmartblinds`` so existing entity ids and
  the mental model carry over.
- **Diagnostics.** A downloadable, redacted snapshot of the hub: resolved
  tuning, live group membership, pending repeats, counters and the last fifty
  commands in order with kind, reason and result. Diagnostic sensors for the
  counters and last command, and a hub connectivity binary sensor.
- **Structured logging.** Every command, repeat, aggregation decision and
  transport failure is recorded and, with the log option on, logged at info.
- **End stop repeats.** up and down are re-sent on a schedule to beat the lossy
  RF, and the favourite gets one delayed repeat once the blind is stationary.
  Scheduled even when the TCP attempt fails, so a repeat doubles as the retry for
  a transient hub outage.
- **Per entry state.** The single connection lock, backoff clock, group
  aggregation and repeat scheduler moved off module globals onto a per entry hub
  object. This fixes by construction the reload leak where the group child
  counter never reset and group broadcast silently stopped firing.
- **Preserved behaviour.** The single hub connection, the command backoff, the
  group aggregation, the guarded favourite, the honest three state model and the
  ``gp`` only favourite are all carried over from the script fork unchanged.
- **Services.** ``neosmartblinds.set_favourite`` recalls the guarded favourite;
  ``neosmartblinds.send_command`` sends a raw motor command for troubleshooting.
