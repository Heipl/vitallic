# Porting Patsiuk onto dimOS

Everything here was checked against the **real dimOS install** (`dimos 0.0.14`, in WSL at
`/root/dimensional-applications/.venv`) by reading the installed package source — not guessed
from docs. Nothing in this file has been confirmed on the live dog yet, because that needs
dimOS running and the robot moving. The one test that settles the design is
`tools/min_move_test.py`.

## What was already right

The CLI shape in `robot.py` was correct:

```
dimos mcp call <tool> --json-args '{"k": v}'     # also: -a key=value
dimos mcp call <tool> --timeout N
dimos mcp list-tools | status | modules
dimos run <blueprint> ; dimos status ; dimos stop ; dimos restart
dimos topic echo|send ; dimos shell        # IPython attached to the coordinator
```

## What was wrong

`robot.py` defaulted to a skill named `relative_move`, with `forward=` / `left=` arguments.
**No such skill exists anywhere in the package.** The real one is in
`dimos/robot/unitree/unitree_skill_container.py`:

```python
@skill
def move_to(self, x=0.0, y=0.0, degrees=None, relative=False) -> str
```

With `relative=True`, **x is forward and y is left, in metres** — which happens to match
`field_scan.py`'s arena frame exactly. So the correct call is:

```
dimos mcp call move_to --json-args '{"x": 0.30, "y": 0.0, "relative": true}'
```

`observe` is real (`dimos/agents/skills/observe_skill.py`) but returns an **Image**, not text,
so what `dimos mcp call observe` prints still needs checking on a live server.

Other skills on the same container: `wait(seconds)`, `current_time()`,
`execute_sport_command(command_name)`, and an RPC `stop()`.

## The blocker: a 5 cm step cannot be executed

`dimos/navigation/replanning_a_star/global_planner.py`:

```python
_goal_tolerance: float = 0.2          # metres
_rotation_tolerance = math.radians(15)
```

and the arrival test (~line 224):

```python
if distance(goal, odom) < self._goal_tolerance and |angle_diff| < self._rotation_tolerance:
    logger.info("Close enough to goal. Accepting as arrived.")
```

Both Go2 controller blueprints set it explicitly — `unitree_go2_rpp_controller.py:112` and
`unitree_go2_holonomic_controller.py:116`, both `"goal_tolerance": 0.20`.

`field_scan.py` used `--step 0.05`; the whole 9-point cross spans 0.40 m. **Every commanded
move is inside the arrival tolerance, so `move_to` returns "Navigation goal reached" without
the dog moving.** All 17 scan points would then be sampled at one physical position, the
dipole design matrix goes degenerate, and the run prints confident nonsense.

This is now caught rather than suffered: `field_scan.py` refuses to start in dog mode when
`--step` is below the tolerance, and `DimosMover.move()` refuses a sub-tolerance leg.

## The second problem: the safety guarantee does not survive

`move_to` hands the goal to a **replanning A\*** planner (`set_goal` then `_wait_for_goal`),
which picks its own route and replans around obstacles. `field_scan.py`'s `plan_move()` proves
an L-shaped path clears every flagged spot — but the planner is free to route the dog straight
over one. **Treat "the dog never steps on a flagged spot" as void** until the mover drives the
body directly instead of through the planner.

## Speed

`_wait_for_goal` does `time.sleep(1.0)` up front, `settle=2.0`, `timeout=100`. That is ≥3 s per
call before any walking. 17 points × 4 spots = 68 moves ≈ 3.5 min of pure settle time.

## Recommended design: continuous traverse

Fixes all three problems at once, and is how real magnetometer surveys actually work:

1. Walk legs the planner can do (≥ the measured minimum, likely 0.3–0.5 m) with
   `move_to(relative=True)`.
2. Stream both phones continuously at ~50 Hz for the whole traverse instead of stopping.
3. Stamp every magnetometer sample with the dog's pose from TF (`world` → `base_link`) —
   `UnitreeSkillContainer` already reads it via `self.tfbuffer.get("world", "base_link")`.
4. Fit the dipole to the resulting track, which has far more than 17 points.

Better implemented as a real dimOS **Module** with `tf: In[TFMessage]` and an `@skill`, rather
than shelling out to the CLI — that is also a much better fit for the Dimensional challenge
(perception → reasoning → action).

## Bringing it up

```bash
# terminal 1 - start dimOS against the dog
/root/dimensional-applications/.venv/bin/dimos go2tool          # find the robot IP
/root/dimensional-applications/.venv/bin/dimos run unitree-go2-agentic --robot-ip <DOG_IP>

# terminal 2 - confirm it is live and the skills are really there
/root/dimensional-applications/.venv/bin/dimos mcp status
/root/dimensional-applications/.venv/bin/dimos mcp list-tools
```

`unitree-go2-agentic` is the blueprint that wires up the skills we need —
`dimos/robot/unitree/go2/blueprints/agentic/_common_agentic.py` registers
`NavigationSkillContainer`, `ObserveSkill`, `PersonFollowSkillContainer`,
`UnitreeSkillContainer`, `WebInput` and `SpeakSkill`.

Then measure the real minimum move before anything else:

```bash
python tools/min_move_test.py --dimos /root/dimensional-applications/.venv/bin/dimos
```

Clear ~2 m in front of the dog, have it standing, keep a tape measure and a way to stop it.
