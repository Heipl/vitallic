"""
min_move_test.py - measure the SMALLEST move the dog actually executes.

This is the one number the scan design depends on.

Default skill is precise_move (dimos run vitallic-dimos.scan). That bypasses the
planner, so a 5 cm step is *supposed* to work; this test is how you find out
whether it actually did.

Pass --skill move_to to measure the stock planner path. That path has a 0.20 m
arrival tolerance, so a commanded 5 cm step may report "Navigation goal reached"
WITHOUT THE DOG MOVING AT ALL.

    python tools/min_move_test.py                      # precise_move, real dog
    python tools/min_move_test.py --skill move_to      # stock planner
    python tools/min_move_test.py --dry-run            # print the commands only

Before running: clear ~2 m in front of the dog, have it standing, and know how to stop it.
Start dimOS first:   dimos run vitallic-dimos.scan --robot-ip <DOG_IP>
Check it is up:      dimos mcp status
                     dimos mcp list-tools | grep precise_move
"""
import argparse
import json
import subprocess
import sys

# Commanded distances (metres). 0.05 is the current --step in field_scan.py.
DEFAULT_STEPS = [0.05, 0.10, 0.15, 0.20, 0.30, 0.50]
PLANNER_SKILLS = frozenset({"move_to"})


def call_move(dimos, skill, dx, dy, timeout, dry_run):
    args = {"x": round(dx, 3), "y": round(dy, 3)}
    if skill in PLANNER_SKILLS:
        args["relative"] = True
    payload = json.dumps(args)
    cmd = [*dimos, "mcp", "call", skill, "--json-args", payload, "--timeout", str(timeout)]
    print(f"    $ {' '.join(cmd)}")
    if dry_run:
        return "(dry run)"
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30)
    except FileNotFoundError:
        sys.exit(f"`{dimos[0]}` not found. Pass --dimos with the full path to the dimos binary.")
    except subprocess.TimeoutExpired:
        return "(timed out)"
    return (r.stdout or r.stderr).strip()


def ask_float(prompt):
    while True:
        s = input(prompt).strip()
        if s.lower() in ("q", "quit", "abort"):
            sys.exit("aborted")
        try:
            return float(s)
        except ValueError:
            print("    enter a number in cm, or q to abort")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dimos", default="dimos",
                    help="dimos binary (e.g. /root/dimensional-applications/.venv/bin/dimos)")
    ap.add_argument("--skill", default="precise_move",
                    help="move skill: precise_move (default) or move_to")
    ap.add_argument("--steps", type=float, nargs="+", default=DEFAULT_STEPS,
                    help="commanded distances in metres")
    ap.add_argument("--axis", choices=["forward", "left"], default="forward")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default="min_move_results.json")
    a = ap.parse_args()

    dimos = a.dimos.split()
    print(__doc__)
    print(f"skill: {a.skill}   axis: {a.axis}   "
          f"commanded steps (cm): {[round(s*100) for s in a.steps]}")
    if not a.dry_run:
        input("\nClear the space, dog standing. Press Enter to start (Ctrl-C to abort) ")

    rows = []
    for step in a.steps:
        dx, dy = (step, 0.0) if a.axis == "forward" else (0.0, step)
        print(f"\n--- commanding {step*100:.0f} cm {a.axis} via {a.skill} ---")
        out = call_move(dimos, a.skill, dx, dy, a.timeout, a.dry_run)
        print(f"    dimos said: {out.splitlines()[0] if out else '(no output)'}")
        if a.dry_run:
            continue
        actual = ask_float("    measured movement in cm (0 if it did not move): ")
        rows.append({"commanded_cm": step * 100, "measured_cm": actual,
                     "moved": actual >= 1.0, "skill": a.skill, "dimos_output": out})
        if actual >= 1.0:
            print("    returning to start...")
            call_move(dimos, a.skill, -dx, -dy, a.timeout, a.dry_run)

    if a.dry_run or not rows:
        return

    json.dump(rows, open(a.out, "w"), indent=1)
    print("\n================ RESULT ================")
    print(f"  {'commanded':>10} {'measured':>10}  {'moved?':>7}  {'error':>8}")
    for r in rows:
        err = r["measured_cm"] - r["commanded_cm"]
        print(f"  {r['commanded_cm']:>8.0f}cm {r['measured_cm']:>8.1f}cm  "
              f"{'yes' if r['moved'] else 'NO':>7}  {err:>+7.1f}cm")

    moved = [r for r in rows if r["moved"]]
    if not moved:
        print("\n  The dog did not move at ANY commanded distance.")
        print("  Check the dog is actually connected (dimos mcp status) before concluding.")
        if a.skill == "precise_move":
            print("  If precise_move is missing from `dimos mcp list-tools`, you started")
            print("  the stock blueprint. Use: dimos run vitallic-dimos.scan --robot-ip <IP>")
    else:
        smallest = min(r["commanded_cm"] for r in moved)
        print(f"\n  Smallest step the dog actually executes: {smallest:.0f} cm")
        if smallest > 5:
            print("  -> field_scan.py's default --step 0.05 (5 cm) WILL NOT WORK.")
            print(f"  -> Either pass --step {smallest/100:.2f} (and re-check the fit still")
            print("     resolves the anomaly), or switch to a continuous traverse that")
            print("     stamps each magnetometer sample with the dog's pose from TF.")
        else:
            print("  -> the 5 cm cross scan is viable as designed.")
    print(f"\n  saved: {a.out}")


if __name__ == "__main__":
    main()
