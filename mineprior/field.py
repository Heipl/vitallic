"""The stateful posterior field the robot reads and updates.

A PosteriorField is a projected grid carrying, per cell, the Gamma posterior
(alpha, beta) plus the audit statistics (Y, T) that produced it.  Everything the
planner needs is O(1) from (alpha, beta); (Y, T) are kept so the field can be
rebuilt from the sweep log and so evaluation can be redone later.

THE FLAT-PRIOR RULE
-------------------
The GED prior has no information below ~5 km: Ukraine's occupied-cell count
saturates at 2,234 cells (0.025 deg) -> 2,346 (0.01 deg), because 31,547 events
sit on only ~2,440 distinct coordinates, and the median nearest-neighbour
spacing between distinct coded locations is 3.58 km.

So when a fine robot grid is seeded from the national prior, every cell inside
one 5 km parent gets the SAME density.  Interpolating the prior down to metre
scale would manufacture smooth, confident-looking gradients that are pure
interpolation artefact.  All sub-5 km structure in this field comes from robot
sweeps, and `prior_is_flat` records that fact for anything downstream.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field as dc_field
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d

from . import model as M
from .geo import ENU, Grid


@dataclass
class PosteriorField:
    grid: Grid
    enu: ENU
    alpha: np.ndarray
    beta: np.ndarray
    Y: np.ndarray                      # cumulative confirmed detections
    T: np.ndarray                      # cumulative effective exposure
    swept_area: np.ndarray             # cumulative swept area, m^2 (audit/display)
    cell_area_m2: float
    prior_is_flat: bool = True
    prior_source: str = ""
    corr_length_m: float = 60.0
    leak: float = 0.35
    meta: dict = dc_field(default_factory=dict)

    # -- construction --------------------------------------------------------

    @classmethod
    def from_density(cls, grid: Grid, enu: ENU, density_per_km2, *,
                     prior_source: str = "", prior_is_flat: bool = True,
                     psi: float = M.PSI, alpha_floor: float = M.ALPHA_FLOOR):
        """Seed from a mines/km^2 density field (scalar or array)."""
        cell_area_m2 = grid.cell_area           # grid.res is in metres here
        cell_area_km2 = cell_area_m2 / 1e6
        m = np.broadcast_to(np.asarray(density_per_km2, dtype=np.float64),
                            grid.shape) * cell_area_km2
        alpha, beta = M.prior_from_mean(m, psi=psi, alpha_floor=alpha_floor)
        z = np.zeros(grid.shape)
        return cls(grid=grid, enu=enu, alpha=np.array(alpha), beta=np.array(beta),
                   Y=z.copy(), T=z.copy(), swept_area=z.copy(),
                   cell_area_m2=cell_area_m2, prior_is_flat=prior_is_flat,
                   prior_source=prior_source)

    # -- readouts ------------------------------------------------------------

    @property
    def mean(self):
        return M.mean(self.alpha, self.beta)

    @property
    def sd(self):
        return M.sd(self.alpha, self.beta)

    @property
    def p_any(self):
        """P(at least one mine present). The right field for risk-averse routing
        -- a planner should key on this, not on the expected count."""
        return M.p_any(self.alpha, self.beta)

    @property
    def density_per_km2(self):
        return self.mean / (self.cell_area_m2 / 1e6)

    @property
    def coverage_fraction(self):
        """Swept area as a fraction of cell area. Deterministic, moves visibly
        with every pass, and is honest -- unlike the risk posterior, which
        correctly barely moves."""
        return np.clip(self.swept_area / self.cell_area_m2, 0.0, 1.0)

    # -- updates -------------------------------------------------------------

    def observe(self, cx: int, cy: int, *, swept_m2: float, sensitivity: float,
                alarms: int = 0, confirmed: int = 0, false_alarm_rate_per_km2: float = 0.0,
                spread: bool = True):
        """Fold one sweep of cell (cx, cy) into the posterior.

        `alarms` are raw sensor anomalies (subject to false positives);
        `confirmed` are adjudicated mines.  The confirmed stream is always
        preferred and is exactly conjugate.
        """
        if not (0 <= cx < self.grid.width and 0 <= cy < self.grid.height):
            raise IndexError(f"cell ({cx}, {cy}) outside the field")

        c = min(swept_m2 / self.cell_area_m2, 1.0)
        t = float(M.effective_exposure(c, sensitivity))
        self.swept_area[cy, cx] += swept_m2

        if confirmed:
            a, b = M.update_confirmed(self.alpha[cy, cx], self.beta[cy, cx], t, confirmed)
            self.Y[cy, cx] += confirmed
        elif alarms:
            f = false_alarm_rate_per_km2 * (c * self.cell_area_m2) / 1e6
            a, b = M.update_alarms(float(self.alpha[cy, cx]), float(self.beta[cy, cx]),
                                   t=t, a=int(alarms), f=f)
        else:
            a, b = M.update_null(self.alpha[cy, cx], self.beta[cy, cx], t)
        self.alpha[cy, cx], self.beta[cy, cx] = a, b
        self.T[cy, cx] += t

        if spread and confirmed:
            # Only CONFIRMED evidence is spread, and only outward.
            #
            # Spreading a confirmed mine is conservative and defensible:
            # minefields are contiguous belts, so a real mine at x genuinely
            # raises P(mine) at x + a few metres.
            #
            # Raw alarms are NOT spread. At a realistic false-alarm rate most
            # alarms are scrap metal, so spreading them paints risk onto
            # neighbours on the strength of clutter.
            #
            # Clean sweeps are never spread either. Lowering risk in cells the
            # robot did not visit is the dangerous direction of error.
            self._spread_positive(cx, cy, confirmed)

    def _spread_positive(self, cx: int, cy: int, y: float):
        """Column-stochastic evidence spreading of a detection.

        Mass is conserved: the leaked share is redistributed over neighbours and
        removed from the origin cell, so sum(y_spread) == leak * y exactly.

        This is NOT conjugate Bayes. It is exact only where lambda is constant
        over the kernel's support; elsewhere it biases the mean by
        (leak * sigma_c^2 / 2) * Laplacian(lambda) and smears minefield edges by
        about sigma_c. Keep sigma_c no larger than the smallest feature that
        must stay resolvable.
        """
        s_cells = self.corr_length_m / self.grid.res
        rad = int(np.ceil(3.0 * s_cells))
        if rad < 1:
            return
        x0, x1 = max(0, cx - rad), min(self.grid.width, cx + rad + 1)
        y0, y1 = max(0, cy - rad), min(self.grid.height, cy + rad + 1)

        stamp = np.zeros((y1 - y0, x1 - x0))
        stamp[cy - y0, cx - x0] = 1.0
        stamp = gaussian_filter1d(stamp, s_cells, axis=0, mode="constant")
        stamp = gaussian_filter1d(stamp, s_cells, axis=1, mode="constant")
        tot = stamp.sum()
        if tot <= 0:
            return
        stamp /= tot                       # column of S: sums to 1 over destinations

        add = self.leak * y * stamp
        add[cy - y0, cx - x0] -= self.leak * y   # origin already counted in full
        self.alpha[y0:y1, x0:x1] += add
        self.Y[y0:y1, x0:x1] += add

    # -- export --------------------------------------------------------------

    def cost_grid_int8(self, *, mode: str = "p_any") -> np.ndarray:
        """int8 grid on the ROS/dimOS 0..100 cost scale.

        -1 (UNKNOWN) is reserved strictly for cells outside the modelled domain.
        A never-surveyed cell with a high war-based prior must be a HIGH COST,
        not unknown: the planner treats unknown very differently from free, and
        letting -1 stand in for "probably fine" would invert the safety logic.
        """
        v = self.p_any if mode == "p_any" else (
            self.mean / max(float(np.max(self.mean)), 1e-12))
        return np.clip(np.round(v * 100.0), 0, 100).astype(np.int8)

    def to_sidecar(self) -> dict:
        """Georeferencing and provenance that must travel with the grid.

        dimOS OccupancyGrid.from_path() discards resolution and origin, so a
        grid reloaded that way is mis-scaled and mis-georeferenced. Always
        rebuild from this sidecar rather than from the .npy alone.
        """
        return {
            "frame_id": "world",
            "origin_lat": self.enu.lat0,
            "origin_lon": self.enu.lon0,
            "origin_x_m": self.grid.x0,
            "origin_y_m": self.grid.y0,
            "resolution_m": self.grid.res,
            "width": self.grid.width,
            "height": self.grid.height,
            "cell_area_m2": self.cell_area_m2,
            "projection": "local ENU tangent plane anchored at (origin_lat, origin_lon)",
            "grid_order": "row = y (north), col = x (east); origin is the BOTTOM-LEFT corner",
            "cost_scale": "0..100 = P(at least one mine present) x 100; -1 = outside modelled domain",
            "prior_is_flat_below_5km": self.prior_is_flat,
            "prior_source": self.prior_source,
            "corr_length_m": self.corr_length_m,
            "leak": self.leak,
            "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "WARNING": ("MODEL OUTPUT - NOT A CLEARANCE RECORD. No cell in this grid has "
                        "been declared free of explosive ordnance. This is non-technical "
                        "survey support information only."),
            **self.meta,
        }

    def save(self, directory, stem: str = "posterior"):
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            d / f"{stem}.npz",
            alpha=self.alpha.astype(np.float32), beta=self.beta.astype(np.float32),
            Y=self.Y.astype(np.float32), T=self.T.astype(np.float32),
            swept_area=self.swept_area.astype(np.float32),
        )
        np.save(d / f"{stem}_cost.npy", self.cost_grid_int8())
        (d / f"{stem}.json").write_text(
            json.dumps(self.to_sidecar(), indent=1), encoding="utf-8")
        return d / f"{stem}.npz"
