# The flapping: analysis and fix

This records why the hall blinds were seen making phantom movements and repeated
moves that alternated direction, what in the code caused it, and how it is
fixed. It is here so the reasoning is not lost, because the obvious fix (shorten
or remove the repeats) is the wrong one.

## The constraint that rules everything out

These blinds are open loop over lossy 433MHz RF. The hub echoes the bytes it
received but never confirms the motor heard the RF, and the motors report no
position. Every command is one way and unconfirmable. On the hut hardware the
loss is severe: it can take the whole escalating repeat window (about seventeen
minutes) for every blind in the hall to catch a frame and open. So the repeats
are essential. Any explanation of the flapping that ends in "so shorten the
repeats" is wrong, because that breaks opening.

## Two symptoms, two mechanisms

### Phantom single movements

A blind moves with nobody at the panel. The dominant cause is a repeat firing
minutes after the interaction the person thought was over, re-driving the blind
to an end stop. With no feedback, the integration re-sends on faith. Most of
these "phantoms" were actually the opposite-direction mechanism below seen in
isolation. The genuine remainder (an external remote or app moved the blind and
a later repeat dragged it back) cannot be fixed in software without feedback,
and is the accepted cost of repeats reliable enough to open the hall.

### Repeated moves alternating direction (the flap)

This is the sharp one. The repeat scheduler holds at most one pending tail per
**device string**. The catch is that a **group** code and an **individual** code
are different strings that drive the **same physical blind**:

- the hall group `040.001-15` broadcasts on channel 15 to all five blinds,
- the individual code `040.001-01` drives only blind 1.

So a tail keyed to `040.001-15` and a tail keyed to `040.001-01` can both be
pending at once, and both actuate blind 1. If they carry opposite commands,
blind 1 receives group-down, individual-up, group-down, alternating every few
seconds until one tail ends. That is the flap.

The old code actively created the opposite second tail. When a command
superseded a **group** tail, instead of just cancelling it, it re-issued the
group's remaining attempts to every **other** member as individual tails. That
was meant to preserve the siblings' delivery insurance. But the supersession ran
before the code knew whether the new command was itself a group broadcast, so a
fresh whole hall command of one direction would re-arm the **old, opposite**
group intent on the siblings as individual tails, right as it scheduled its own
group tail of the new direction. Both then drove those blinds, opposite ways.

A concrete sequence that flapped blinds 2 to 5:

1. Whole hall driven **up**. Group `…-15` up-tail scheduled.
2. Within the window, the hall is driven **down** (a shade, a button, or CCA
   re-evaluating). The broadcast first cancelled the `…-15` up-tail and re-issued
   "up" to blinds 2 to 5 as individual tails, then sent `…-15 dn` and scheduled a
   `…-15` down-tail.
3. Now pending together: a `…-15` **down** tail (channel 15, all blinds) and
   `…-02..05` **up** tails. Those blinds got down, up, down, up.

The seventeen minute window did not cause this; it widened it, by making it
likely that two whole hall commands of opposite direction fall inside one window.
The **full reset automation** and the **CCA re-evaluate pulse** do exactly that:
they make all five CCA instances re-run within seconds, and in a mixed state they
emit mixed directions in a burst.

## The fix

Keep the long schedule. Make cancellation **scope aware**, and do it after the
aggregation decision so it knows the scope:

- A whole hall **broadcast** (`_supersede_group` in `hub.py`) cancels the old
  group tail **and every member's individual tail**, and inherits nothing. The
  new channel 15 tail is then the single source of truth, one direction, for the
  whole room.
- An **individual** command (`supersede_individual`) cancels its own tail and the
  group tail (channel 15 would fight the blind just commanded), and hands the
  group's remaining intent to the **other** members only.

The invariant this guarantees: no physical blind is ever left with two pending
tails. A group tail and an individual tail can no longer coexist for one blind,
so they can never drive it opposite ways. The long, essential repeats become
safe. `tests/test_repeats.py::test_group_broadcast_clears_every_member_tail`
guards it.

## What the fix does not touch

- **Sources Home Assistant cannot see.** The physical remote, the vendor app, a
  scene. A repeat fighting one of those looks identical to a self inflicted flap
  and cannot be prevented without position feedback.
- **CCA issuing opposite commands in a burst.** That is CCA's logic and lives in
  the Cover Control Automation blueprint, not the hub. The reset and re-evaluate
  behaviour is tunable there.
- **Whether channel 15 group frames are honoured** by these motors at all. It is
  inferred from the vendor protocol, not proven. Down only shading avoids relying
  on a group `gp`.

## Confirming it from the diagnostics

Every frame the hub sends is recorded with its kind (`command`, `repeat`,
`group`, `aggregated`), device, reason and time, in the diagnostics download and
the recent commands log. When a blind moves unexpectedly, read that log:

- A `repeat` on `…-15` and a `repeat` on `…-0X` firing opposite directions
  seconds apart would be the old flap. With the fix in place this cannot happen;
  seeing it would mean a regression.
- A single `repeat` long after the last `command`, with no opposing frame, is a
  late re-drive; if the blind had been moved externally in between, that is the
  unavoidable phantom.
- No `neosmartblinds` frame at all around the movement points at an external
  source (remote, app, scene) or CCA driving through a different path.
