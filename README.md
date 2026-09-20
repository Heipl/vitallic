# Vitallic: the dog that checks drone-flagged metal

# SEE MASTER (NOT MAIN) FOR INTERACTIVE HTML FILES

A drone survey flags every piece of metal in a field. Today a **person still has to
walk up to each flag** to find out whether it is a mine or a tin can.

Vitallic does that step instead. It walks to each flagged spot, scans it at ground
level with two phones used as a gradiometer, fits a magnetic dipole to the readings,
and sorts it:

| Label | Meaning |
|---|---|
| `MINE_SIZED` | enough steel to be a mine or UXO. Send a human (EOD). |
| `FRAGMENT` | small steel object: scrap, low priority. |
| `NO_TARGET` | nothing ferrous above the noise. |
| `RESCAN` | something is there but the fit is poor. Never treated as safe. |
| `SKIPPED` | no safe path to the spot. Never treated as safe. |

The dog keeps one heading all run, and `plan_move` routes it so the body never crosses a
flagged spot.

> **This guarantee currently holds only in `--sim` and `--manual`.** On real hardware,
> dimOS's `move_to` hands the goal to a replanning A\* planner that chooses its own route,
> so it can cross a flagged spot regardless of what `plan_move` computed. See
> [DIMOS_PORT.md](DIMOS_PORT.md). The dog path is not yet validated on hardware.

## Why a fit beats a threshold

Peak signal confounds **size** with **depth**: a big object 20 cm down and a small one
3 cm down give the same peak reading. The fit uses the *width* of the anomaly and the
low/high phone ratio to get depth first, then converts strength into size.

`python benchmark.py` measures exactly that, on 300 randomised buried objects, through
the same fit and classify code the dog runs. The peak-threshold baseline is handed its
**best possible threshold, chosen in hindsight on the same data** — the comparison is
deliberately unfair in its favour:

| On the 122 objects above the detection floor | Correct | Scrap called a mine |
|---|---|---|
| Peak-signal threshold (what a metal detector gives you) | 93/122 (76%) | 15/44 |
| **Vitallic dipole fit** | **121/122 (99%)** | **1/44** |

Depth error on those objects: median 0.5 cm, RMS 1.6 cm.
`benchmark.png` shows why — on peak signal the two classes overlap completely; on
fitted moment they separate.

The 35 mines both methods miss are below the **sensor's** detection floor, not the
classifier's: at 300 trials neither method can see what the phones cannot reach.

## Honest scope (say it before judges ask)

- **Ferrous (steel) targets only**: UXO and steel-cased mines, not plastic mines.
- Detection reach at the 1.0 µT floor, measured by `benchmark.py`:

  | Object | Moment | Detectable to |
  |---|---|---|
  | large UXO | 0.120 A·m² | 23 cm |
  | steel pot / mine stand-in | 0.050 A·m² | 16 cm |
  | small mine body | 0.020 A·m² | 11 cm |
  | keys / bolt | 0.005 A·m² | 4.5 cm |

- If a phone's reading suddenly jumps several µT, the OS recalibrated its
  magnetometer. Rescan that spot.
- Positions are the dog's commanded moves, so accuracy depends on how precisely it
  steps.
- `NO_TARGET` means "nothing ferrous above the noise", **not** "safe to walk on".

## Files

- `field_scan.py` — main program (scan, fit, classify, map, status server on :8765)
- `dipole.py` — physics and fit. `python dipole.py` runs a self-test showing a big deep
  object and a small shallow one with the **same peak signal**, told apart by the fit.
- `benchmark.py` — the numbers above. `python benchmark.py --trials 60` for a quick check.
- `phones.py` — phyphox reader and live hand-test tool
- `robot.py` — dimOS mover (Go2) and manual mover (handheld rig)
- `dimos_vitallic/` — dimOS module + blueprint that adds the `precise_move` skill
- `sim.py` — fake world, phones and dog
- `flagged_spots.json` — the "drone survey" input (remove `sim_truth` for real runs)
- `geo.py` — arena metres → WGS-84 lat/lon, so finds land on a real map
- `bayes.py` — Beta-Binomial and Gamma-Poisson posteriors over contamination
- `live_map.html` — the live page `field_scan.py` serves on `:8765/`
- `DIMOS_PORT.md` — what was verified against the real dimOS install, and how the
  20 cm planner trap is bypassed. **Read before touching hardware.**
- `tools/min_move_test.py` — measures the smallest move your dog actually performs.

`pip install -r requirements.txt`

## Two builds

The project has a dog version and a no-dog version. They share all the physics —
the difference is only what carries the sensor.

| | WITH the dog | WITHOUT the dog |
|---|---|---|
| Platform | Unitree Go2 via dimOS | 4-wheel Arduino rover |
| Sensor | two phones (gradiometer) on a boom | search coil on A0/A5 |
| Firmware | `arduino/dog/status_display.ino` (status only — the dog needs no Arduino) | `arduino/no_dog/rover_firmware.ino` (motors, sonar, coil) |
| Schematic | `schematics/dog/architecture.svg`, `schematics/dog/mounting.svg` | `schematics/no_dog/architecture.svg`, `wiring_unoq.svg`, `wiring_uno_r3.png` |
| Positioning | dimOS pose / commanded steps | dead reckoning from timed moves |

Note the asymmetry: on the dog build the Arduino does **no sensing or driving** —
the phones are self-contained sensors and dimOS drives the robot, so the UNO Q is
an optional LED status display with nothing wired to it. On the rover build the
Arduino *is* the robot: it drives the motors, reads the sonars and pulses the coil.

There is a third path that needs neither: `field_scan.py --manual` runs the whole
pipeline with you carrying the two-phone rig over a taped grid.

## Live map

`field_scan.py` serves a live page while it scans:

```
http://localhost:8765/        map + posterior (Leaflet)
http://localhost:8765/api     JSON: results with lat/lon, plus the posterior
http://localhost:8765/state   plain text, for the UNO Q display
```

Every classified spot drops a pin at its **fitted** position (not the flagged one),
mine-sized finds raise an alert, and two posteriors update as the dog walks:
`P(mine | flagged spot)` and mines per hectare, each with a 95% credible interval.
A panel extrapolates the density to larger regions through the exact
Negative-Binomial posterior predictive.

Set the arena origin so the pins land in the right place:

```
python field_scan.py --sim --lat 42.3601 --lon -71.0942 --heading 0
```

`--heading` is the compass bearing of the arena's +x axis (0 = north, 90 = east).

**On the extrapolation:** scaling a surveyed room to a city assumes uniform
density, which is false. That assumption dominates the error, not the counting
statistics, and the API says so in the payload. Present it that way.

## Test order (do not skip steps)

1. `python dipole.py` then `python benchmark.py` — physics and numbers, no hardware.
2. `python field_scan.py --sim` — whole pipeline, no hardware.
3. **Hand test (10 min):** phyphox on both phones, open Magnetometer, menu, Allow
   remote access. Everything on ONE hotspot.
   `python phones.py http://LOW:8080 http://HIGH:8080`. Sweep over a steel pot and over
   keys. You need changes of several µT at 5–10 cm, and noise well under 0.5 µT.
   **If this step fails, nothing downstream works — find out now.**
4. **Handheld rig:** tape a grid on the floor, then
   `python field_scan.py --manual --low http://LOW:8080 --high http://HIGH:8080`
5. **Dog:** read [DIMOS_PORT.md](DIMOS_PORT.md) first — the dog path is **not yet proven on
   hardware**. Install the scan blueprint into the dimOS venv, then:

   ```
   VIRTUAL_ENV=/root/dimensional-applications/.venv uv pip install -e dimos_vitallic
   dimos run vitallic-dimos.scan --robot-ip <DOG_IP>
   dimos mcp list-tools | grep precise_move
   python tools/min_move_test.py --dimos /root/dimensional-applications/.venv/bin/dimos
   ```

   Only after a 5 cm step actually moves the dog:

   ```
   python field_scan.py --low http://LOW:8080 --high http://HIGH:8080 \
       --dimos /root/dimensional-applications/.venv/bin/dimos
   ```

   The default `--skill precise_move` is what makes the 5 cm cross possible. Do not
   pass `--skill move_to` unless `min_move_test.py --skill move_to` proved small
   planner steps really execute.

`field_scan.py` runs `mover.preflight()` before it touches anything, so a missing
`dimos` CLI, a sleeping dog or a wrong skill name fails immediately with a clear
message instead of halfway through a demo.

## Mounting (measure and pass these)

- Phones flat, screen up, top of phone pointing forward along the boom.
- `--h-low` / `--h-high`: height of each phone above the ground with the dog standing
  (default 0.05 / 0.35 m).
- `--boom`: horizontal distance from the dog's body centre to the phones (default
  0.65 m). Longer means less dog interference.
- Non-metal boom only (wood, PVC, cardboard). Keep keys and phones in pockets away
  from the rig.

## Calibrate the threshold (5 min)

Scan one mine stand-in (steel pot or tin) and one fragment (keys) with `--calibrate`.
Set `--threshold` to about `sqrt(moment_big * moment_small)`.
