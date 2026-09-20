"""Build the landmine prior from UCDP GED v25.1.

Outputs (into data/out/):
  ukraine_grid.npz    5 km equal-area Gamma prior over Ukraine + raion/oblast index
  world_grid.npz      0.25 deg global exposure raster + per-country totals
  regions.json        district/oblast/country aggregates for the HTML
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d
from shapely.geometry import Point, shape
from shapely.prepared import prep
from shapely.strtree import STRtree

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mineprior import model as M
from mineprior import prior as P
from mineprior.geo import UKRAINE_LAEA, Grid

DATA = Path(r"C:\Users\rinoa\landmine-bayes\data")
OUT = DATA / "out"
OUT.mkdir(exist_ok=True)

UA_RES_KM = 5.0
"""5 km cells. The GED prior must not be finer than this.

A resolution-saturation test settles it empirically: Ukraine's occupied cell
count runs 0.5deg=225, 0.25deg=509, 0.1deg=1250, 0.05deg=1922, 0.025deg=2234,
0.01deg=2346. Going from 0.05 to 0.01 deg multiplies available cells 25x and
occupied cells only 1.22x, because there are only ~2,440 distinct coordinates
behind 31,547 events. Median nearest-neighbour spacing between distinct coded
locations is 3.58 km. There is no information below ~0.05 deg, and 5 km ~=
0.045 deg lat sits right at that limit.
"""

WORLD_RES_DEG = 0.25

# Contaminated area in km^2 and severity band, parsed from Mine Action Review,
# "Clearing the Mines 2025" (1 Nov 2025) -- see build/parse_ctm.py. These are
# AP MINED AREA under Article 5 reporting, NOT the far larger "potentially
# hazardous area" survey envelopes.
#
# That distinction is the easiest way to be wrong by three orders of magnitude:
# Ukraine's widely quoted 139,000 km^2 is territory requiring SURVEY (~23% of
# the country). The envelope is the SUPPORT of the prior; these figures are its
# MASS. The ratio is roughly 1,400:1.
#
# Landmine Monitor severity bands: Light <5, Medium 5-19, Heavy 20-99,
# Massive >100 km^2.
BAND_MIDPOINT = {"Light": 2.5, "Medium": 12.0, "Heavy": 55.0, "Massive": 250.0}

# Mine Action Review's state names -> GED's own country strings, which use
# historical forms. Only states GED actually covers can be joined.
CTM_TO_GED = {
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
    "Cambodia": "Cambodia (Kampuchea)",
    "Democratic Republic of the Congo": "DR Congo (Zaire)",
    "Myanmar": "Myanmar (Burma)",
    "Russia": "Russia (Soviet Union)",
    "Yemen": "Yemen (North Yemen)",
    "North Korea": "North Korea",
    "South Korea": "South Korea",
}

UKRAINE_KM2_DEFAULT = 105.88
"""Landmine Monitor 2025 reports 105.88 km^2 of landmine contamination for
Ukraine, and that is used as the default calibration anchor.

It must be read alongside Mine Action Review's own 2025 verdict, which is
verbatim: "Massive but no reliable estimate". The specialist clearance-reporting
body does not believe a trustworthy national figure exists. So the absolute mine
COUNT this model reports has no trusted denominator; it is a modelling
assumption, exposed as a slider in the UI, and the relative ranking between
districts is the claim the data actually supports.
"""

MINES_PER_KM2 = 600.0
"""~6 antipersonnel mines per hectare inside land actually classified as
minefield. Two independent anchors converge here: 105,640 AP mines destroyed by
States Parties in 2024 over 175.39 km^2 of mined land cleared (~602/km^2), and
the Falklands programme, ~30,000 mines over 23 km^2 released (430-1,300/km^2).

This is an order-of-magnitude anchor, not a measured rate -- the two 2024
denominators come from different reports. It multiplies every output linearly,
so it is exposed as a slider in the UI rather than buried here.
"""

PI_BACKGROUND = 0.15
"""Share of a country's total attributed to diffuse background rather than to
mapped events -- contamination from incidents GED never recorded, legacy
ordnance, and the coarse-geocoded tail."""

T_REF = 2025.0


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

log("loading contamination baseline (Mine Action Review 2025) ...")
_ctm = json.load(open(DATA / "contamination.json", encoding="utf-8"))
CONTAMINATION = {}
for _name, _rec in _ctm.items():
    _ged = CTM_TO_GED.get(_name, _name)
    _km2 = _rec["km2"]
    CONTAMINATION[_ged] = {
        "km2": _km2 if _km2 is not None else BAND_MIDPOINT.get(_rec["band"]),
        "band": _rec["band"],
        "km2_reported": _km2 is not None,
    }
CONTAMINATION["Ukraine"] = {"km2": UKRAINE_KM2_DEFAULT, "band": "Massive",
                            "km2_reported": False}
log(f"  {len(CONTAMINATION)} contaminated states; "
    f"{sum(v['km2_reported'] for v in CONTAMINATION.values())} with a reported km^2 figure")

log("loading event cache ...")
ev = np.load(DATA / "ged_events.npz")
labels = json.load(open(DATA / "ged_labels.json", encoding="utf-8"))
countries = labels["countries"]

lat, lon = ev["lat"].astype(np.float64), ev["lon"].astype(np.float64)
wp = ev["where_prec"].astype(np.int64)
dur = ev["duration"].astype(np.float64)

w = P.event_weight(ev["tov"], ev["best"], dur, ev["year"], ev["clarity"], wp, T_REF)
sig = P.event_sigma_km(wp, dur)

keep = (w > 0) & np.isfinite(sig)
log(f"  {len(lat):,} events -> {keep.sum():,} usable "
    f"({(~keep).sum():,} dropped: where_prec in {P.DROP_PREC} or zero weight)")

# Guard against the centroid pile-up silently returning.
dropped_wp = np.bincount(wp[~keep], minlength=8)
log(f"  dropped by where_prec: " +
    ", ".join(f"{k}={dropped_wp[k]:,}" for k in range(1, 8) if dropped_wp[k]))

cid = ev["country"].astype(np.int64)
ua_code = countries.index("Ukraine")


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def load_geo(name):
    blob = json.load(open(DATA / "geo" / f"{name}.json", encoding="utf-8"))
    s = blob["scale"]
    feats = []
    for f in blob["features"]:
        polys = []
        for ring in f["r"]:
            xs, ys, x, y = [], [], ring[0], ring[1]
            xs.append(x / s)
            ys.append(y / s)
            for i in range(2, len(ring), 2):
                x += ring[i]
                y += ring[i + 1]
                xs.append(x / s)
                ys.append(y / s)
            polys.append(list(zip(xs, ys)))
        geom = shape({"type": "MultiPolygon", "coordinates": [[p] for p in polys]})
        if not geom.is_valid:
            geom = geom.buffer(0)
        feats.append({"name": f["n"], "geom": geom})
    return feats


log("loading geometry ...")
adm1 = load_geo("ukr_adm1")
adm2 = load_geo("ukr_adm2")
ua_union = shape({"type": "MultiPolygon", "coordinates": []})
from shapely.ops import unary_union
ua_union = unary_union([f["geom"] for f in adm1])
log(f"  {len(adm1)} oblasts, {len(adm2)} raions, UA area {ua_union.area:.2f} deg^2")


def assign_polygon(lons, lats, feats):
    """Index of the containing feature for each point, or -1. Falls back to the
    nearest feature, because a quantised admin centroid can land just outside
    its own concave polygon."""
    geoms = [f["geom"] for f in feats]
    tree = STRtree(geoms)
    preps = [prep(g) for g in geoms]
    out = np.full(len(lons), -1, dtype=np.int64)
    for i in range(len(lons)):
        pt = Point(lons[i], lats[i])
        for j in tree.query(pt):
            if preps[j].contains(pt):
                out[i] = j
                break
        if out[i] < 0:
            cand = tree.query_nearest(pt)
            j = int(np.atleast_1d(cand)[0])
            if geoms[j].distance(pt) < 0.25:  # ~25 km
                out[i] = j
    return out


# ---------------------------------------------------------------------------
# Ukraine: 5 km equal-area grid
# ---------------------------------------------------------------------------

log("\n=== Ukraine ===")
ua = keep & (cid == ua_code)
log(f"  {ua.sum():,} usable Ukraine events")

ua_lat, ua_lon, ua_w, ua_sig, ua_wp = lat[ua], lon[ua], w[ua], sig[ua], wp[ua]
ex, ey = UKRAINE_LAEA.forward(ua_lat, ua_lon)

# Grid padded so wide kernels do not clip at the border.
bx, by = UKRAINE_LAEA.forward(
    np.array([44.0, 53.0, 44.0, 53.0]), np.array([21.5, 21.5, 41.0, 41.0]))
grid = Grid.covering(bx, by, UA_RES_KM, pad=200.0)
log(f"  grid {grid.width} x {grid.height} = {grid.n_cells:,} cells at {UA_RES_KM} km")

exposure = np.zeros(grid.shape, dtype=np.float64)

# --- where_prec 3/4: spread uniformly over the admin polygon -----------------
# These rows are administrative CENTROIDS, not locations. A Gaussian at the
# centroid invents a bulge in the middle of a district; the true posterior over
# the location is roughly uniform across the unit.
gx, gy = grid.centre_mesh()
glat, glon = UKRAINE_LAEA.inverse(gx, gy)

log("  assigning grid cells to admin units ...")
cell_adm2 = assign_polygon(glon.ravel(), glat.ravel(), adm2).reshape(grid.shape)
cell_adm1 = assign_polygon(glon.ravel(), glat.ravel(), adm1).reshape(grid.shape)
land = cell_adm1 >= 0
log(f"  {land.sum():,} land cells ({land.sum() * grid.cell_area:,.0f} km^2)")

for lvl, feats, cell_idx in (("adm2", adm2, cell_adm2), ("adm1", adm1, cell_adm1)):
    sel = ua_wp == (3 if lvl == "adm2" else 4)
    if not sel.any():
        continue
    ev_idx = assign_polygon(ua_lon[sel], ua_lat[sel], feats)
    wsel = ua_w[sel]
    n_spread = 0
    for j in np.unique(ev_idx):
        if j < 0:
            continue
        mask = cell_idx == j
        n = int(mask.sum())
        if n == 0:
            continue
        exposure[mask] += float(wsel[ev_idx == j].sum()) / n
        n_spread += int((ev_idx == j).sum())
    log(f"  where_prec={3 if lvl == 'adm2' else 4}: spread {n_spread:,} events "
        f"uniformly over {len(np.unique(ev_idx[ev_idx >= 0]))} {lvl} units")

# --- where_prec 1/2/5: mass-normalised Gaussian ------------------------------
pt = np.isin(ua_wp, (1, 2, 5))
bins, reps = P.sigma_bins(ua_sig[pt])
px, py, pw = ex[pt], ey[pt], ua_w[pt]
cx, cy = grid.index_of(px, py)
ok = grid.in_bounds(cx, cy)
log(f"  where_prec in (1,2,5): {pt.sum():,} events in {len(reps)} sigma bins "
    f"({reps.min():.1f}-{reps.max():.1f} km)")

for k, s_km in enumerate(reps):
    sel = ok & (bins == k)
    if not sel.any():
        continue
    layer = np.zeros(grid.shape, dtype=np.float64)
    np.add.at(layer, (cy[sel], cx[sel]), pw[sel])
    s_cells = max(s_km / grid.res, 1e-3)
    # Separable Gaussian: exact for a Gaussian kernel, and normalised, so total
    # mass is conserved and an imprecise event spreads the same weight wider.
    layer = gaussian_filter1d(layer, s_cells, axis=0, mode="constant", truncate=P.TRUNC)
    layer = gaussian_filter1d(layer, s_cells, axis=1, mode="constant", truncate=P.TRUNC)
    exposure += layer

# --- sanity: no single cell may dominate -------------------------------------
exposure[~land] = 0.0
tot_exp = exposure.sum()
top = np.sort(exposure.ravel())[-1] / max(tot_exp, 1e-12)
log(f"  exposure total {tot_exp:,.1f}; largest single cell holds {top * 100:.2f}%")
assert top < 0.05, f"a single cell holds {top:.1%} of exposure -- centroid pile-up?"

# --- calibrate ---------------------------------------------------------------
n_star = CONTAMINATION["Ukraine"]["km2"] * MINES_PER_KM2
area_c = float(land.sum()) * grid.cell_area
a0 = PI_BACKGROUND * n_star / area_c
kappa = (1.0 - PI_BACKGROUND) * n_star / tot_exp
m = np.where(land, a0 * grid.cell_area + kappa * exposure, 0.0)
log(f"  calibrated to N* = {n_star:,.0f} mines "
    f"({CONTAMINATION['Ukraine']['km2']} km^2 x {MINES_PER_KM2:.0f}/km^2)")
log(f"  a0 = {a0:.4g} mines/km^2, kappa = {kappa:.4g}; sum(m) = {m.sum():,.0f}")

alpha, beta = M.prior_from_mean(m)
alpha[~land] = 0.0
beta[~land] = 1.0

np.savez_compressed(
    OUT / "ukraine_grid.npz",
    alpha=alpha.astype(np.float32), beta=beta.astype(np.float32),
    m=m.astype(np.float32), exposure=exposure.astype(np.float32),
    land=land, adm1=cell_adm1.astype(np.int16), adm2=cell_adm2.astype(np.int16),
    x0=grid.x0, y0=grid.y0, res=grid.res, width=grid.width, height=grid.height,
    lat0=UKRAINE_LAEA.lat0, lon0=UKRAINE_LAEA.lon0,
    n_star=n_star, a0=a0, kappa=kappa,
)
log(f"  wrote ukraine_grid.npz ({(OUT / 'ukraine_grid.npz').stat().st_size:,} bytes)")


# ---------------------------------------------------------------------------
# District aggregates
# ---------------------------------------------------------------------------

L_CORR_KM = 20.0
deff_cache = {}


def aggregate_cells(mask):
    n = int(mask.sum())
    if n == 0:
        return dict(n_cells=0, area_km2=0.0, mean=0.0, q05=0.0, q95=0.0, density=0.0, p_any=0.0)
    deff = deff_cache.setdefault(n, M.design_effect(L_CORR_KM, grid.cell_area, n))
    a, b = alpha[mask], beta[mask]
    mu, q05, q95 = M.district_interval(a, b, deff=deff)
    area = n * grid.cell_area
    return dict(n_cells=n, area_km2=area, mean=mu, q05=q05, q95=q95,
                density=mu / area, p_any=float(np.max(M.p_any(a, b))))


log("\n  aggregating districts ...")
regions = {"ukraine": {"oblasts": [], "raions": []}}
for j, f in enumerate(adm1):
    r = aggregate_cells(cell_adm1 == j)
    r["name"] = f["name"]
    regions["ukraine"]["oblasts"].append(r)
for j, f in enumerate(adm2):
    r = aggregate_cells(cell_adm2 == j)
    r["name"] = f["name"]
    parent = cell_adm1[(cell_adm2 == j) & (cell_adm1 >= 0)]
    r["parent"] = adm1[int(np.bincount(parent).argmax())]["name"] if parent.size else ""
    regions["ukraine"]["raions"].append(r)

regions["ukraine"]["oblasts"].sort(key=lambda r: -r["mean"])
regions["ukraine"]["raions"].sort(key=lambda r: -r["mean"])
log("  top oblasts by estimated mines:")
for r in regions["ukraine"]["oblasts"][:8]:
    log(f"    {r['name']:32} {r['mean']:9,.0f}  [{r['q05']:,.0f} - {r['q95']:,.0f}]"
        f"  {r['density']:7.2f}/km^2")


# ---------------------------------------------------------------------------
# World overview: 0.25 deg raster
# ---------------------------------------------------------------------------

log("\n=== World ===")
nx, ny = int(360 / WORLD_RES_DEG), int(180 / WORLD_RES_DEG)
world = np.zeros((ny, nx), dtype=np.float64)

gl = keep
wx = np.clip(((lon[gl] + 180.0) / WORLD_RES_DEG).astype(np.int64), 0, nx - 1)
wy = np.clip(((lat[gl] + 90.0) / WORLD_RES_DEG).astype(np.int64), 0, ny - 1)
wbins, wreps = P.sigma_bins(sig[gl])
lat_band = np.clip(((lat[gl] + 90.0) / 10.0).astype(np.int64), 0, 17)

KM_PER_DEG_LAT = 110.57
log(f"  {gl.sum():,} events, {len(wreps)} sigma bins x 18 latitude bands")
for k, s_km in enumerate(wreps):
    sel = wbins == k
    if not sel.any():
        continue
    layer = np.zeros((ny, nx), dtype=np.float64)
    np.add.at(layer, (wy[sel], wx[sel]), w[gl][sel])
    # Latitude: constant degree-sigma. Longitude: degree-sigma grows as
    # 1/cos(lat), so blur band by band.
    layer = gaussian_filter1d(layer, (s_km / KM_PER_DEG_LAT) / WORLD_RES_DEG,
                              axis=0, mode="constant", truncate=P.TRUNC)
    out_l = np.zeros_like(layer)
    for band in range(18):
        r0 = int(band * 10 / WORLD_RES_DEG)
        r1 = int((band + 1) * 10 / WORLD_RES_DEG)
        phi = math.radians(band * 10 - 90 + 5)
        km_lon = max(KM_PER_DEG_LAT * math.cos(phi), 1.0)
        out_l[r0:r1] = gaussian_filter1d(
            layer[r0:r1], (s_km / km_lon) / WORLD_RES_DEG, axis=1,
            mode="wrap", truncate=P.TRUNC)
    world += out_l

# Per-country exposure and calibrated totals.
log("  per-country totals ...")
country_exp = np.zeros(len(countries))
np.add.at(country_exp, cid[keep], w[keep])

# A mine estimate is produced ONLY for states that published AP mine
# contamination. Extrapolating from conflict exposure alone is exactly the
# "battle intensity relabelled as mine risk" error: Mexico has the 4th-highest
# GED event count in the dataset and essentially no landmines, because cartel
# violence is not mine-laying. Every other country shows conflict exposure --
# which is what GED actually measures -- and no mine figure at all.
matched = [c for c in CONTAMINATION if c in countries]
log(f"  {len(matched)} of {len(CONTAMINATION)} contaminated states matched to GED "
    f"names; unmatched: {sorted(set(CONTAMINATION) - set(matched))}")

world_rows = []
for i, c in enumerate(countries):
    if country_exp[i] <= 0:
        continue
    rec = CONTAMINATION.get(c)
    world_rows.append(dict(
        name=c,
        exposure=float(country_exp[i]),
        mines=float(rec["km2"] * MINES_PER_KM2) if rec else None,
        contaminated_km2=rec["km2"] if rec else None,
        km2_reported=bool(rec["km2_reported"]) if rec else False,
        band=rec["band"] if rec else None,
    ))
world_rows.sort(key=lambda r: (-(r["mines"] or -1), -r["exposure"]))
log("  states with published AP mine contamination (top 12 by estimate):")
for r in [x for x in world_rows if x["mines"] is not None][:12]:
    tag = "reported km2" if r["km2_reported"] else f"{r['band']} band midpoint"
    log(f"    {r['name']:26} {r['mines']:11,.0f} mines  "
        f"({r['contaminated_km2']:>8,.1f} km^2, {tag})")
log("  highest conflict exposure with NO published contamination "
    "(shown as exposure only, no mine estimate):")
for r in [x for x in world_rows if x["mines"] is None][:6]:
    log(f"    {r['name']:26} exposure {r['exposure']:12,.0f}")

regions["world"] = world_rows
json.dump(regions, open(OUT / "regions.json", "w", encoding="utf-8"))
np.savez_compressed(OUT / "world_grid.npz", exposure=world.astype(np.float32),
                    res=WORLD_RES_DEG)
log(f"\n  wrote regions.json ({(OUT / 'regions.json').stat().st_size:,} bytes), "
    f"world_grid.npz ({(OUT / 'world_grid.npz').stat().st_size:,} bytes)")
log("done.")
