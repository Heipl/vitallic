"""Turning the posterior into a robot trajectory.

The acquisition score balances what the mission is for (find mines), what the
model needs (reduce variance), and what the battery allows (travel).  Pure
information gain sends the robot to the most uncertain cell, which is not the
same as the most useful one.

THE EXPLORATION ARM IS NOT OPTIONAL.  If every sweep is chosen by the score,
the robot only ever visits cells the model already calls risky, so the model can
never be shown to be wrong: "we predicted high risk, went there, found mines" is
unfalsifiable when low-risk cells are never sampled.  A fixed fraction of sweeps
is therefore drawn at random across the risk deciles, and the selection
propensity is recorded so the data can be analysed by inverse-propensity
weighting afterwards.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import model as M


@dataclass
class Weights:
    find: float = 1.0       # expected mines found -- direct mission value
    info: float = 0.6       # variance reduction
    cost: float = 0.8       # travel time
    risk: float = 0.4       # civilian exposure x P(mine present)


def score(fieldobj, *, robot_xy, coverage: float, sensitivity: float,
          weights: Weights = Weights(), civilian_weight=None, mask=None):
    """Acquisition score per cell. Higher is a better next target."""
    t = float(M.effective_exposure(coverage, sensitivity))
    a, b = fieldobj.alpha, fieldobj.beta

    expected_find = a * t / b
    info = M.voi(a, b, t)
    risk = M.p_any(a, b)
    if civilian_weight is not None:
        risk = risk * civilian_weight

    xs, ys = fieldobj.grid.centre_mesh()
    travel = np.hypot(xs - robot_xy[0], ys - robot_xy[1])

    # Normalise each term by its own median so the weights stay dimensionless.
    def norm(v):
        med = float(np.median(v[v > 0])) if np.any(v > 0) else 1.0
        return v / max(med, 1e-12)

    s = (weights.find * norm(expected_find)
         + weights.info * norm(info)
         - weights.cost * norm(travel)
         + weights.risk * norm(risk))
    if mask is not None:
        s = np.where(mask, s, -np.inf)
    return s


def select_next(fieldobj, *, robot_xy, coverage, sensitivity, rng,
                explore_fraction: float = 0.15, weights: Weights = Weights(),
                civilian_weight=None, mask=None):
    """Pick the next cell. Returns (cx, cy, propensity, is_exploration).

    With probability `explore_fraction` the cell is drawn uniformly from a
    risk-decile-stratified sample, which gives low-risk cells a non-zero chance
    of being visited. That is the only source of data that can falsify the model.
    """
    s = score(fieldobj, robot_xy=robot_xy, coverage=coverage,
              sensitivity=sensitivity, weights=weights,
              civilian_weight=civilian_weight, mask=mask)
    valid = np.isfinite(s)
    n_valid = int(valid.sum())
    if n_valid == 0:
        raise ValueError("no candidate cells")

    if rng.random() < explore_fraction:
        # Stratify by risk decile so low-risk cells are genuinely reachable.
        risk = np.where(valid, M.p_any(fieldobj.alpha, fieldobj.beta), np.nan)
        finite = risk[valid]
        edges = np.nanquantile(finite, np.linspace(0, 1, 11))
        decile = int(rng.integers(0, 10))
        lo, hi = edges[decile], edges[decile + 1]
        band = valid & (risk >= lo) & (risk <= hi)
        if not band.any():
            band = valid
        idx = np.flatnonzero(band.ravel())
        pick = int(rng.choice(idx))
        # P(select this cell) = P(explore) * P(this decile) * P(cell | decile)
        prop = explore_fraction * 0.1 / max(len(idx), 1)
        cy, cx = np.unravel_index(pick, s.shape)
        return int(cx), int(cy), float(prop), True

    pick = int(np.argmax(np.where(valid, s, -np.inf)))
    cy, cx = np.unravel_index(pick, s.shape)
    ties = int(np.sum(s == s.ravel()[pick]))
    return int(cx), int(cy), float((1.0 - explore_fraction) / ties), False


def boustrophedon(grid, *, cx0, cy0, cx1, cy1, lane_step: int = 1):
    """Lawnmower waypoints over a cell-index box, in projected metres.

    Serpentine rather than raster so the robot does not deadhead back across the
    lane it just finished.
    """
    pts = []
    rows = range(cy0, cy1 + 1, lane_step)
    for k, cy in enumerate(rows):
        cols = range(cx0, cx1 + 1) if k % 2 == 0 else range(cx1, cx0 - 1, -1)
        cols = list(cols)
        for cx in (cols[0], cols[-1]) if len(cols) > 1 else cols:
            pts.append((grid.x0 + (cx + 0.5) * grid.res,
                        grid.y0 + (cy + 0.5) * grid.res))
    return pts


def plan_route(fieldobj, *, robot_xy, n_waypoints, coverage, sensitivity, rng,
               explore_fraction: float = 0.15, weights: Weights = Weights(),
               civilian_weight=None, mask=None):
    """Greedy sequential plan.

    For the pure-information objective this is within (1 - 1/e) of optimal,
    because VOI = Var * t/(beta+t) decreases monotonically in beta, making the
    objective submodular. Adding the travel term turns it into an orienteering
    problem and forfeits that guarantee -- greedy is still used, but the bound
    no longer holds, and a 2-opt pass over the chosen cells would shorten the
    tour.
    """
    # Plan against a scratch copy so planning never mutates real belief.
    alpha0, beta0 = fieldobj.alpha.copy(), fieldobj.beta.copy()
    t = float(M.effective_exposure(coverage, sensitivity))
    xy = tuple(robot_xy)
    plan = []
    try:
        for _ in range(n_waypoints):
            cx, cy, prop, expl = select_next(
                fieldobj, robot_xy=xy, coverage=coverage, sensitivity=sensitivity,
                rng=rng, explore_fraction=explore_fraction, weights=weights,
                civilian_weight=civilian_weight, mask=mask)
            x = fieldobj.grid.x0 + (cx + 0.5) * fieldobj.grid.res
            y = fieldobj.grid.y0 + (cy + 0.5) * fieldobj.grid.res
            lat, lon = fieldobj.enu.inverse(x, y)
            plan.append({
                "cell_x": cx, "cell_y": cy, "x_m": float(x), "y_m": float(y),
                "lat": float(lat), "lon": float(lon),
                "propensity": prop, "exploration": expl,
                "expected_find": float(fieldobj.alpha[cy, cx] * t / fieldobj.beta[cy, cx]),
                "p_any": float(M.p_any(fieldobj.alpha[cy, cx], fieldobj.beta[cy, cx])),
            })
            # Assume a null result so the next pick does not re-target this cell.
            fieldobj.alpha[cy, cx], fieldobj.beta[cy, cx] = M.update_null(
                fieldobj.alpha[cy, cx], fieldobj.beta[cy, cx], t)
            xy = (x, y)
    finally:
        fieldobj.alpha, fieldobj.beta = alpha0, beta0
    return plan
