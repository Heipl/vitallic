# Porting Patsiuk onto dimOS

Everything here was checked against the **real dimOS install** (`dimos 0.0.14`, in WSL at
`/root/dimensional-applications/.venv`) by reading the installed package source — not guessed
from docs. Nothing here has been confirmed on the live dog yet. The one test that settles
the design is `tools/min_move_test.py`.

## What the scan runs on now

`field_scan.py` defaults to `--skill precise_move`. That skill lives in
`dimos_patsiuk/` and is exposed by a custom blueprint that wraps stock
`unitree-go2-agentic`:

```
VIRTUAL_ENV=/root/dimensional-applications/.venv uv pip install -e dimos_patsiuk
# one-time, already done on this machine: dimos list now shows patsiuk-dimos.scan

# also required, NOT yet done: the Go2 connection extra
VIRTUAL_ENV=/root/dimensional-applications/.venv uv pip install "dimos[unitree]"

dimos run patsiuk-dimos.scan --robot-ip <DOG_IP>
dimos mcp list-tools | grep precise_move
```

`observe` and `move_to` stay available on that blueprint. Pass `--skill move_to`
only if you want the stock planner path (and then the 20 cm trap below applies).

## What was already right

The CLI shape in `robot.py` was correct:

```
dimos mcp call <tool> --json-args '{"k": v}'     # also: -a key=value
dimos mcp call <tool> --timeout N
dimos mcp list-tools | status | modules
dimos run <blueprint> ; dimos status ; dimos stop ; dimos restart
dimos topic echo|send ; dimos shell
```

`observe` is real (`dimos/agents/skills/observe_skill.py`) but returns an **Image**, not text.

## Why `move_to` cannot do a 5 cm scan

`move_to` always calls `self._navigation.set_goal()`
(`unitree_skill_container.py`). The planner's arrival test is:

```
_goal_tolerance: float = 0.2          # metres
if distance(goal, odom) < 0.2 and |angle_diff| < 15deg:
    "Close enough to goal. Accepting as arrived."
```

Both Go2 controller blueprints set `"goal_tolerance": 0.20` explicitly. A commanded
5 cm step therefore returns "Navigation goal reached" **without the dog moving**.
All 17 scan points would be sampled at one physical position, the dipole design
matrix would go degenerate, and the run would print confident nonsense.

Raising `--step` to clear 20 cm is not a workaround. At 20 cm the fit is statistically
tied with a peak-signal metal detector; at 30 cm it is worse and calls every piece of
scrap a mine. The anomaly from a shallow target is only ~20–30 cm wide.

`field_scan.py` still refuses `--step < 0.20` when `--skill move_to`. It does not
refuse that for `precise_move`.

The planner also picks its own route, so `plan_move()`'s "never step on a flagged
spot" proof is void under `move_to`. `precise_move` drives the body directly, so
that proof holds again — once hardware confirms the dog actually follows the
commanded legs.

## How `precise_move` bypasses the planner

`MovementManager` (in the base `unitree_go2` blueprint, therefore also in
`unitree-go2-agentic`) takes two velocity inputs:

```
nav_cmd_vel:  In[Twist]     # the planner
tele_cmd_vel: In[Twist]     # teleop; `_on_teleop` cancels the nav goal
cmd_vel:      Out[Twist]    # to the robot
```

Publishing `tele_cmd_vel` therefore outranks the planner: no arrival tolerance,
no replanned route. That is how the WASD keyboard-teleop blueprints already drive
the dog.

It cannot be done from the CLI. `UnitreeConnection` arms a 0.2 s deadman timer on
every velocity message (`robot/unitree/connection.py`), so you have to republish
faster than 5 Hz. Each `dimos topic send` takes far longer than that. Hence a
module: the loop runs in-process at 20 Hz, closed-loop on
`tfbuffer.get("world", "base_link")`, and `field_scan.py` calls it over MCP the
same way it called `move_to`.

The heading is held on purpose. The gradiometer assumes one heading for the whole
run so the dog's magnetism stays constant at the phones.

**The topic name is a guess until `dimos spy` confirms it.** Default remap is
`tele_cmd_vel`. If the live name differs:

```
PATSIUK_CMD_VEL_TOPIC=<real name> dimos run patsiuk-dimos.scan --robot-ip <IP>
```

## Missing extra on this install

`dimos list` shows `unitree-go2-agentic`, but loading any Go2 blueprint currently
fails with `No module named 'unitree_webrtc_connect'`. The `dimos` package
declares `Requires-Dist: unitree-webrtc-connect>=2.1.2; extra == "unitree"`, and
that extra is not installed. Stock `unitree-go2-agentic` is broken the same way
as `patsiuk-dimos.scan`. Fix:

```
VIRTUAL_ENV=/root/dimensional-applications/.venv uv pip install "dimos[unitree]"
```

then `python dimos_patsiuk/check_install.py` should print OK.

Also: `dimos whoami` currently says not logged in. Run `dimos login` before the
agentic blueprint.

## Bringing it up (tomorrow)

```bash
# 0. mirrored WSL networking (recommended) so the dog and WSL share a LAN
#    write %USERPROFILE%\.wslconfig with networkingMode=mirrored, then wsl --shutdown

# 1. Go2 extra + scan blueprint
VIRTUAL_ENV=/root/dimensional-applications/.venv uv pip install "dimos[unitree]"
VIRTUAL_ENV=/root/dimensional-applications/.venv uv pip install -e /mnt/c/Users/aliek/shit/vitallic/dimos_patsiuk
/root/dimensional-applications/.venv/bin/python /mnt/c/Users/aliek/shit/vitallic/dimos_patsiuk/check_install.py

# 2. find the dog, start the blueprint
/root/dimensional-applications/.venv/bin/dimos login          # if whoami says not logged in
/root/dimensional-applications/.venv/bin/dimos go2tool
/root/dimensional-applications/.venv/bin/dimos run patsiuk-dimos.scan --robot-ip <DOG_IP>

# 3. confirm skills, then measure
/root/dimensional-applications/.venv/bin/dimos mcp list-tools
/root/dimensional-applications/.venv/bin/python /mnt/c/Users/aliek/shit/vitallic/tools/min_move_test.py \
    --dimos /root/dimensional-applications/.venv/bin/dimos
```

Clear ~2 m in front of the dog, have it standing, keep a tape measure and a way to stop it.

If `precise_move` is missing from `list-tools`, you started the stock blueprint by
mistake. If 5 cm does not actually move the dog, the next design is a continuous
traverse that stamps magnetometer samples with TF pose — not a larger `--step`.
