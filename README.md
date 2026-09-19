# Patsiuk: the dog that checks drone-flagged metal

A drone survey flags every piece of metal in a field. Today a **person still has to
walk up to each flag** to find out whether it is a mine or a tin can.

Patsiuk does that step instead. It walks to each flagged spot, scans it at ground
level with two phones used as a gradiometer, fits a magnetic dipole to the readings,
and sorts it:

| Label | Meaning |
|---|---|
| `MINE_SIZED` | enough steel to be a mine or UXO. Send a human (EOD). |
| `FRAGMENT` | small steel object: scrap, low priority. |
| `NO_TARGET` | nothing ferrous above the noise. |
| `RESCAN` | something is there but the fit is poor. Never treated as safe. |
| `SKIPPED` | no safe path to the spot. Never treated as safe. |

The dog keeps one heading all run and never steps on a flagged spot (`plan_move`).

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
| **Patsiuk dipole fit** | **121/122 (99%)** | **1/44** |

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
- `sim.py` — fake world, phones and dog
- `flagged_spots.json` — the "drone survey" input (remove `sim_truth` for real runs)
- `unoq/` — optional Arduino UNO Q status display (App Lab app: `sketch/` + `python/`)

`pip install -r requirements.txt`

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
5. **Dog:** `dimos mcp list-tools` to confirm the move skill and its argument names,
   then test a +5 cm forward and a +5 cm left move for direction. Find the smallest
   move the dog does accurately and set `--step` to at least that.
   `python field_scan.py --low http://LOW:8080 --high http://HIGH:8080 [--skill ... --fwd-arg ... --left-arg ...]`

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
