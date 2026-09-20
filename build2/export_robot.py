"""Build the robot-facing posterior for one area of operations, run a simulated
mission against it, and export the DimOS artifacts.

The simulated ground truth here is SYNTHETIC and is used only to exercise the
update path. Its detections are logged with Provenance.SYNTHETIC and are
therefore rejected by export_registered(), which is the behaviour being tested:
no synthetic record may ever reach an operational export or be drawn as a
confirmed hazard.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mineprior import mission, model as M
from mineprior.field import PosteriorField
from mineprior.geo import ENU, Grid, UKRAINE_LAEA
from mineprior.sweeplog import (Detection, Provenance, ProvenanceError, Sweep,
                                SweepLog, export_registered)

DATA = Path(r"C:\Users\rinoa\landmine-bayes\data")
OUT = Path(r"C:\Users\rinoa\landmine-bayes\dist\robot")
OUT.mkdir(parents=True, exist_ok=True)

AO_SIZE_M = 200.0
AO_RES_M = 2.0
"""A 200 m square at 2 m cells. Deliberately small: at 10,000 m^2/day -- an
optimistic UGV rate -- sweeping the whole of Ukraine would take 165,000
robot-years, so an AO the robot can actually make progress on is a single plot,
not a district."""

SENSITIVITY = 0.85
FALSE_ALARM_PER_KM2 = 4000.0
"""~4 false alarms per 1,000 m^2 for metal-detector-class sensors in
scrap-littered post-conflict soil. Highly site-dependent; estimate it on a known
clean calibration lane and update it per soil class."""

SWEEP_FOOTPRINT_M2 = 4.0       # one full cell per logged pass
N_WAYPOINTS = 3000

BELT_DENSITY_PER_KM2 = 6000.0
"""Synthetic belt core density, ~60 mines/hectare -- the Cambodian K5 'Bamboo
Curtain' rate (3,000 mines per linear km over a 500 m swath), about 10x a
generic confirmed minefield. Used only to give the simulated sensor something
to find."""


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------------------
# Pick the AO from the national prior
# ---------------------------------------------------------------------------

g = np.load(DATA / "out" / "ukraine_grid.npz")
alpha_n, beta_n, land = g["alpha"], g["beta"], g["land"]
nat = Grid(x0=float(g["x0"]), y0=float(g["y0"]), res=float(g["res"]),
           width=int(g["width"]), height=int(g["height"]))
mean_n = np.where(land, M.mean(np.maximum(alpha_n, 1e-9), np.maximum(beta_n, 1e-9)), 0.0)

cy, cx = np.unravel_index(int(np.argmax(mean_n)), mean_n.shape)
x_c = nat.x0 + (cx + 0.5) * nat.res
y_c = nat.y0 + (cy + 0.5) * nat.res
lat0, lon0 = UKRAINE_LAEA.inverse(x_c, y_c)
lat0, lon0 = float(lat0), float(lon0)

parent_mean = float(mean_n[cy, cx])
parent_density = parent_mean / (nat.res ** 2)       # mines per km^2
log(f"AO anchored on the highest-prior 5 km cell: {lat0:.4f} N, {lon0:.4f} E")
log(f"  parent cell: {parent_mean:.1f} mines over {nat.res**2:.0f} km^2 "
    f"= {parent_density:.2f} mines/km^2")

# ---------------------------------------------------------------------------
# Fine AO grid, seeded FLAT from the parent cell
# ---------------------------------------------------------------------------

enu = ENU(lat0, lon0)
half = AO_SIZE_M / 2.0
ao = Grid(x0=-half, y0=-half, res=AO_RES_M,
          width=int(AO_SIZE_M / AO_RES_M), height=int(AO_SIZE_M / AO_RES_M))

fld = PosteriorField.from_density(
    ao, enu, parent_density,
    prior_source=("UCDP GED v25.1 national 5 km prior, cell "
                  f"({cx},{cy}); FLAT within the parent cell"),
    prior_is_flat=True)
fld.meta["ao_size_m"] = AO_SIZE_M
fld.corr_length_m = 8.0
"""Evidence-spreading length, set from mine-laying doctrine: row spacing inside
a patterned belt is metres, so a confirmed mine raises belief over a handful of
cells, not across the plot. The default 60 m suits a belt-width-scale grid; on
this 2 m grid it would be 30 cells and would smear every detection over a third
of the AO. Bandwidth must come from doctrine, never from tuning until the
heatmap looks lively."""
log(f"  AO grid {ao.width} x {ao.height} @ {AO_RES_M} m = {ao.n_cells:,} cells "
    f"({ao.cell_area:.0f} m^2 each)")
log(f"  seeded flat at {parent_density:.2f} mines/km^2 "
    f"=> prior mean {float(fld.mean.mean()):.2e} mines/cell, "
    f"P(any) {float(fld.p_any.mean()):.4f}")

prior_mean_total = float(fld.mean.sum())
prior_p_any = fld.p_any.copy()

# ---------------------------------------------------------------------------
# Synthetic ground truth -- a belt, because minefields are laid in belts
# ---------------------------------------------------------------------------

rng = np.random.default_rng(20260919)
xs, ys = ao.centre_mesh()
belt = np.exp(-((ys - 0.35 * xs) ** 2) / (2 * 22.0 ** 2))
truth_density = BELT_DENSITY_PER_KM2 * belt       # mines/km^2 in the belt core
truth_lambda = truth_density * (ao.cell_area / 1e6)
truth = rng.poisson(truth_lambda)
log(f"\nsynthetic ground truth: {int(truth.sum()):,} mines in a belt "
    f"({int((truth > 0).sum()):,} occupied cells of {ao.n_cells:,})")

# ---------------------------------------------------------------------------
# Run the mission
# ---------------------------------------------------------------------------

logpath = OUT / "sweeps.jsonl"
if logpath.exists():
    logpath.unlink()
swlog = SweepLog(logpath)

coverage = SWEEP_FOOTPRINT_M2 / ao.cell_area
log(f"\nrunning {N_WAYPOINTS} sweeps at {SWEEP_FOOTPRINT_M2:.0f} m^2 each "
    f"(coverage {coverage:.1%} of a cell per pass)")

robot_xy = (0.0, 0.0)
remaining = truth.copy()
detections, n_explore, n_alarm, n_conf = [], 0, 0, 0
hit_cells, swept_cells = set(), set()
for step in range(N_WAYPOINTS):
    # A fully swept cell is not a candidate again. Without this the travel term
    # is zero exactly where the robot already stands, so the greedy arm re-picks
    # its current cell forever and only the exploration arm ever moves.
    free = fld.coverage_fraction < 0.999
    if not free.any():
        log(f"  AO fully swept after {step} sweeps")
        break
    cx_a, cy_a, prop, expl = mission.select_next(
        fld, robot_xy=robot_xy, coverage=coverage, sensitivity=SENSITIVITY,
        rng=rng, explore_fraction=0.15, mask=free)
    n_explore += expl

    # Simulate the sensor against the mines STILL PRESENT: a confirmed mine is
    # excavated and removed, so it cannot be found again on a later pass.
    n_true = int(remaining[cy_a, cx_a])
    seen = rng.binomial(n_true, min(coverage * SENSITIVITY, 1.0))
    f_exp = FALSE_ALARM_PER_KM2 * (SWEEP_FOOTPRINT_M2 / 1e6)
    clutter = rng.poisson(f_exp)
    alarms = int(seen + clutter)

    # Adjudication: an operator confirms a share of alarms by excavation.
    confirmed = int(rng.binomial(seen, 0.6)) if seen else 0
    remaining[cy_a, cx_a] -= confirmed
    n_alarm += alarms
    n_conf += confirmed
    if confirmed:
        hit_cells.add((cy_a, cx_a))
    swept_cells.add((cy_a, cx_a))

    fld.observe(cx_a, cy_a, swept_m2=SWEEP_FOOTPRINT_M2, sensitivity=SENSITIVITY,
                alarms=alarms if not confirmed else 0, confirmed=confirmed,
                false_alarm_rate_per_km2=FALSE_ALARM_PER_KM2)
    swlog.append(Sweep(cell_x=cx_a, cell_y=cy_a, swept_m2=SWEEP_FOOTPRINT_M2,
                       sensitivity=SENSITIVITY, alarms=alarms, confirmed=confirmed,
                       false_alarm_rate_per_km2=FALSE_ALARM_PER_KM2,
                       propensity=prop, exploration=bool(expl), run_id="sim-001"))
    if confirmed:
        lat, lon = enu.inverse(ao.x0 + (cx_a + .5) * ao.res, ao.y0 + (cy_a + .5) * ao.res)
        d = Detection(lat=float(lat), lon=float(lon), provenance=Provenance.SYNTHETIC,
                      mine_type="simulated", run_id="sim-001")
        detections.append(d)
        swlog.append(d)
    robot_xy = (ao.x0 + (cx_a + .5) * ao.res, ao.y0 + (cy_a + .5) * ao.res)

log(f"  {n_explore} exploration sweeps ({n_explore / N_WAYPOINTS:.0%}), "
    f"{n_alarm} alarms, {n_conf} operator-confirmed")
log(f"  ground truth: {int(truth.sum())} mines present, {n_conf} removed, "
    f"{int(remaining.sum())} still in the ground")
assert n_conf <= int(truth.sum()), "confirmed more mines than exist"
log(f"  swept {float(fld.swept_area.sum()):,.0f} m^2 of "
    f"{ao.n_cells * ao.cell_area:,.0f} m^2 "
    f"({float(fld.swept_area.sum()) / (ao.n_cells * ao.cell_area):.2%} of the AO)")

# ---------------------------------------------------------------------------
# What the mission actually achieved
# ---------------------------------------------------------------------------

touched = fld.swept_area > 0
log(f"\nposterior movement:")
log(f"  prior total expected mines  {prior_mean_total:10.2f}")
log(f"  posterior total             {float(fld.mean.sum()):10.2f}")
log(f"  cells with any evidence     {int(touched.sum()):,} of {ao.n_cells:,}")
in_belt = truth_density > 0.25 * BELT_DENSITY_PER_KM2

# Break the AO down by what each cell actually experienced. Averaging over the
# belt buries a handful of detections under thousands of untouched cells, which
# is itself the honest headline: the posterior stays prior-dominated everywhere
# except where the robot physically went.
found = np.zeros_like(touched)
for cy_h, cx_h in hit_cells:
    found[cy_h, cx_h] = True
null_swept = touched & ~found
unswept = ~touched
for label, sel in (("detection here", found),
                   ("swept, nothing found", null_swept),
                   ("never swept", unswept)):
    if not sel.any():
        continue
    log(f"  {label:22} {int(sel.sum()):6,} cells   "
        f"P(any) {float(prior_p_any[sel].mean()):.6f} -> {float(fld.p_any[sel].mean()):.6f}"
        f"   ({float(fld.p_any[sel].mean() / max(prior_p_any[sel].mean(), 1e-12)):8.3f}x)")
log(f"  strongest cell         P(any) {float(fld.p_any.max()):.4f} "
    f"vs prior {float(prior_p_any.max()):.6f} "
    f"({float(fld.p_any.max() / max(prior_p_any.max(), 1e-12)):,.0f}x)")
log(f"  belt recall            {int(found[in_belt].sum())} of "
    f"{int(found.sum())} detection cells fall inside the true belt")
log(f"  coverage layer         {float(fld.coverage_fraction.mean()):.1%} of the AO swept "
    "-- deterministic, and the only number that moves fast")
log("  NOTE: with 30% of a 200 m plot swept, most of the map is still the prior. "
    "That is the correct behaviour, not a bug.")

# How much is one clean sweep actually worth? The shrink factor beta/(beta+t) is
# the whole answer, and at a low prior density beta is enormous, so it is ~1.
_a0, _b0 = M.prior_from_mean(parent_density * ao.cell_area / 1e6)
_t = float(M.effective_exposure(coverage, SENSITIVITY))
log(f"\n  how informative is one clean sweep here?")
log(f"    prior beta = {float(_b0):,.0f}; one full-cell sweep contributes t = {_t:.3f}")
log(f"    posterior mean shrinks by {float(_b0 / (_b0 + _t)):.6f} -- "
    f"{(1 - float(_b0 / (_b0 + _t))) * 100:.4f}% per sweep")
log(f"    sweeps needed to halve this cell's estimate: {float(_b0 / _t):,.0f}")
log("    This is the honest scale of the problem: where the prior already says "
    "'almost certainly empty',")
log("    a clean sweep confirms what you believed and moves nothing. Detections "
    "move the map; nulls barely do.")

# ---------------------------------------------------------------------------
# Provenance gate
# ---------------------------------------------------------------------------

log(f"\nprovenance gate ({len(detections)} synthetic detections):")
probe = detections or [Detection(lat=lat0, lon=lon0, provenance=Provenance.SYNTHETIC)]
try:
    export_registered(probe)
    log("  FAIL: synthetic detections passed the strict export gate")
    sys.exit(1)
except ProvenanceError as e:
    log(f"  OK: export_registered() refused them -- {e}")
anomaly = Detection(lat=lat0, lon=lon0, provenance=Provenance.SENSOR_ANOMALY)
try:
    export_registered([anomaly])
    log("  FAIL: an unadjudicated sensor anomaly passed the strict export gate")
    sys.exit(1)
except ProvenanceError:
    log("  OK: a raw sensor anomaly is refused -- only operator_confirmed / "
        "eod_disposed meet the IMAS direct-evidence bar")
log(f"  registered hazards exported: {len(export_registered(detections, strict=False))} "
    "(correct: no synthetic record may ever be published as a confirmed mine)")

# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

fld.save(OUT, stem="ao_posterior")
plan = mission.plan_route(fld, robot_xy=robot_xy, n_waypoints=60, coverage=coverage,
                          sensitivity=SENSITIVITY, rng=rng)
(OUT / "next_mission.json").write_text(json.dumps({
    "frame_id": "world",
    "origin_lat": lat0, "origin_lon": lon0,
    "resolution_m": AO_RES_M,
    "waypoints": plan,
    "WARNING": ("MODEL OUTPUT - NOT A CLEARANCE RECORD. These waypoints are survey "
                "priorities, not a safe route. Nothing here has been cleared."),
}, indent=1), encoding="utf-8")

# Replay check: the log alone must reproduce the posterior.
fresh = PosteriorField.from_density(ao, enu, parent_density, prior_source="replay")
fresh.corr_length_m = fld.corr_length_m
n = SweepLog(logpath).replay(fresh)
delta = float(np.abs(fresh.mean - fld.mean).max())
log(f"\nreplay check: {n} sweeps replayed from the log, "
    f"max |mean| difference {delta:.3e}")
assert delta < 1e-9, "replaying the sweep log did not reproduce the posterior"

log(f"\nwrote into {OUT}:")
for p in sorted(OUT.iterdir()):
    log(f"  {p.name:24} {p.stat().st_size:10,} bytes")
