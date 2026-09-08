# Migrating the Scout Hut from the YAML platform

This is the specific migration for the hut: seven `bf` blinds on one hub, five
of them on the hall group `040.001-15`, driven by Cover Control Automation (CCA)
and two wall buttons. It moves you from the old `cover:` platform in
`configuration.yaml` to the UI configured integration, keeping the entity ids so
nothing downstream breaks.

## What stays exactly as it is

- **CCA is not touched.** The `hvorragend/cover_control_automation.yaml`
  automations keep driving the blinds through normal cover services. This
  integration owns the hub, the covers and the buttons, not the schedule.
- **The `Hall Blinds` group cover** stays in `configuration.yaml`.
- **The reevaluate helpers** (`input_boolean.hall_blinds_reevaluate`,
  `input_boolean.office_blinds_reevaluate`) and the **full reset automation**
  stay. They are CCA's `force_pause`, nothing to do with the hub.
- **The `input_text.*_cover_status_helper` helpers** stay. They are CCA's.

## Why the entity ids need care

The old `cover:` platform registered `cover.hall_front_left` and friends. The
new config entry creates fresh entities with new unique ids, so Home Assistant
will not hand them the old ids automatically: it would park the new one at
`cover.hall_front_left_2` while the old, now dead, entity still holds the real
id. Everything downstream (CCA, the `Hall Blinds` group, the `customize` block,
the button covers) points at `cover.hall_front_left`, so the ids must be
preserved. The fix is to delete the old entities first, which frees the ids, so
the correctly named new entities claim them.

The integration helps by making each blind its own device with the cover as its
primary entity, so a blind named **Hall Front Left** yields exactly
`cover.hall_front_left`.

## Before you start

Do this at a quiet time. Have the hall accessible so you can watch the blinds.
Turn debug logging on so you can see what the hub does:

```yaml
logger:
  logs:
    custom_components.neosmartblinds: debug
```

## Step 1: Install the new version

Add this repository to HACS as a custom repository (category **Integration**),
download it, and restart Home Assistant. Do not add the integration from the UI
yet.

## Step 2: Remove the old platform blocks

In `configuration.yaml`, delete the seven `- platform: neosmartblinds` blocks
(Office, Kitchen, and the five Hall blinds). **Keep** the `- platform: group`
`Hall Blinds` block.

The `homeassistant: customize:` block that sets `supported_features: 15` is now
redundant, because the new entities advertise open, close, stop and set position
themselves. You can leave it (harmless) or remove it.

Restart Home Assistant. The seven old blinds go **unavailable**.

## Step 3: Free the old entity ids

Go to **Settings → Devices & Services → Entities**. Filter to the seven
unavailable `cover.*` blinds (Office, Kitchen, the five Hall). Select them and
**delete** them from the registry. This releases `cover.hall_front_left` and the
rest. Do not delete the `Hall Blinds` group.

## Step 4: Add the hub

**Settings → Devices & Services → Add Integration → NeoSmartBlinds.** Enter:

- Name: `Scout Hut Blinds` (or anything, it names the hub device only)
- Hub IP: your `neo_hub_host`
- Hub ID: your `neo_hub_id`
- Protocol: **TCP**, Port **8839**

## Step 5: Add the seven blinds

Open the integration's **Configure → Add a blind** and add each of these. The
name must match exactly so the entity id comes out right. Motor code is `bf` and
positioning mode is 0 for every blind.

| Name | Blind code | Close time | Group code |
| --- | --- | --- | --- |
| Office | 181.224-01 | 26 | (leave blank) |
| Kitchen | 178.136-01 | 29 | (leave blank) |
| Hall Front Left | 040.001-01 | 29 | 040.001-15 |
| Hall Front Right | 040.001-02 | 29 | 040.001-15 |
| Hall Right Front | 040.001-03 | 32 | 040.001-15 |
| Hall Right Middle | 040.001-04 | 32 | 040.001-15 |
| Hall Right Back | 040.001-05 | 32 | 040.001-15 |

Choose **Save changes** in the menu when done.

Close times are the measured values from your old config. Your CCA `drive_time`
was a few seconds longer (34, 37) as its own travel margin; leave CCA's
`drive_time` as it is. The integration uses its own close time for the favourite
guard.

## Step 6: Check the ids

In **Entities**, confirm the seven new covers are `cover.office`,
`cover.kitchen`, `cover.hall_front_left`, `cover.hall_front_right`,
`cover.hall_right_front`, `cover.hall_right_middle`, `cover.hall_right_back`. If
any came out with a `_2` suffix (an old entity was not deleted), delete the
stale one and rename the new entity's id in its settings.

**Office needs a look.** The old CCA "Office Blind Automation" targets
`cover.office_2`, but the blind here yields `cover.office`. Either point CCA's
`blind:` at `cover.office`, or if you truly need `cover.office_2`, rename the new
entity's id to match. Reconcile the two so they agree.

## Step 7: Add the two buttons

Open **Configure → Add a button control** and add both, then **Save changes**.
This replaces the two toggle automations.

| Name | Button event entity | Action | Blinds | Travel ceiling |
| --- | --- | --- | --- | --- |
| Hall Front | `event.hall_switch_button_1` | Toggle | `cover.hall_front_left`, `cover.hall_front_right` | 40 |
| Hall Side | `event.hall_switch_button_2` | Toggle | `cover.hall_right_front`, `cover.hall_right_middle`, `cover.hall_right_back` | 45 |

Set the **Press type** to match your button's `event_type` attribute. Your old
blueprint used `press`; confirm in **Developer Tools → States** on the event
entity (a Shelly BLU button reports `press`, `double_press` and so on; a Shelly
input reports `single_push`). Cooldown 10 is fine.

Because the hub serialises every command itself, there is no mutex and no gap.
Press both buttons together and both walls travel in parallel.

## Step 8: Retire the old button plumbing

Once the buttons work from the integration, delete:

- the two toggle automations (Hall Front Toggle, Hall Side Toggle),
- the `input_boolean.hall_blind_mutex` helper,
- the `dan/blind_button_toggle.yaml` blueprint.

## Step 9: Two CCA fixes

1. **Kitchen shading.** The Kitchen CCA has `shading_position: 60`. The blinds
   only reach 0, 50 (favourite) or 100, so 60 is rejected with a warning. Change
   it to **50** (favourite shade) or **0** (down only, the most robust).
2. **Ventilation.** The hall blinds have `auto_ventilate_enabled` on with
   `ventilate_position: 99`. These motors cannot part open, so a ventilate cycle
   drives them fully up (99 rounds to open). If that is not what you want, drop
   `auto_ventilate_enabled` from those blinds' `auto_options`.

## Step 10: Verify

1. Drive the whole hall closed from the group or a schedule. In the log you want
   one `040.001-15-dn!bf` group frame, not five individual ones.
2. Press the front button, then the side button, straight after. Both walls
   should move, the side one right behind the front, not a wall apart.
3. Recall a favourite on the Kitchen (or via `neosmartblinds.set_favourite`).
   You should see it wait, then a single `gp!bf`.
4. Download diagnostics from the hub device and check the recent commands read
   the way you expect.

If the blinds flap, set **End stop repeats** to 0 in the options and watch the
diagnostics. That is the open question the rewrite exists to answer.
