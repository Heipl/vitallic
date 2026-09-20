"""DimensionalOS adapter.

Publishes the Bayesian posterior as a nav_msgs/OccupancyGrid on the
`global_costmap` topic and sweep waypoints as a nav_msgs/Path, and folds robot
detections back into the posterior.

WIRING.  ReplanningAStarPlanner is the only shipped planner with an
OccupancyGrid input port (`global_costmap: In[OccupancyGrid]`), so this module
stands in for CostMapper.  autoconnect matches on (property_name, message_type),
so declaring `global_costmap: Out[OccupancyGrid]` connects automatically.
DanLocalPlanner is NOT an SE(2) search planner -- it is a replan commit-gate and
path smoother with no map input at all -- and MLSPlannerNative searches a voxel
PointCloud2, so wiring a costmap to either would simply never connect.

IMPORTS.  dimOS has no __init__.py files, so every import is a full module path.
`from dimos.msgs.geometry_msgs import Twist` (as the README shows) binds the
submodule, not the class.  MapMetaData has no dimOS wrapper at all and comes
from the separate dimos-lcm distribution.

This module is import-guarded: mineprior's maths has no dimOS dependency and
runs anywhere, which matters because dimOS targets Linux/macOS while the model
build runs on Windows.
"""
from __future__ import annotations

import time

import numpy as np

from .field import PosteriorField
from .sweeplog import Sweep, SweepLog

try:  # pragma: no cover - exercised only inside a dimOS environment
    from reactivex.disposable import Disposable

    from dimos.core.core import rpc
    from dimos.core.module import Module, ModuleConfig
    from dimos.core.stream import In, Out
    from dimos.msgs.geometry_msgs.Point import Point
    from dimos.msgs.geometry_msgs.Pose import Pose
    from dimos.msgs.geometry_msgs.PointStamped import PointStamped
    from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
    from dimos.msgs.nav_msgs.OccupancyGrid import CostValues, OccupancyGrid
    from dimos.msgs.nav_msgs.Path import Path as NavPath

    DIMOS_AVAILABLE = True
except ImportError:  # pragma: no cover
    DIMOS_AVAILABLE = False


def build_occupancy_grid(fieldobj: PosteriorField, *, frame_id: str = "world"):
    """PosteriorField -> nav_msgs/OccupancyGrid.

    Built in code, never loaded blind from disk: OccupancyGrid.from_path()
    discards resolution and origin (falling back to 0.05 m at (0,0,0)) and its
    .png branch wraps any pixel above 127 to a negative int8.

    grid is [row=y, col=x] with shape (height, width) and the origin Pose at the
    BOTTOM-LEFT corner. The origin's quaternion is ignored by dimOS's
    world_to_grid/grid_to_world helpers, so the grid stays axis-aligned and the
    orientation stays identity.
    """
    if not DIMOS_AVAILABLE:
        raise RuntimeError("dimos is not installed in this environment")
    cost = fieldobj.cost_grid_int8()
    return OccupancyGrid(
        grid=np.ascontiguousarray(cost, dtype=np.int8),
        width=fieldobj.grid.width,
        height=fieldobj.grid.height,
        resolution=fieldobj.grid.res,
        origin=Pose(float(fieldobj.grid.x0), float(fieldobj.grid.y0), 0.0),
        frame_id=frame_id,
        ts=time.time(),
    )


def build_path(waypoints, *, frame_id: str = "world"):
    """Waypoints from mission.plan_route -> nav_msgs/Path.

    Feed this straight to DanHolonomicTC's `path: In[Path]`, which needs no map,
    only odom. An empty Path is the stop signal.
    """
    if not DIMOS_AVAILABLE:
        raise RuntimeError("dimos is not installed in this environment")
    poses = [PoseStamped(ts=time.time(), frame_id=frame_id,
                         position=[w["x_m"], w["y_m"], 0.0])
             for w in waypoints]
    return NavPath(ts=time.time(), frame_id=frame_id, poses=poses)


MAX_PUBLISHED_CELLS = 512 * 512
"""OccupancyGrid.lcm_encode() calls grid.flatten().tolist(), turning every cell
into a Python int on each publish. A 2000x2000 grid is 4 million objects per
message and will stall the transport. Coarsen larger grids with
block_max_reduce (max, not mean -- averaging erases lethal cells)."""


if DIMOS_AVAILABLE:  # pragma: no cover

    class MinePosteriorConfig(ModuleConfig):
        posterior_npz: str = ""
        sidecar_json: str = ""
        sweep_log: str = "sweeps.jsonl"
        publish_hz: float = 0.2
        sensitivity: float = 0.85
        sweep_footprint_m2: float = 1.0
        false_alarm_rate_per_km2: float = 4000.0

    class MinePosterior(Module):
        """Serves the landmine posterior as a costmap and ingests detections.

        Ports:
          detection: In[PointStamped]   -- one stamped world point per sensor hit
          odom:      In[PoseStamped]    -- robot pose, used to accrue swept area
          global_costmap: Out[OccupancyGrid] -- consumed by ReplanningAStarPlanner
        """
        config: MinePosteriorConfig
        detection: In[PointStamped]
        odom: In[PoseStamped]
        global_costmap: Out[OccupancyGrid]

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._field: PosteriorField | None = None
            self._log: SweepLog | None = None
            self._last_cell = None
            self._last_publish = 0.0

        @rpc
        def start(self) -> None:
            super().start()
            self._field = load_field(self.config.posterior_npz, self.config.sidecar_json)
            if self._field.grid.n_cells > MAX_PUBLISHED_CELLS:
                raise ValueError(
                    f"grid has {self._field.grid.n_cells:,} cells; coarsen it below "
                    f"{MAX_PUBLISHED_CELLS:,} before publishing over LCM")
            self._log = SweepLog(self.config.sweep_log)
            # subscribe() returns a plain unsubscribe function, not a
            # DisposableBase, so it must be wrapped or the handler outlives stop().
            self.register_disposable(Disposable(self.detection.subscribe(self._on_detection)))
            self.register_disposable(Disposable(self.odom.subscribe(self._on_odom)))
            self._publish()

        @rpc
        def stop(self) -> None:
            super().stop()

        def _cell_of(self, x: float, y: float):
            cx, cy = self._field.grid.index_of(x, y)
            cx, cy = int(cx), int(cy)
            if not self._field.grid.in_bounds(cx, cy):
                return None
            return cx, cy

        def _on_odom(self, msg) -> None:
            """Accrue swept area as the robot moves, logging NULL sweeps too --
            they are the majority of the evidence and the only unbiased signal."""
            cell = self._cell_of(msg.x, msg.y)
            if cell is None or cell == self._last_cell:
                return
            self._last_cell = cell
            cx, cy = cell
            self._field.observe(cx, cy, swept_m2=self.config.sweep_footprint_m2,
                                sensitivity=self.config.sensitivity, alarms=0)
            self._log.append(Sweep(cell_x=cx, cell_y=cy,
                                   swept_m2=self.config.sweep_footprint_m2,
                                   sensitivity=self.config.sensitivity))
            self._maybe_publish()

        def _on_detection(self, msg) -> None:
            """A detection is a SENSOR ANOMALY, not a confirmed mine. It updates
            belief through the false-positive-aware likelihood, and is never
            promoted to a registered hazard without operator adjudication."""
            cell = self._cell_of(msg.x, msg.y)
            if cell is None:
                return
            cx, cy = cell
            self._field.observe(
                cx, cy, swept_m2=self.config.sweep_footprint_m2,
                sensitivity=self.config.sensitivity, alarms=1,
                false_alarm_rate_per_km2=self.config.false_alarm_rate_per_km2)
            self._log.append(Sweep(
                cell_x=cx, cell_y=cy, swept_m2=self.config.sweep_footprint_m2,
                sensitivity=self.config.sensitivity, alarms=1,
                false_alarm_rate_per_km2=self.config.false_alarm_rate_per_km2))
            self._publish()

        def _maybe_publish(self) -> None:
            if time.time() - self._last_publish >= 1.0 / max(self.config.publish_hz, 1e-6):
                self._publish()

        def _publish(self) -> None:
            self.global_costmap.publish(build_occupancy_grid(self._field))
            self._last_publish = time.time()


def load_field(npz_path: str, sidecar_path: str) -> PosteriorField:
    """Rebuild a PosteriorField from the files written by field.save()."""
    import json
    from pathlib import Path

    from .geo import ENU, Grid

    d = np.load(npz_path)
    meta = json.loads(Path(sidecar_path).read_text(encoding="utf-8"))
    grid = Grid(x0=meta["origin_x_m"], y0=meta["origin_y_m"], res=meta["resolution_m"],
                width=meta["width"], height=meta["height"])
    return PosteriorField(
        grid=grid, enu=ENU(meta["origin_lat"], meta["origin_lon"]),
        alpha=d["alpha"].astype(np.float64), beta=d["beta"].astype(np.float64),
        Y=d["Y"].astype(np.float64), T=d["T"].astype(np.float64),
        swept_area=d["swept_area"].astype(np.float64),
        cell_area_m2=meta["cell_area_m2"],
        prior_is_flat=meta.get("prior_is_flat_below_5km", True),
        prior_source=meta.get("prior_source", ""),
        corr_length_m=meta.get("corr_length_m", 60.0),
        leak=meta.get("leak", 0.35))
