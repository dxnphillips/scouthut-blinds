# NeoSmartBlinds (Scout Hut)

UI configurable Home Assistant integration for the NeoSmartBlinds controller at
the Pelsall Scout Hut. A config entry fork of mtgeekman's neosmartblinds
platform, keeping the hard won reliability behaviour for these ``bf`` motor
blinds while adding structured logging and a downloadable diagnostics dump so
the intermittent blind flapping can be diagnosed from evidence.

- No YAML. Add the hub and each blind through **Settings → Devices & Services**.
- Group aggregation, single hub connection, command backoff and the guarded
  favourite are all preserved from the original fork.
- Every command, repeat, aggregation decision and transport failure is counted
  and kept in a rolling log, surfaced through diagnostic sensors and the
  diagnostics download.
- The end stop repeat window is now short and tunable (or off), because a repeat
  fired minutes after a command was the most likely cause of the flapping.

After download, restart Home Assistant and add **NeoSmartBlinds** from
**Settings → Devices & Services**. See the README for setup and the flapping
notes.
