"""
robot.py - move the sensor. The dog keeps ONE heading for the whole run
(facing +x) and only steps forward/back and sideways. That keeps the dog's own
magnetic field constant at the phones, so the fit's offsets cancel it.

Before the first run:  dimos mcp list-tools
and check the move skill name and argument names; pass them with
--skill / --fwd-arg / --left-arg if they differ from the defaults.
Test signs with a tiny move first: +forward must go forward, +left must go left.
"""
import subprocess
import time


class DimosMover:
    """Moves a Unitree Go2 through dimOS MCP skills via the `dimos` CLI."""

    def __init__(self, skill="relative_move", fwd_arg="forward", left_arg="left",
                 observe_skill="observe", settle=0.8, min_move=0.01):
        self.skill, self.fwd_arg, self.left_arg = skill, fwd_arg, left_arg
        self.observe_skill, self.settle, self.min_move = observe_skill, settle, min_move

    def _call(self, *parts, timeout=60):
        cmd = ["dimos", "mcp", "call", *parts]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            raise RuntimeError("the `dimos` CLI is not on PATH. Install dimOS, or run with "
                               "--manual (handheld rig) or --sim (no hardware).") from None
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"`{' '.join(cmd)}` timed out after {timeout}s - is the dog "
                               "powered on and on this hotspot?") from None
        if r.returncode != 0:
            raise RuntimeError(f"`{' '.join(cmd)}` failed:\n{r.stderr.strip() or r.stdout.strip()}")
        return r.stdout.strip()

    def preflight(self):
        """Fail loudly NOW rather than halfway through a demo. Confirms the CLI is
        installed, the dog answers, and the move skill actually exists."""
        try:
            tools = subprocess.run(["dimos", "mcp", "list-tools"], capture_output=True,
                                   text=True, timeout=30)
        except FileNotFoundError:
            raise RuntimeError("the `dimos` CLI is not on PATH. Install dimOS, or run with "
                               "--manual (handheld rig) or --sim (no hardware).") from None
        except subprocess.TimeoutExpired:
            raise RuntimeError("`dimos mcp list-tools` timed out - is the dog powered on "
                               "and on the same hotspot as this laptop?") from None
        if tools.returncode != 0:
            raise RuntimeError("`dimos mcp list-tools` failed:\n"
                               + (tools.stderr.strip() or tools.stdout.strip()))
        if self.skill not in tools.stdout:
            raise RuntimeError(f"the dog does not expose a skill called '{self.skill}'.\n"
                               f"Skills it does expose:\n{tools.stdout.strip()}\n"
                               "Pass the right one with --skill / --fwd-arg / --left-arg.")
        if self.observe_skill not in tools.stdout:
            print(f"  note: no '{self.observe_skill}' skill - photos at finds will be skipped")

    def move(self, dx, dy, target=None):
        """Relative move of the dog body in metres (x forward, y left). One axis per
        call so it works even if the skill only accepts one argument at a time."""
        if abs(dx) >= self.min_move:
            self._call(self.skill, "--arg", f"{self.fwd_arg}={dx:.3f}")
        if abs(dy) >= self.min_move:
            self._call(self.skill, "--arg", f"{self.left_arg}={dy:.3f}")
        time.sleep(self.settle)  # let the body stop swaying before we measure

    def observe(self):
        try:
            return self._call(self.observe_skill, timeout=90)
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
