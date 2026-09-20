"""
robot.py - move the sensor. The dog keeps ONE heading for the whole run
(facing +x) and only steps forward/back and sideways. That keeps the dog's own
magnetic field constant at the phones, so the fit's offsets cancel it.

Verified against dimos 0.0.14 (the real install in WSL), not guessed:
  - the CLI really is:  dimos mcp call <tool> --json-args '{...}'  (also -a key=value)
  - stock Go2 move skill is `move_to` (relative=True: x forward, y left, metres).
  - `move_to` always goes through the A* planner, whose 0.20 m arrival tolerance
    silently accepts a 5 cm step without the dog moving. See DIMOS_PORT.md.
  - the scan therefore defaults to `precise_move`, a skill from dimos_patsiuk that
    publishes tele_cmd_vel in-process (the 0.2 s deadman timer rules out CLI
    velocity). Start that blueprint:  dimos run patsiuk-dimos.scan --robot-ip <IP>
  - `observe` exists but returns an IMAGE, not text.

If you pass --skill move_to, `move()` still refuses legs shorter than 0.20 m
unless --allow-small-moves. precise_move does not have that trap, so the 5 cm
cross is allowed. Measure it anyway with tools/min_move_test.py.
"""
import json
import math
import subprocess
import time


class DimosMover:
    """Moves a Unitree Go2 through dimOS MCP skills via the `dimos` CLI."""

    # dimOS global_planner._goal_tolerance. Only applies to planner skills.
    GOAL_TOLERANCE_M = 0.20
    PLANNER_SKILLS = frozenset({"move_to"})

    def __init__(self, skill="precise_move", observe_skill="observe", settle=0.8,
                 min_move=0.01, dimos="dimos", timeout=90, allow_small_moves=False):
        self.skill, self.observe_skill = skill, observe_skill
        self.settle, self.min_move = settle, min_move
        self.dimos = dimos.split() if isinstance(dimos, str) else list(dimos)
        self.timeout, self.allow_small_moves = timeout, allow_small_moves

    def uses_planner(self):
        return self.skill in self.PLANNER_SKILLS

    def _run(self, args, timeout):
        cmd = [*self.dimos, "mcp", *args]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            raise RuntimeError(
                f"`{self.dimos[0]}` is not on PATH. Pass --dimos with the full path "
                "(e.g. /root/dimensional-applications/.venv/bin/dimos), or run with "
                "--manual (handheld rig) or --sim (no hardware).") from None
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"`{' '.join(cmd)}` timed out after {timeout}s - is the dog powered on "
                "and is dimOS still running?") from None
        if r.returncode != 0:
            detail = r.stderr.strip() or r.stdout.strip()
            raise RuntimeError(f"`{' '.join(cmd)}` failed:\n{detail}")
        return r.stdout.strip()

    def preflight(self):
        """Fail loudly NOW rather than halfway through a demo. Confirms the CLI is
        installed, dimOS is running, and the move skill actually exists."""
        out = self._run(["list-tools"], timeout=30)
        if self.skill not in out:
            raise RuntimeError(
                f"dimOS does not expose a skill called '{self.skill}'.\n"
                f"Skills it does expose:\n{out}\n"
                "Start the right blueprint (`dimos run patsiuk-dimos.scan "
                "--robot-ip <DOG_IP>`) or pass --skill.")
        if self.observe_skill not in out:
            print(f"  note: no '{self.observe_skill}' skill - photos at finds will be skipped")

    def move(self, dx, dy, target=None):
        """Relative move of the dog body in metres (x forward, y left).

        precise_move already treats x/y as body-relative. move_to needs relative=True
        to get the same frame. Planner skills refuse a sub-tolerance leg because
        dimOS would report success without moving.
        """
        dist = math.hypot(dx, dy)
        if dist < self.min_move:
            return
        if (self.uses_planner() and dist < self.GOAL_TOLERANCE_M
                and not self.allow_small_moves):
            raise RuntimeError(
                f"leg of {dist * 100:.1f} cm is below dimOS's "
                f"{self.GOAL_TOLERANCE_M * 100:.0f} cm arrival tolerance - the planner "
                "would report 'goal reached' without the dog moving, and every scan point "
                "would be measured from the same spot.\n"
                "Default is --skill precise_move (dimos run patsiuk-dimos.scan), which "
                "does not have this trap. If you insist on move_to, measure the real "
                "minimum with `python tools/min_move_test.py --skill move_to` and either "
                "raise --step above it or pass --allow-small-moves.")
        args = {"x": round(dx, 3), "y": round(dy, 3)}
        if self.uses_planner():
            args["relative"] = True
        payload = json.dumps(args)
        self._run(["call", self.skill, "--json-args", payload, "--timeout", str(self.timeout)],
                  timeout=self.timeout + 30)
        time.sleep(self.settle)  # let the body stop swaying before we measure

    def observe(self):
        try:
            return self._run(["call", self.observe_skill, "--timeout", "90"], timeout=120)
        except Exception as e:
            return f"(observe unavailable: {e})"


class ManualMover:
    """Handheld mode: carry the two-phone rig over a tape grid on the floor.
    Lets you test the whole pipeline without dog time."""

    def preflight(self):
        pass

    def move(self, dx, dy, target=None):
        where = f" to x={target[0]*100:.0f} cm, y={target[1]*100:.0f} cm" if target is not None else \
                f" by forward {dx*100:+.0f} cm, left {dy*100:+.0f} cm"
        input(f"  put the phones{where} (keep the same heading), then Enter ")

    def observe(self):
        return ""
