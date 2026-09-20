"""precise_move - a scan-sized step the dimOS planner refuses to make.

WHY THIS EXISTS

`move_to` is the only movement skill on the Go2, and it always goes through the
replanning A* planner (`unitree_skill_container.py`: `self._navigation.set_goal`).
That planner calls a goal reached as soon as it is within
`global_planner._goal_tolerance = 0.2` m, and both Go2 controller blueprints set
`"goal_tolerance": 0.20` explicitly. So a commanded 5 cm step returns
"Navigation goal reached" WITHOUT THE DOG MOVING, and every point of a scan would
be measured from the same place.

`MovementManager` gives a way around it. It takes two velocity inputs and lets
teleop win:

    nav_cmd_vel:  In[Twist]     # the planner
    tele_cmd_vel: In[Twist]     # teleop  -> `_on_teleop` cancels the nav goal
    cmd_vel:      Out[Twist]    # to the robot

Driving `tele_cmd_vel` therefore bypasses the planner completely: no arrival
tolerance, so any step size is possible, and no replanner choosing its own route,
which is what restores `field_scan.py`'s promise that the dog never crosses a
flagged spot.

The catch is that this cannot be done from the CLI. `UnitreeConnection` arms a
deadman timer on every velocity message (`robot/unitree/connection.py`):

    self.cmd_vel_timeout = 0.2
    self.stop_timer = threading.Timer(self.cmd_vel_timeout, self.stop_movement)

so velocity has to be republished faster than 5 Hz to keep the dog walking, and a
`dimos topic send` subprocess takes far longer than that per call. Hence a module:
the control loop runs in-process, and `field_scan.py` calls it over MCP exactly the
way it calls `move_to` today.

HEADING IS HELD ON PURPOSE. The whole gradiometer design assumes the dog keeps one
heading for the entire run, so its own magnetism stays constant at the phones and
cancels into the fit's per-phone offsets. This loop actively steers yaw back to
where it started rather than letting it drift.

NOT YET RUN ON A DOG. The interfaces are read from the installed dimos 0.0.14
source, but no part of this has been executed against hardware. Check
`tools/min_move_test.py` first, and keep a hand on the stop.
"""

from __future__ import annotations

import math
import os
import time
from typing import Any

from dimos.agents.annotation import skill
from dimos.core.module import Module, ModuleConfig
from dimos.core.stream import In, Out
from dimos.msgs.geometry_msgs.Twist import Twist
from dimos.msgs.geometry_msgs.Vector3 import Vector3
from dimos.msgs.tf2_msgs.TFMessage import TFMessage
from dimos.utils.logging_config import setup_logger

logger = setup_logger()

WORLD_FRAME = "world"
BODY_FRAME = "base_link"

# The MovementManager input that cancels the nav goal and outranks the planner.
# Lives here rather than in blueprint.py so this module stays importable without
# the Go2 connection stack. The concrete topic differs between blueprints, so
# check `dimos spy` against the live robot and override if it does not match.
CMD_VEL_TOPIC = os.environ.get("PATSIUK_CMD_VEL_TOPIC", "tele_cmd_vel")


class PreciseMoveConfig(ModuleConfig):
    rate_hz: float = 20.0          # must stay above the 5 Hz deadman floor
    max_speed: float = 0.25        # m/s
    min_speed: float = 0.06        # m/s; below this the dog may not break stiction
    approach_gain: float = 1.5     # commanded speed = gain * remaining distance
    tolerance_m: float = 0.015     # close enough to stop
    max_yaw_rate: float = 0.4      # rad/s of heading correction
    yaw_gain: float = 1.2
    max_leg_m: float = 2.0         # refuse anything longer than a scan step
    timeout_s: float = 30.0
    settle_s: float = 0.4          # let the body stop swaying before measuring


def _wrap_pi(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class PreciseMove(Module):
    """Closed-loop body move of any size, driven on velocity instead of a goal."""

    config: PreciseMoveConfig

    tf: In[TFMessage]
    cmd_vel: Out[Twist]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def _halt(self) -> None:
        self.cmd_vel.publish(Twist(linear=Vector3(0.0, 0.0, 0.0),
                                   angular=Vector3(0.0, 0.0, 0.0)))

    def _pose(self):
        tf = self.tfbuffer.get(WORLD_FRAME, BODY_FRAME)
        return None if tf is None else tf.to_pose()

    @skill
    def precise_move(self, x: float = 0.0, y: float = 0.0) -> str:
        """Move the body x metres forward and y metres left, keeping the heading.

        Unlike move_to this does not use the planner, so steps far below the
        planner's 0.20 m arrival tolerance are executed rather than silently
        skipped. Blocks until the dog arrives, stalls or times out.

        Args:
            x: forward in metres, negative is backward
            y: left in metres, negative is right
        """
        x, y = float(x), float(y)
        leg = math.hypot(x, y)
        if leg > self.config.max_leg_m:
            return (f"Refused: {leg:.2f} m is longer than max_leg_m "
                    f"({self.config.max_leg_m:.2f} m). This skill is for scan steps.")
        if leg < 1e-4:
            return "Nothing to do: zero-length move."

        start = self._pose()
        if start is None:
            return "Failed to get the position of the robot."

        yaw0 = start.orientation.to_euler().yaw
        # Same construction move_to uses, so the frame convention matches exactly:
        # x forward, y left, relative to where the dog stands now.
        target = start.position + start.orientation.rotate_vector(Vector3(x, y, 0.0))

        period = 1.0 / self.config.rate_hz
        deadline = time.monotonic() + self.config.timeout_s
        closest = leg

        try:
            while time.monotonic() < deadline:
                pose = self._pose()
                if pose is None:
                    self._halt()
                    return "Lost the robot pose mid-move; stopped."

                err_x = target.x - pose.position.x
                err_y = target.y - pose.position.y
                remaining = math.hypot(err_x, err_y)
                if remaining <= self.config.tolerance_m:
                    break
                closest = min(closest, remaining)

                # Rotate the world-frame error into the body frame the dog drives in.
                yaw = pose.orientation.to_euler().yaw
                forward = err_x * math.cos(yaw) + err_y * math.sin(yaw)
                left = -err_x * math.sin(yaw) + err_y * math.cos(yaw)

                speed = _clamp(remaining * self.config.approach_gain,
                               self.config.min_speed, self.config.max_speed)
                scale = speed / remaining
                yaw_rate = _clamp(_wrap_pi(yaw0 - yaw) * self.config.yaw_gain,
                                  -self.config.max_yaw_rate, self.config.max_yaw_rate)

                self.cmd_vel.publish(Twist(
                    linear=Vector3(forward * scale, left * scale, 0.0),
                    angular=Vector3(0.0, 0.0, yaw_rate)))
                time.sleep(period)
            else:
                self._halt()
                return (f"Timed out after {self.config.timeout_s:.0f}s; "
                        f"got within {closest * 100:.1f} cm of a {leg * 100:.1f} cm leg.")
        finally:
            # A raised exception must never leave the dog walking.
            self._halt()

        time.sleep(self.config.settle_s)

        end = self._pose()
        if end is None:
            return "Arrived, but lost the pose while confirming."
        moved = math.hypot(end.position.x - start.position.x,
                           end.position.y - start.position.y)
        drift = math.degrees(_wrap_pi(end.orientation.to_euler().yaw - yaw0))
        return (f"Moved {moved * 100:.1f} cm of a commanded {leg * 100:.1f} cm; "
                f"heading drifted {drift:+.1f} deg.")
