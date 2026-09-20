"""The stock agentic Go2 blueprint plus the precise_move skill.

Run it with:

    dimos run vitallic-dimos.scan --robot-ip <DOG_IP>

`unitree-go2-agentic` is kept underneath unchanged, so `move_to`, `observe` and
everything `field_scan.py` already relies on stay exactly where they were. The
only addition is `PreciseMove`, whose velocity output is remapped onto the input
`MovementManager` treats as teleop -- the one that outranks the planner.

THE TOPIC NAME IS A GUESS UNTIL YOU CHECK IT. `MovementManager` declares the port
as `tele_cmd_vel`, and that is the default here, but the concrete topic differs
between blueprints (the rpp controller binds `/cmd_vel` while
`unitree_go2_mid360_record` remaps KeyboardTeleop's `cmd_vel` to `tele_cmd_vel`).
List what is actually live with `dimos spy`, and if it differs:

    VITALLIC_CMD_VEL_TOPIC=<real name> dimos run vitallic-dimos.scan --robot-ip <IP>
"""

from __future__ import annotations

from dimos.core.coordination.blueprints import autoconnect
from dimos.robot.unitree.go2.blueprints.agentic.unitree_go2_agentic import unitree_go2_agentic

from vitallic_dimos.precise_move import CMD_VEL_TOPIC, PreciseMove

vitallic_scan = autoconnect(
    unitree_go2_agentic,
    PreciseMove.blueprint(),
).remappings([(PreciseMove, "cmd_vel", CMD_VEL_TOPIC)])
