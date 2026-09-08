# Changelog

All notable changes to NeoSmartBlinds (Scout Hut) are recorded here. This
project follows [semantic versioning](https://semver.org).

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
- **Flapping change: the end stop repeat is short and tunable.** The earlier
  fork spread eight drive repeats across roughly seventeen minutes. Because
  these motors give no feedback, a repeat fired minutes after a command
  re-drives the blind to an end stop regardless of anything that happened since,
  which is the most likely cause of the blinds flapping. Repeats now default to
  two, six seconds apart, stay inside a single travel, are fully configurable,
  and can be switched off entirely. Stop is no longer repeated by default.
- **Per entry state.** The single connection lock, backoff clock, group
  aggregation and repeat scheduler moved off module globals onto a per entry hub
  object. This fixes by construction the reload leak where the group child
  counter never reset and group broadcast silently stopped firing.
- **Preserved behaviour.** The single hub connection, the command backoff, the
  group aggregation, the guarded favourite, the honest three state model and the
  ``gp`` only favourite are all carried over from the script fork unchanged.
- **Services.** ``neosmartblinds.set_favourite`` recalls the guarded favourite;
  ``neosmartblinds.send_command`` sends a raw motor command for troubleshooting.
