## SUMMARY
DimensionalOS (dimOS) is real and open source at github.com/dimensionalOS/dimos (Apache-2.0), shipped on PyPI as `dimos` v0.0.14 (released 2026-09-19, Python >=3.10,<3.13). It reimplements ROS message semantics in pure Python over LCM: the dimOS-side wrappers live one-class-per-file under `dimos/msgs/<pkg>/<Class>.py` (there are NO `__init__.py` files anywhere in the repo, so you must import the full module path, e.g. `from dimos.msgs.nav_msgs.OccupancyGrid import OccupancyGrid`), while the raw wire structs come from a separate PyPI dist `dimos-lcm` that imports as `dimos_lcm`. `nav_msgs/MapMetaData` has NO dimOS wrapper — it is used directly as `from dimos_lcm.nav_msgs import MapMetaData`. OccupancyGrid is confirmed int8 with 0=free, 1..99 graded cost, 100=lethal, -1=unknown (`CostValues` IntEnum), stored as a 2-D `NDArray[np.int8]` of shape (height, width) with a `Pose` origin at the bottom-left corner. Modules are plain classes subclassing `dimos.core.module.Module` with class-level `name: In[T]` / `Out[T]` / `IO[T]` annotations and `@rpc`-decorated methods; they are composed with `autoconnect(...)` over `Cls.blueprint(**config)` and wired by matching `(property_name, message_type)`, with topic `/<property_name>`. The real navigation classes are `DanHolonomicTC` (`dimos.navigation.dannav.holonomic_tc.module`), `DanLocalPlanner` (`dimos.navigation.dannav.local_planner.module`), `MLSPlannerNative` (`dimos.navigation.nav_3d.mls_planner.mls_planner_native`), `ReplanningAStarPlanner` (`dimos.navigation.replanning_a_star.module`) and `CostMapper` (`dimos.mapping.costmapper`). Critically for deliverable B: only `ReplanningAStarPlanner` consumes an `OccupancyGrid` (its `global_costmap: In[OccupancyGrid]` port) — `DanLocalPlanner` is NOT an SE(2) search planner but a replan-gate/path-smoother, and `MLSPlannerNative` searches a voxel `PointCloud2`, not a grid. dimOS has NO lat/lon-to-metric projection: it ships only a `LatLon` dataclass, a haversine distance, and Web-Mercator OSM tile helpers, so we must supply our own ENU/UTM anchor ourselves.

## FINDINGS

### [verified] Package identity, install, versions
PyPI dist `dimos`, version 0.0.14, released 2026-09-19, `requires-python = ">=3.10,<3.13"`, Apache-2.0, authors "Dimensional Team <build@dimensionalOS.com>", description "Powering agentive generalist robotics". Install: `pip install dimos` or the documented `uv venv --python "3.12" && source .venv/bin/activate && uv pip install 'dimos[base,unitree]'`. Guided installer: `curl -fsSL https://raw.githubusercontent.com/dimensionalOS/dimos/main/scripts/install.sh | bash`. Extras groups: agents, perception, manipulation, planning, control, web, visualization, sim, mapping, drone, unitree; `base` = agents+web+perception+visualization. Console scripts: `dimos`, `lcmspy`, `agentspy`, `humancli`, `rerun-bridge`, `doclinks`, `dtop`. Build backend setuptools+pybind11.
_source: https://raw.githubusercontent.com/dimensionalOS/dimos/main/pyproject.toml and https://pypi.org/project/dimos/_

### [verified] Companion message package dimos_lcm
Separate PyPI dist `dimos-lcm` (repo github.com/dimensionalOS/dimos-lcm, root pyproject `name = "dimos_lcm"`, version 0.1.3). Python import name is `dimos_lcm`. Its setuptools package-dir maps `dimos_lcm.nav_msgs` -> `generated/python_lcm_msgs/lcm_msgs/nav_msgs`, likewise for geometry_msgs, std_msgs, sensor_msgs, tf2_msgs, vision_msgs, trajectory_msgs, visualization_msgs, shape_msgs, stereo_msgs, diagnostic_msgs, actionlib_msgs, builtin_interfaces, foxglove_msgs. Depends on `lcm-dimos-fork` (still imports as `lcm`), `foxglove-websocket`, `numpy`. Bindings are generated from ROS .msg sources into .lcm types, then into py/cpp/cs/java/lua/ts/rust.
_source: https://raw.githubusercontent.com/dimensionalOS/dimos-lcm/main/pyproject.toml and its README.md_

### [verified] No __init__.py — import full module paths
A recursive GitHub tree listing of dimensionalOS/dimos main (3312 entries, not truncated) contains ZERO `__init__.py` files under `dimos/msgs/`. Every dimOS source file imports the full path, e.g. `from dimos.msgs.geometry_msgs.Pose import Pose`, `from dimos.msgs.nav_msgs.Path import Path`. The repo README's snippet `from dimos.msgs.geometry_msgs import Twist` and `from dimos.msgs.sensor_msgs import Image` is inconsistent with the on-disk layout (it would bind the submodule, not the class) — do NOT copy the README form.
_source: GET https://api.github.com/repos/dimensionalOS/dimos/git/trees/main?recursive=1 + grep of every downloaded source file_

### [verified] EXACT message import paths
from dimos.msgs.nav_msgs.OccupancyGrid import OccupancyGrid, CostValues, block_max_reduce
from dimos.msgs.nav_msgs.Path import Path
from dimos.msgs.nav_msgs.Odometry import Odometry
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.geometry_msgs.Pose import Pose
from dimos.msgs.geometry_msgs.Quaternion import Quaternion
from dimos.msgs.geometry_msgs.Point import Point
from dimos.msgs.geometry_msgs.PointStamped import PointStamped
from dimos.msgs.geometry_msgs.Vector3 import Vector3
from dimos.msgs.geometry_msgs.Twist import Twist
from dimos.msgs.std_msgs.Header import Header
from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2
from dimos.msgs.sensor_msgs.Image import Image, ImageFormat
from dimos.msgs.vision_msgs.Detection3DArray import Detection3DArray
from dimos.msgs.tf2_msgs.TFMessage import TFMessage
MapMetaData has NO dimOS wrapper: `from dimos_lcm.nav_msgs import MapMetaData`.
NOTE the nav modules' Bool/String ports use `from dimos_lcm.std_msgs import Bool, String`, NOT dimos.msgs.std_msgs.
_source: Read of dimos/msgs/nav_msgs/OccupancyGrid.py, Path.py, geometry_msgs/PoseStamped.py, Pose.py, Quaternion.py, PointStamped.py, std_msgs/Header.py, navigation/replanning_a_star/module.py, navigation/movement_manager/movement_manager.py_

### [verified] OccupancyGrid class: exact constructor and fields
class OccupancyGrid(Timestamped), msg_name="nav_msgs.OccupancyGrid".
__init__(self, grid: NDArray[np.int8]|None=None, width: int|None=None, height: int|None=None, resolution: float=0.05, origin: Pose|None=None, frame_id: str="world", ts: float|None=None)
Attributes: ts: float; frame_id: str; info: MapMetaData (the dimos_lcm one); grid: NDArray[np.int8] of shape (height, width).
Properties: width, height, resolution, origin (all proxy self.info); total_cells, occupied_cells (grid>=1), free_cells (==0), unknown_cells (==-1), occupied_percent, free_percent, unknown_percent.
Methods: world_to_grid(VectorLike)->Vector3, grid_to_world(VectorLike)->Vector3, cell_value(Vector3)->int, filter_above(int), filter_below(int), max(), copy(), lcm_encode()->bytes, lcm_decode(bytes)->OccupancyGrid, from_path(pathlib.Path) [.npy or .png], to_rerun(colormap=None, z_offset=0, opacity=1.0, cost_range=None, background=None, color_lookup_table=None).
When grid is None and width/height given, grid initialises to np.full((height,width), -1, int8).
_source: Read of https://raw.githubusercontent.com/dimensionalOS/dimos/main/dimos/msgs/nav_msgs/OccupancyGrid.py (599 lines)_

### [verified] OccupancyGrid value convention CONFIRMED (int8 0..100, -1 unknown)
class CostValues(IntEnum): UNKNOWN = -1; FREE = 0; OCCUPIED = 100. Docstring: "These values follow the ROS nav_msgs/OccupancyGrid convention: 0: Free space, 1-99: Occupied space with varying cost levels, 100: Lethal obstacle, -1: Unknown space". The rerun LUT is 102 entries indexed by `np.clip(grid + 1, 0, 101)`, i.e. exactly the domain [-1, 100]. Docs table for the go2 height_cost costmap: 0 = flat/easy, 50 = moderate slope (~7.5cm rise/cell), 100 = steep/impassable (>=15cm rise/cell), -1 = unknown (no observations).
_source: dimos/msgs/nav_msgs/OccupancyGrid.py lines 123-136, 547; docs/capabilities/navigation/deep_dive.md lines 98-103_

### [verified] Grid geometry: indexing, origin corner, rotation
grid is indexed [row=y, col=x]: `grid = np.array(data).reshape((info.height, info.width))` and `cell_value` does `int(self.grid[y, x])`. Origin is the BOTTOM-LEFT corner in world coords: `grid_to_world` = (ox + gx*res, oy + gy*res); `world_to_grid` = ((wx-ox)/res, (wy-oy)/res). Both are explicitly commented "simplified, assuming no rotation" — the origin Pose's quaternion is IGNORED by these helpers. to_rerun() builds a quad from (ox,oy) to (ox + width*res, oy + height*res) and flips rows for world coords.
_source: dimos/msgs/nav_msgs/OccupancyGrid.py lines 280-318, 508-516, 560-576_

### [verified] LCM wire layout of the required types (from the .lcm IDL)
nav_msgs.MapMetaData { std_msgs.Time map_load_time; float resolution; int32_t width; int32_t height; geometry_msgs.Pose origin; }  // resolution is float32 on the wire (struct '>fii'), width/height are INT32 not uint32
nav_msgs.OccupancyGrid { int32_t data_length; std_msgs.Header header; MapMetaData info; int8_t data[data_length]; }
nav_msgs.Path { int32_t poses_length; std_msgs.Header header; geometry_msgs.PoseStamped poses[poses_length]; }
std_msgs.Header { int32_t seq; std_msgs.Time stamp; string frame_id; }
std_msgs.Time { int32_t sec; int32_t nsec; }
geometry_msgs.Pose { Point position; Quaternion orientation; }
geometry_msgs.PoseStamped { std_msgs.Header header; Pose pose; }
geometry_msgs.Point { double x; double y; double z; }
geometry_msgs.Quaternion { double x; double y; double z; double w; }
Generated MapMetaData __init__ signature: MapMetaData(map_load_time=std_msgs.Time(), resolution=0.0, width=0, height=0, origin=geometry_msgs.Pose()).
_source: raw.githubusercontent.com/dimensionalOS/dimos-lcm/main/lcm_types/{nav_msgs_MapMetaData,nav_msgs_OccupancyGrid,nav_msgs_Path,std_msgs_Header,std_msgs_Time,geometry_msgs_Pose,geometry_msgs_PoseStamped,geometry_msgs_Point,geometry_msgs_Quaternion}.lcm and generated/python_lcm_msgs/lcm_msgs/nav_msgs/MapMetaData.py_

### [verified] Path class: exact API
class Path(Timestamped), msg_name="nav_msgs.Path".
__init__(self, ts: float|None=None, frame_id: str="world", poses: list[PoseStamped]|None=None, **kwargs)
Attributes: ts, frame_id, poses: list[PoseStamped].
Methods: __len__, __bool__, __getitem__, __iter__, head(), last(), tail(), push(pose)->Path (immutable), push_mut(pose)->None, slice(start,end), extend(other)->Path, extend_mut(other), reverse(), clear(), lcm_encode(), lcm_decode(), to_rerun(color=(0,255,128), z_offset=0.5, radii=0.05).
On encode, EVERY pose gets the Path's frame_id (per-pose frame_id is overwritten); on decode likewise.
_source: Read of dimos/msgs/nav_msgs/Path.py (215 lines)_

### [verified] PoseStamped / Pose / Quaternion / PointStamped constructors
class PoseStamped(Pose, Timestamped), msg_name="geometry_msgs.PoseStamped". Accepts PoseStamped(ts, frame_id) positionally when the first arg is int/float/str and len(args)<3, otherwise PoseStamped(x,y,z) / PoseStamped(x,y,z,qx,qy,qz,qw) / PoseStamped(ts=..., frame_id=..., position=[x,y,z], orientation=[x,y,z,w]). Extra methods: new_transform_to(name), new_transform_from(name), find_transform(other)->Transform, to_rerun(), to_rerun_arrow(length=0.5).
class Pose(LCMPose): fields position: Vector3, orientation: Quaternion. Overloads: Pose(), Pose(x,y,z), Pose(x,y,z,qx,qy,qz,qw), Pose(position, orientation), Pose(position=..., orientation=...), Pose((position, orientation)), Pose({'position':..., 'orientation':...}). Read-only props x, y, z, roll, pitch, yaw (radians, via orientation.to_euler()).
class Quaternion(LCMQuaternion): Quaternion(), Quaternion(x,y,z,w), Quaternion(sequence|ndarray|Quaternion). Classmethods from_euler(vector: Vector3)->Quaternion, from_rotation_matrix(np.ndarray). Methods to_tuple/to_list/to_numpy/to_euler()->Vector3/to_rotation_matrix/conjugate/inverse/normalize/rotate_vector(Vector3)/angle_to/dot/__mul__. Identity default is (0,0,0,1).
class PointStamped(Point, Timestamped): __init__(x=0.0, y=0.0, z=0.0, ts=None, frame_id=""), has to_pose_stamped().
_source: Read of dimos/msgs/geometry_msgs/{PoseStamped,Pose,Quaternion,PointStamped}.py_

### [verified] Module definition surface (the real class/decorator)
from dimos.core.module import Module, ModuleConfig
from dimos.core.stream import In, Out, IO
from dimos.core.core import rpc
A module is a subclass of Module with class-level annotations `name: In[MsgType]` / `Out[MsgType]` / `IO[MsgType]` and a `config: MyConfig` where MyConfig subclasses ModuleConfig (a pydantic BaseConfig; inherited fields include rpc_transport, default_rpc_timeout, rpc_timeouts, frame_id_prefix, frame_id, instance_name, g: GlobalConfig). Lifecycle methods start()/stop()/build() are @rpc and you must call super().start()/super().stop(). ClassVars: `deployment: Literal['python','docker'] = 'python'`, `dedicated_worker: bool = False`. Module.name is the lowercased class name. `Module.blueprint` is a classproperty returning partial(Blueprint.create, cls), so `MyModule.blueprint(arg=1)` builds a Blueprint. Introspection helpers: `MyModule.io()`, `MyModule.module_info()`, `dimos.core.introspection.svg.to_svg(bp, path)`.
_source: Read of dimos/core/module.py (lines 100-179, 440-456, 763+) and docs/usage/modules.md_

### [verified] Minimal working module skeleton (verified pattern)
from reactivex.disposable import Disposable
from dimos.core.core import rpc
from dimos.core.module import Module, ModuleConfig
from dimos.core.stream import In, Out
from dimos.msgs.nav_msgs.OccupancyGrid import OccupancyGrid
from dimos.msgs.geometry_msgs.PointStamped import PointStamped

class MinePriorConfig(ModuleConfig):
    prior_npy: str = ""
    resolution_m: float = 0.5

class MinePriorMap(Module):
    config: MinePriorConfig
    detection: In[PointStamped]
    global_costmap: Out[OccupancyGrid]

    def __init__(self, **kwargs): super().__init__(**kwargs); self._grid = None

    @rpc
    def start(self) -> None:
        super().start()
        self.register_disposable(Disposable(self.detection.subscribe(self._on_detection)))

    def _on_detection(self, msg: PointStamped) -> None:
        ...
        self.global_costmap.publish(self._grid)

    @rpc
    def stop(self) -> None: super().stop()

Alternative async form: declaring `async def handle_detection(self, msg)` for a stream named `detection` auto-subscribes it at start() onto the module's private asyncio loop, serialized per-handler with LATEST-only backpressure (intermediate messages dropped).
_source: Pattern taken verbatim from dimos/navigation/dannav/local_planner/module.py and dimos/mapping/costmapper.py; async form from docs/usage/modules.md lines 286-323_

### [verified] Message exchange: topics, autoconnect, transports, remapping
Wiring is by `(property_name, message_type)`: an `Out[T] foo` connects to every `In[T] foo` across the blueprint. Default topic name is `/<property_name>`; if two modules share a property name with different types both get a random topic. Compose with `from dimos.core.coordination.blueprints import autoconnect, Blueprint`; `autoconnect(a_bp, b_bp, ...)` returns a frozen Blueprint. Chainable methods on a Blueprint: `.remappings([(ModuleCls, 'old_name', 'new_name')])`, `.transports({("name", MsgType): LCMTransport("/topic", MsgType)})`, `.global_config(n_workers=10, robot_model="...", obstacle_avoidance=False)`. Default transport is `LCMTransport` when the payload has `lcm_encode`, else `pLCMTransport` (pickled LCM); `pSHMTransport` available from dimos.core.transport. Build/run: `from dimos.core.coordination.module_coordinator import ModuleCoordinator; ModuleCoordinator.build(blueprint).loop()`. To expose a blueprint to `dimos run <name>`, declare a `[project.entry-points."dimos.blueprints"]` entry in your own package's pyproject; the name becomes `<dist-namespace>.<entry-point-name>`.
_source: docs/usage/blueprints.md lines 145-254, 501-530, 87-129_

### [verified] DanHolonomicTC — real class, config and ports
Module path: dimos.navigation.dannav.holonomic_tc.module. `class DanHolonomicTC(Module)` with `config: DanHolonomicTCConfig`.
Ports: path: In[Path]; odom: In[PoseStamped]; stop_movement: In[Bool]  (Bool from dimos_lcm.std_msgs); nav_cmd_vel: Out[Twist]; goal_reached: Out[Bool].
RPCs: start(), stop(), set_run_profile(profile: str) -> bool, get_state() -> NavigationState.
DanHolonomicTCConfig(ModuleConfig) fields with defaults: control_frequency: float = 10.0; run_profile: str = "walk"; speed_m_s: float|None = None; goal_tolerance: float = 0.2; orientation_tolerance: float = 0.35; k_position_per_s: float = 2.0; k_yaw_per_s: float = 1.0; k_velocity_per_s: float = 0.5; k_yaw_rate_per_s: float = 1.0; align_heading_before_move: bool = False; align_goal_yaw: bool = False.
Behavior: an empty Path stops the follow; a non-empty Path updates or starts a follow; it consumes odom directly (no TF), publishes nav_cmd_vel until within goal_tolerance then goal_reached. It consumes NO map/costmap at all — the planner owns route safety.
_source: Read of https://raw.githubusercontent.com/dimensionalOS/dimos/main/dimos/navigation/dannav/holonomic_tc/module.py lines 589-671_

### [verified] DanLocalPlanner — real class, and what it is NOT
Module path: dimos.navigation.dannav.local_planner.module. `class DanLocalPlanner(Module)` with `config: DanLocalPlannerConfig`.
Ports: planner_path: In[Path] (from MLSPlannerNative.path, remapped); odom: In[PoseStamped]; goal: In[PointStamped] (MovementManager click/cancel); path: Out[Path] (to DanHolonomicTC.path).
DanLocalPlannerConfig fields: lock_replan: float = 0.0 (commit-window in m; 0 disables gating); goal_commit_tolerance_m: float = 0.3; resample_spacing_m: float = 0.0 (0 disables smoothing); smoothing_window: int = 100.
IMPORTANT: despite the name it is NOT an SE(2) search local planner. Its own docstring calls it "Path-stream middleware between MLSPlannerNative and DanHolonomicTC" — a replan commit-gate plus a smooth/resample stage (`dimos.mapping.occupancy.path_resampling.smooth_resample_path`). It consumes no map of any kind.
_source: Read of https://raw.githubusercontent.com/dimensionalOS/dimos/main/dimos/navigation/dannav/local_planner/module.py (246 lines)_

### [verified] MLSPlannerNative — the actual SE(2)/surface search planner
Import path: `from dimos.navigation.nav_3d.mls_planner.mls_planner_native import MLSPlannerNative`. Rust-backed (dimos/navigation/nav_3d/mls_planner/rust/src/{planner,mls_planner,adjacency,dijkstra,surfaces,smoother,voxel}.rs). Blueprint kwargs used in the shipped Go2 blueprint: MLSPlannerNative.blueprint(world_frame="world", voxel_size=0.05, robot_height=0.5, start_z_offset_m=0.5, wall_clearance_m=0.2, wall_buffer_m=0.75, wall_buffer_weight=100.0, step_threshold_m=0.16, step_penalty_weight=1.0, viz_publish_hz=0.0).remappings([(MLSPlannerNative, "path", "planner_path")]). It plans over a multi-level-surface voxel map derived from the VoxelGridMapper PointCloud2 global map — it does NOT take a nav_msgs/OccupancyGrid. Related raycasting lives in dimos/mapping/ray_tracing/ (module.py, voxel_map.py, rust voxel_ray_tracer).
_source: Read of dimos/robot/unitree/go2/blueprints/navigation/unitree_go2_mls_htc.py lines 23-96 and the repo tree under dimos/navigation/nav_3d/mls_planner/_

### [verified] ReplanningAStarPlanner — THE module that consumes an OccupancyGrid
Import: `from dimos.navigation.replanning_a_star.module import ReplanningAStarPlanner, ReplanningAStarPlannerConfig`.
class ReplanningAStarPlanner(Module, NavigationInterface).
Inputs: odom: In[PoseStamped]; odometry: In[Odometry]; global_costmap: In[OccupancyGrid]; goal_request: In[PoseStamped]; clicked_point: In[PointStamped]; target: In[PoseStamped]; stop_movement: In[Bool].
Outputs: goal_reached: Out[Bool]; navigation_state: Out[String]; nav_cmd_vel: Out[Twist]; path: Out[Path]; navigation_costmap: Out[OccupancyGrid] (only published when env var DEBUG_NAVIGATION is set).
Config: ReplanningAStarPlannerConfig(robot_width: float|None = None, robot_rotation_diameter: float|None = None) — both fall back to GlobalConfig.
RPCs: start(), stop(), set_goal(goal: PoseStamped) -> bool, get_state() -> NavigationState, is_goal_reached() -> bool, cancel_goal() -> bool, set_replanning_enabled(enabled: bool) -> None, set_safe_goal_clearance(clearance: float) -> None, reset_safe_goal_clearance() -> None.
Internals: delegates to dimos.navigation.replanning_a_star.global_planner.GlobalPlanner; it derives its own planning costmap from the incoming global_costmap gradient.
_source: Read of https://raw.githubusercontent.com/dimensionalOS/dimos/main/dimos/navigation/replanning_a_star/module.py (164 lines)_

### [verified] How an OccupancyGrid is normally produced: CostMapper
Import: `from dimos.mapping.costmapper import CostMapper, Config`.
class CostMapper(Module): global_map: In[PointCloud2]; merged_map: In[PointCloud2]; global_costmap: Out[OccupancyGrid].
Config(ModuleConfig): algo: str = "height_cost"; config: OccupancyConfig = Field(default_factory=HeightCostConfig); initial_safe_radius_meters: float = 0.0.
Algorithms registry: `OCCUPANCY_ALGOS` in dimos.mapping.pointclouds.occupancy, alongside HeightCostConfig(can_pass_under=0.6, can_climb=0.15, ignore_noise=0.05, smoothing=1.0).
Pipeline in the shipped Go2 stack: GO2Connection --PointCloud2--> VoxelGridMapper (dimos.mapping.voxels.module.VoxelGridMapper, voxel_size=0.05, block_count=2_000_000, device="CUDA:0", carve_columns=True, emit_every=1) --PointCloud2--> CostMapper --OccupancyGrid(global_costmap)--> ReplanningAStarPlanner --Twist--> robot.
_source: Read of dimos/mapping/costmapper.py (112 lines) and docs/capabilities/navigation/deep_dive.md_

### [verified] How goals/waypoints are issued
Four verified routes into ReplanningAStarPlanner: (1) publish a PoseStamped on the `goal_request` topic; (2) publish a PoseStamped on `target`; (3) publish a PointStamped on `clicked_point` (converted with `.to_pose_stamped()`); (4) call the RPC `set_goal(PoseStamped)` directly, e.g. `app.get_module("ReplanningAStarPlanner").set_goal(ps)`.
MovementManager (dimos.navigation.movement_manager.movement_manager.MovementManager) relays clicks: clicked_point: In[PointStamped]; nav_cmd_vel: In[Twist]; tele_cmd_vel: In[Twist]; goal: Out[PointStamped]; way_point: Out[PointStamped]; cmd_vel: Out[Twist]; stop_movement: Out[Bool]. Config: tele_cooldown_sec=1.0, tele_cmd_vel_scaling=Twist(Vector3(1,1,1),Vector3(1,1,1)). Click sanity limits: |x|,|y| <= 500.0 m, |z| <= 50.0 m, non-finite rejected.
Cancel protocol: publish `Bool(data=True)` on stop_movement AND a NaN PointStamped (x=y=z=float('nan'), frame_id="map") on goal/way_point. DanLocalPlanner treats the NaN point as a disarm+drop-committed-path.
Completion signal: `goal_reached: Out[Bool]` (dimos_lcm.std_msgs.Bool, read `.data`).
Agent/CLI level: `dimos mcp call move_to --arg x=0.5 --arg relative=true` or `app.skills.move_to(x=2.0, relative=True)`.
_source: Read of dimos/navigation/replanning_a_star/module.py, dimos/navigation/movement_manager/movement_manager.py, docs/usage/python-api.md, README.md_

### [verified] Coordinate frames
Root world frame is literally named "world": OccupancyGrid's frame_id defaults to "world", Path's frame_id defaults to "world", VoxelGridMapper is configured frame_id="world", MLSPlannerNative takes world_frame="world". Standard child frames used in docs/source: base_link, camera_link, camera_optical. (MovementManager's NaN cancel point uses frame_id="map", an inconsistency in that one spot.)
Transforms ride an ordinary stream named `tf` carrying `dimos.msgs.tf2_msgs.TFMessage.TFMessage`; declare `tf: In[TFMessage]` / `Out[TFMessage]` / `IO[TFMessage]`. Inside a module, `self.tfbuffer.get(parent_frame, child_frame)` does direct, chained and inverse lookups (lazy TF view over the module's tf port; `TF(stream)` outside a module). `dimos.msgs.geometry_msgs.Transform.Transform` has frame_id, child_frame_id, translation, rotation, ts, composes with `*` and inverts with unary `-`/`.inverse()`.
Module frame_id defaults to the class name and can be set via ModuleConfig `frame_id` and `frame_id_prefix` (prefix yields "robot1/sensor_link").
The planner works in plain metric SE(2)/SE(3) in the world frame; it has no notion of geodesy.
_source: docs/usage/transforms.md; dimos/msgs/nav_msgs/{OccupancyGrid,Path}.py defaults; unitree_go2_mls_htc.py_

### [verified] NO lat/lon <-> metric projection exists in dimOS
A regex sweep of the full 3312-entry repo tree for gps|utm|enu|geodet|geopoint|NavSatFix returned only: dimos/agents/skills/{gps_nav_skill.py, demo_gps_nav.py, test_gps_nav_skills.py} and JSON fixtures. There is NO UTM/ENU/local-tangent-plane converter anywhere. What exists:
- `from dimos.mapping.models import LatLon` — @dataclass(frozen=True) LatLon(lat: float, lon: float, alt: float|None = None); plus `ImageCoord: TypeAlias = tuple[int,int]`.
- `from dimos.mapping.utils.distance import distance_in_meters(LatLon, LatLon) -> float` — haversine with EARTH_RADIUS_M = 6371000.
- `dimos.mapping.osm.osm`: `get_osm_map(position: LatLon, zoom_level: int = 18, n_tiles: int = 4) -> MapImage` (downloads 256px tiles from tile.openstreetmap.org), and MapImage.latlon_to_pixel(LatLon)->(x,y) / pixel_to_latlon((x,y))->LatLon using standard Web Mercator slippy-tile math.
- `dimos.agents.skills.gps_nav_skill.GpsNavSkillContainer(Module)` with `gps_location: In[LatLon]`, `gps_goal: Out[LatLon]`, `_max_valid_distance = 50000` (m), and the @skill `set_gps_travel_points(points: list[dict[str,float]]) -> str` taking [{"lat":..,"lon":..}, ...].
Conclusion: we must implement the lat/lon -> local metric anchor ourselves (pyproj UTM or a local ENU tangent plane anchored at an origin LatLon) and feed the planner metric world-frame coordinates.
_source: Recursive tree grep + Read of dimos/mapping/models.py, dimos/mapping/utils/distance.py, dimos/mapping/osm/osm.py, dimos/agents/skills/gps_nav_skill.py_

### [verified] Sensor-data ingestion and logging for detections
CLI recording: `dimos --record run <blueprint>` (bare --record == sqlite) writes `recordings/<run-id>/memory.db`; `--record mcap --record-engine rust` writes memory.mcap. Root is the checkout or `~/.local/state/dimos/recordings/`; run-id is `YYYYMMDD-HHMMSS-<blueprint>`. `--record-topics` takes comma-separated globs on the STREAM name without a leading slash (e.g. `lidar,odom,tf`, `global_*`). Inspect with `dimos mem summary recordings/<run-id>/memory.db` (columns Stream/Items/Hz/Start/Duration/Size — a real sample shows global_costmap at 0.4 Hz, 421 KiB for 9 frames). Replay with `dimos --replay --replay-db recordings/<run-id>/memory.db run <blueprint>` (replay needs lidar, odom, color_image). Streams typed Any/dict are not recorded; the Rust engine only handles LCMTransport/ZenohTransport with dimOS LCM payloads.
Message types suitable for logging mine detections: dimos.msgs.geometry_msgs.PointStamped (simplest: one detection = one stamped world point), dimos.msgs.vision_msgs.Detection3DArray / Detection2DArray, dimos.msgs.sensor_msgs.PointCloud2.
Ad-hoc inspection from Python: `app.peek_stream("global_costmap", 1.0)` pulls the next message off any running module's stream.
_source: docs/usage/recording.md (102 lines), docs/usage/python-api.md, repo tree of dimos/msgs/vision_msgs/_

### [verified] Python entry point for scripting the running robot
`from dimos import Dimos`. Local: `app = Dimos(n_workers=8); app.run("unitree-go2-agentic")`. Remote (attach to a running `dimos run ...`): `app = Dimos.connect()`. Then: `app.skills.move_to(x=2.0, relative=True)`; `app.get_module("ReplanningAStarPlanner")` (or an exact instance name like "robot0/camera"); `app.list_modules()`, `app.list_rpcs()`, `app.describe(obj)`; `app.find_module_by_spec(SomeSpec)` matching a `dimos.spec.utils.Spec` Protocol; `app.peek_stream(name, timeout)`; `app.run(ModuleClass)` to add a module; `app.restart(ModuleClass)` to hot-reload; `app.stop()`. Adding or removing In/Out declarations requires a full daemon restart (autoconnect wiring is computed at coordinator build time). `load_blueprint` over LCM has a 120 s RPC timeout.
_source: docs/usage/python-api.md (217 lines)_

### [verified] Navigation state enum and interface
`from dimos.navigation.base import NavigationInterface, NavigationState`. NavigationState is an Enum with IDLE = "idle", FOLLOWING_PATH = "following_path", RECOVERY = "recovery". NavigationInterface is an ABC requiring set_goal(goal: PoseStamped) -> bool, get_state() -> NavigationState, is_goal_reached() -> bool, cancel_goal() -> bool. A Protocol version for Spec injection exists at `dimos.navigation.navigation_spec.NavigationInterfaceSpec(Spec, Protocol)`.
_source: Read of dimos/navigation/base.py and dimos/navigation/navigation_spec.py_

### [verified] Other navigation modules worth knowing
dimos.navigation.frontier_exploration.wavefront_frontier_goal_selector.WavefrontFrontierExplorer — scans the costmap for frontiers, wavefront BFS from robot pose, publishes a nav goal; agent skills begin_exploration / end_exploration.
dimos.navigation.patrolling.module.PatrollingModule — systematic coverage of a KNOWN area; agent skills start_patrol / stop_patrol; routers in dimos/navigation/patrolling/routers/: coverage (default, Voronoi-weighted max new-coverage), random, frontier. Waits for goal_reached before requesting the next goal; filters candidates through a safe mask (free space eroded by robot clearance radius).
dimos.navigation.basic_path_follower.module — simpler follower.
dimos.mapping.occupancy.* — inflation.py, gradient.py, operations.py, path_map.py, path_mask.py, path_resampling.py (smooth_resample_path), visualizations.py, extrude_occupancy.py: reusable grid utilities.
Coverage/patrol is the closest existing analogue to a landmine sweep pattern.
_source: Repo tree + docs/capabilities/navigation/deep_dive.md sections 'Frontier Exploration' and 'Patrolling'_

### [verified] Named blueprints shipped for navigation
unitree_go2 (dimos/robot/unitree/go2/blueprints/smart/unitree_go2.py) = autoconnect(unitree_go2_basic, VoxelGridMapper.blueprint(emit_every=5), CostMapper.blueprint(), ReplanningAStarPlanner.blueprint(), WavefrontFrontierExplorer.blueprint(), PatrollingModule.blueprint(), MovementManager.blueprint()).global_config(n_workers=10, robot_model="unitree_go2").
unitree_go2_mls_htc (dimos/robot/unitree/go2/blueprints/navigation/unitree_go2_mls_htc.py) = autoconnect(vis_module(...), GO2Connection.blueprint(motion_mode="mcf"), VoxelGridMapper.blueprint(voxel_size=0.05, frame_id="world", emit_every=1), MLSPlannerNative.blueprint(...).remappings([(MLSPlannerNative,"path","planner_path")]), DanLocalPlanner.blueprint(resample_spacing_m=0.1), DanHolonomicTC.blueprint(run_profile="walk"), MovementManager.blueprint()).global_config(n_workers=10, robot_model="unitree_go2", obstacle_avoidance=False).
CLI: `dimos --replay run unitree-go2`, `dimos --simulation run unitree-go2-agentic`, `dimos run demo-camera`, `dimos status`, `dimos log -f`, `dimos agent-send "..."`, `dimos mcp list-tools`, `dimos stop`.
_source: Read of both blueprint files and README.md_

## RECOMMENDATIONS
- For deliverable B, target ReplanningAStarPlanner, not DanLocalPlanner/MLSPlannerNative. It is the only shipped planner with an OccupancyGrid input port (`global_costmap: In[OccupancyGrid]`). Write our own dimOS module that declares `global_costmap: Out[OccupancyGrid]` and autoconnect it in place of CostMapper; wiring is automatic because it matches on (property_name='global_costmap', type=OccupancyGrid).
- Emit the Bayesian posterior as a dimOS OccupancyGrid built in code, never loaded blind from disk: `OccupancyGrid(grid=arr_int8, resolution=res_m, origin=Pose(x0, y0, 0.0), frame_id='world', ts=time.time())` where arr_int8 has shape (height, width), dtype int8, row index = y, col index = x, and (x0, y0) is the BOTTOM-LEFT corner in metres in the world frame.
- Map posterior mine probability to the int8 0..100 cost scale explicitly, e.g. `cost = np.clip(np.round(p_mine * 100), 0, 100).astype(np.int8)` and reserve -1 strictly for 'never swept and no prior coverage'. Use CostValues.UNKNOWN / FREE / OCCUPIED from dimos.msgs.nav_msgs.OccupancyGrid rather than magic numbers.
- Anchor the local metric frame yourself. Pick an origin LatLon for the Ukrainian area of operations, project with pyproj (UTM zone 35N/36N/37N covers Ukraine) or a local ENU tangent plane, and keep the grid axis-aligned to that projection. dimOS gives you only LatLon, haversine distance_in_meters (R=6371000 m), and Web-Mercator tile math — no projection. Ship the origin lat/lon + resolution + UTM/EPSG code as sidecar JSON alongside the grid.
- Issue sweep waypoints as `PoseStamped(ts=time.time(), frame_id='world', position=[x, y, 0.0], orientation=Quaternion.from_euler(Vector3(0, 0, yaw)))` published on the `goal_request` topic, or by calling the RPC `set_goal(...)` on the ReplanningAStarPlanner proxy obtained from `Dimos.connect().get_module('ReplanningAStarPlanner')`. Subscribe `goal_reached: Out[Bool]` (dimos_lcm.std_msgs.Bool, read `.data`) before sending the next waypoint.
- If you want to emit a full boustrophedon sweep trajectory rather than one goal at a time, build a `dimos.msgs.nav_msgs.Path.Path(ts=..., frame_id='world', poses=[PoseStamped, ...])` and feed DanHolonomicTC's `path: In[Path]` directly — it needs no map, only `odom: In[PoseStamped]`. An empty Path is the stop signal.
- Log detections as `PointStamped(x, y, z, ts=time.time(), frame_id='world')` on a dedicated Out stream, and capture the run with `dimos --record --record-topics 'mine_detection,global_costmap,odom,tf' run <blueprint>`; inspect with `dimos mem summary recordings/<run-id>/memory.db`. That SQLite artifact is the natural posterior-update log feeding back into the Bayesian model.
- Keep the robot-facing posterior grid small. OccupancyGrid.lcm_encode() calls `self.grid.flatten().tolist()`, converting every cell to a Python int on each publish. Stay at or below roughly 512x512 cells per published grid (e.g. 0.5 m resolution over a 256 m square), publish at well under 1 Hz, and use `block_max_reduce(cells, factor)` from the same module to coarsen larger district-scale grids without erasing obstacles.
- Build all HTML geography at build time and inline it. dimOS's OSM helper (`get_osm_map`) fetches tiles from tile.openstreetmap.org at runtime and must never be used from the artifact; if you want basemap imagery, download it during the build and embed it as a data: URI.
- Develop and run the dimOS side on Linux (or macOS). The install script targets Ubuntu 22.04/24.04, NixOS and macOS, and the dependency set (lcm-dimos-fork, pinocchio, open3d, drake, mujoco) is not Windows-friendly. Do the ZIP/GED processing and HTML build on Windows, but ship deliverable B as a plain Python module plus a .npy + JSON sidecar that runs inside a Linux dimOS environment.

## PITFALLS
- Copying the README's `from dimos.msgs.geometry_msgs import Twist` form. There are no __init__.py files in the repo, so that binds the submodule, not the class. Always use the full path: `from dimos.msgs.geometry_msgs.Twist import Twist`.
- Looking for MapMetaData under dimos.msgs. It has no dimOS wrapper — it is `from dimos_lcm.nav_msgs import MapMetaData`, from the separate `dimos-lcm` distribution. Never hand-roll a MapMetaData class.
- Using dimos.msgs.std_msgs.Bool for the planner's stop_movement / goal_reached ports. Those modules import `from dimos_lcm.std_msgs import Bool, String`. Publishing the wrong Bool type breaks autoconnect's (name, type) matching silently.
- Assuming DanLocalPlanner does SE(2) search over a raycaster local map. It does not — it is a replan commit-gate plus path smoother with no map input at all. The real search planner is MLSPlannerNative, and it consumes a voxel PointCloud2, not an OccupancyGrid. Wiring a costmap to either of them will simply never connect.
- Round-tripping a grid through OccupancyGrid.from_path(). The .png branch does `np.array(img.convert('L')).astype(np.int8)`, so any pixel above 127 wraps to a negative int8 and silently becomes 'unknown' or garbage. Both the .npy and .png branches also discard metadata: resolution falls back to 0.05 m and origin to Pose() at (0,0,0), so a grid reloaded this way is mis-scaled and mis-georeferenced.
- Treating the origin Pose's rotation as meaningful. world_to_grid and grid_to_world are explicitly commented 'simplified, assuming no rotation' and ignore the quaternion entirely. Keep the origin orientation identity and the grid axis-aligned with the projected metric frame.
- Transposing the grid. It is [row=y, col=x] — shape is (height, width) — and origin is the bottom-left corner, not top-left. to_rerun() flips rows (`self.grid[::-1]`) precisely because of this.
- Assuming MapMetaData.resolution is float64. On the wire it is packed as '>fii' (float32 resolution, int32 width, int32 height), so a resolution like 0.1 will not survive a round-trip exactly. Never compare resolutions with ==.
- Forgetting to wrap `In.subscribe()` in a Disposable. It returns a plain unsubscribe *function*, not a DisposableBase; `self.register_disposable(Disposable(self.x.subscribe(cb)))` is required or the handler keeps running after stop() and the thread-leak detector fails the test session.
- Adding or renaming In/Out ports and expecting `app.restart(Module)` to pick it up. Autoconnect wiring is computed at coordinator build time, so stream-signature changes need a full `dimos stop` + `dimos run`.
- Publishing a district-scale heatmap (thousands of cells per side) straight onto the LCM topic. lcm_encode converts every cell to a Python int via .tolist(); a 2000x2000 grid is 4 million Python objects per message and will stall the transport.
- Letting -1 leak into the posterior as 'probably safe'. -1 is UNKNOWN in the ROS/dimOS convention, and the planner treats unknown very differently from 0 (free). A never-surveyed district with a high war-based prior must be encoded as a high cost value, not as -1.
- Expecting dimOS to convert GPS goals into planner goals. GpsNavSkillContainer only publishes LatLon out on `gps_goal` (and enforces a 50 km sanity limit); nothing in the repo turns a LatLon into a metric PoseStamped. That bridge is ours to write.