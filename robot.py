"""
robot.py - move the sensor. The dog keeps ONE heading for the whole run
(facing +x) and only steps forward/back and sideways. That keeps the dog's own
magnetic field constant at the phones, so the fit's offsets cancel it.

Verified against dimos 0.0.14 (the real install in WSL), not guessed:
  - the CLI really is:  dimos mcp call <tool> --json-args '{...}'  (also -a key=value)
  - the Go2 move skill is `move_to`, NOT `relative_move` (which does not exist).
    dimos/robot/unitree/unitree_skill_container.py:
        move_to(x=0.0, y=0.0, degrees=None, relative=False)
    With relative=True, x is forward and y is left in metres - exactly this file's frame.
  - `observe` exists (dimos/agents/skills/observe_skill.py) and returns an IMAGE.
  - the blueprint that exposes both:  dimos run unitree-go2-agentic --robot-ip <DOG_IP>

THE 20 cm TRAP - read this before changing --step.
dimOS plans every move with a replanning A* planner whose arrival test is
(dimos/navigation/replanning_a_star/global_planner.py):
        _goal_tolerance: float = 0.2        # metres
    if distance(goal, odom) < 0.2 and |angle_diff| < 15deg:
        "Close enough to goal. Accepting as arrived."
Both Go2 controller blueprints set "goal_tolerance": 0.20 explicitly. So a commanded
move shorter than 20 cm reports SUCCESS WITHOUT THE DOG MOVING. If that were allowed
through, every scan point would be measured at the same place, the dipole design
matrix would go degenerate, and the run would print confident nonsense.
So `move()` refuses a sub-tolerance leg instead. Measure the real limit on your dog
with `python tools/min_move_test.py` before trusting any step size.

A second consequence, not fixed here: move_to hands the goal to a REPLANNING planner
that picks its own route, so field_scan.py's plan_move() can no longer promise the dog
misses every flagged spot. Treat that guarantee as void until the mover drives the
body directly rather than through the planner.
"""
import math
import subprocess
import time


class DimosMover:
    """Moves a Unitree Go2 through dimOS MCP skills via the `dimos` CLI."""

    # dimOS global_planner._goal_tolerance; see the module docstring.
    GOAL_TOLERANCE_M = 0.20

    def __init__(self, skill="move_to", observe_skill="observe", settle=0.8,
                 min_move=0.01, dimos="dimos", timeout=90, allow_small_moves=False):
        self.skill, self.observe_skill = skill, observe_skill
        self.settle, self.min_move = settle, min_move
        self.dimos = dimos.split() if isinstance(dimos, str) else list(dimos)
        self.timeout, self.allow_small_moves = timeout, allow_small_moves

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
                "Start the right blueprint (dimos run unitree-go2-agentic "
                "--robot-ip <DOG_IP>) or pass --skill.")
        if self.observe_skill not in out:
            print(f"  note: no '{self.observe_skill}' skill - photos at finds will be skipped")

    def move(self, dx, dy, target=None):
        """Relative move of the dog body in metres (x forward, y left).

        One `move_to` call carries both axes. Refuses a leg shorter than the planner's
        arrival tolerance, because dimOS would report success without moving.
        """
        dist = math.hypot(dx, dy)
        if dist < self.min_move:
            return
        if dist < self.GOAL_TOLERANCE_M and not self.allow_small_moves:
            raise RuntimeError(
                f"leg of {dist * 100:.1f} cm is below dimOS's "
                f"{self.GOAL_TOLERANCE_M * 100:.0f} cm arrival tolerance - the planner "
                "would report 'goal reached' without the dog moving, and every scan point "
                "would be measured from the same spot.\n"
                "Measure your dog's real minimum with `python tools/min_move_test.py`, then "
                "either raise --step above it or switch to a continuous traverse. Use "
                "--allow-small-moves only if that test proved small moves really work.")
        payload = '{"x": %.3f, "y": %.3f, "relative": true}' % (dx, dy)
        self._run([self.skill, "--json-args", payload, "--timeout", str(self.timeout)],
                  timeout=self.timeout + 30)
        time.sleep(self.settle)  # let the body stop swaying before we measure

    def observe(self):
        try:
            return self._run([self.observe_skill, "--timeout", "90"], timeout=120)
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
