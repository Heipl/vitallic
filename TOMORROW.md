# Tomorrow: what still has to be true

Connecting the dog to Dimensional's wifi removes the blocker you spent tonight on.
It does not make the scan work. Behind it sit five things, none of which has ever
run on hardware. This is the order to test them in, cheapest and most-blocking
first, with what to do when each fails.

## Do tonight, while you still have internet

Both of these need a working internet connection, and the venue may not give you
one at the wrong moment.

```bash
uv pip install "dimos[unitree]"   # or pip; fixes ModuleNotFoundError: unitree_webrtc_connect
dimos login                        # dimos whoami was reporting not logged in
python dimos_vitallic/check_install.py
```

Without the first, `dimos run` fails on a perfectly reachable dog. This is the
single most annoying way to lose twenty minutes tomorrow.

## 1. Phones (10 min, no robot, no network)

**This is the critical path and it has never been run.** Every number in the
pitch - 99% vs 76%, the depth-reach table, the whole "a fit beats a threshold"
claim - rests on a measurement nobody has taken.

```bash
python phones.py http://LOW_PHONE:8080 http://HIGH_PHONE:8080
```

Sweep over a steel pot, then over keys. You need **several µT of change at
5-10 cm** and **noise well under 0.5 µT**.

- Works → everything downstream is worth doing.
- Fails → stop and fix this. No robot work matters. Try: phones further from the
  dog and from each other, a different phone, and check neither is in a case with
  a magnet.

## 2. Same-network reachability (5 min)

Being "on the same wifi" is not the same as being able to reach each other.
Corporate and venue networks often run **client isolation**, which blocks
device-to-device traffic and breaks dimOS silently.

```bash
dimos go2tool discover --lan -t 20
ping <dog-ip>
```

- Ping works → good.
- Discovered but no ping, or no discovery → client isolation. Fall back to the
  phone hotspot (2.4 GHz) with the laptop USB-tethered to the same phone, which
  is the arrangement in DIMOS_PORT.md. Do not fight the venue network.

## 3. Telemetry actually flowing (5 min)

A blueprint that starts cleanly is **not** a connected dog. This is what caught
you tonight.

```bash
dimos run vitallic-dimos.scan --robot-ip <IP>
dimos mcp list-tools      # expect precise_move, blind_move, move_to, observe
dimos spy                 # topics must be TICKING with live data
```

If `spy` is empty, the dog is not connected and nothing below will work.

## 4. Two things to settle inside `dimos spy`

**a. The `tele_cmd_vel` topic name is a guess.** `precise_move` and `blind_move`
publish velocity there to bypass the planner's 20 cm arrival tolerance. If the
live name differs they publish into the void and the dog never moves - and it
will look exactly like the dog ignoring you.

```bash
VITALLIC_CMD_VEL_TOPIC=<real name> dimos run vitallic-dimos.scan --robot-ip <IP>
```

**b. Does pose arrive, and how fast?** `precise_move` closes its loop on
`tfbuffer.get("world", "base_link")`. On a Go2 **Air**, WebRTC is limited to
topics and state comes only through low-frequency `rt/lf/lowstate`; CycloneDDS
works out of the box on EDU only. Look for TF/odometry and note the rate.

- Pose present and reasonably fast → use `precise_move`.
- Pose absent or very slow → use `blind_move` (open loop, reads nothing back)
  and accept that scan positions become dead reckoning.

## 5. Does a 5 cm step actually move the dog (15 min)

The number the whole scan design hangs on.

```bash
python tools/min_move_test.py --skill precise_move --dimos $(which dimos)
```

Clear ~2 m, dog standing, tape measure, hand on the stop.

- 5 cm moves reliably → run the real scan.
- 5 cm does nothing → try `--skill blind_move`, then calibrate
  `blind_speed_scale`: command 1.00 m, measure what it walked, set
  `blind_speed_scale = measured / commanded`.
- Neither works → stop. Go to the fallback below. Do **not** raise `--step` above
  20 cm to please the planner: at 20 cm the fit is statistically tied with a
  plain peak-signal detector, and at 30 cm it is worse and calls every piece of
  scrap a mine. A bigger step is not a workaround, it deletes the project's
  entire result.

## 6. The real scan

```bash
python field_scan.py --low http://LOW:8080 --high http://HIGH:8080 \
    --dimos $(which dimos) --skill precise_move
```

## The fallback, which is not a consolation prize

If any of 3-5 fails, you still have a complete, working demo:

```bash
python field_scan.py --manual --low http://LOW:8080 --high http://HIGH:8080
```

Tape a grid, carry the two-phone rig by hand, and the entire pipeline runs -
scan, dipole fit, classification, map. For the visual, **drive the dog with its
physical remote** along the same line with the phones on the boom. Judges see a
robot dog sweeping for mines; the data comes from the phones; dimOS is not in the
loop at all.

This is worth saying plainly: the dog is the spectacle, not the project. The
project is the physics - that a dipole fit separates a mine from scrap where a
peak-signal threshold cannot. That result is already measured, reproducible and
defensible, and it does not need a robot to be true.

## Honest odds

- Phones work: unknown, untested, and the only thing that can kill the project.
- Network + telemetry: likely, especially if other teams have it working in the
  building.
- `tele_cmd_vel` correct first try: maybe half. Easy to fix once seen in `spy`.
- Pose usable on an Air: genuinely uncertain. `blind_move` exists for this.
- 5 cm step working: uncertain until measured.

Budget the morning for 1-5 in that order and keep the manual demo as the thing
you know you can show.
