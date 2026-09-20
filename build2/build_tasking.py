"""Build the clearance-priority layers on the national 5 km grid.

Every layer is aggregated onto the SAME grid the posterior lives on, and then
onto the same raion/oblast index that produced regions.json, so a district's
tasking score and its mine estimate are talking about exactly the same cells.

Outputs (into data/out/ and dist/robot/):
  tasking_grid.npz        seven uint8 percentile layers + the composite
  tasking.json            per-district raw and normalised criterion values
  tasking_priority.json   the district tasking order, for the robot

What each layer is, and what is wrong with it -- both stated here because the
second half is the part that gets lost downstream:

  density     This model. Inherits every limitation of the prior, chiefly that
              it ends in 2024 and cannot see mines laid where fighting was
              prevented.
  people      WorldPop 2020. PRE-INVASION. Millions of people have moved since,
              so this is where people lived, and where many intend to return,
              not where they are tonight.
  farmland    ESA WorldCover 2021. Also pre-dates most of the war; fields that
              have since been cratered or abandoned still read as cropland.
  schools     OpenStreetMap. Mapping completeness is uneven and is WORST in
              exactly the contested oblasts that matter most here, so this
              layer is a lower bound that is biased low where it counts.
  hospitals   OpenStreetMap, same caveat, and an exhausted one: many facilities
              in the east are damaged or non-operational and OSM will not say so.
  roads       GRIP4 (c. 2018), 5 arcmin. Coarser than the 5 km grid, so it is
              nearest-neighbour sampled and smooths across district borders.
  access      GMTED2010 30 arc-second relief. A cell's MEAN slope hides the
              gully inside it; treat as a coarse workability screen only.

Run: python build2/fetch_tasking.py && python build2/build_tasking.py
"""
from __future__ import annotations

import concurrent.futures
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import from_bounds
from scipy.ndimage import convolve

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mineprior import model as M
from mineprior import tasking as T
from mineprior.geo import UKRAINE_LAEA, Grid

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "out"
RAW = DATA / "tasking"
ROBOT = ROOT / "dist" / "robot"

REACH_KM = 10.0
"""Radius of the "within reach" neighbourhood for population, schools,
hospitals and roads.

Not a cosmetic smoothing parameter: it is the claim that a minefield 10 km from
a village is still that village's problem, which is about an hour's walk and
the range at which people collect firewood, graze livestock and take shortcuts.
Tightening it to one cell would say that only the ground people stand on
matters, which is how you end up tasking a robot to an empty steppe cell
because the school is 6 km east and therefore invisible."""

WORLDCOVER = ("https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
              "ESA_WorldCover_10m_2021_v200_{tile}_Map.tif")
WC_READ_PX = 1125
"""Overview level to read from each 3-degree WorldCover tile: 36000 / 1125 = 32,
an exact power-of-two decimation, so GDAL serves it from the COG's own overview
pyramid instead of downloading the 72 MB full-resolution tile. 1125 px over 3
degrees is ~300 m, which puts ~280 samples in every 5 km cell."""

WC_CROP = 40
WC_BLOCKED = (10, 50, 80, 90)   # forest, built-up, permanent water, wetland
GMTED_ARCSEC = 30.0
UA_BBOX = (21.9, 44.2, 40.4, 52.5)      # west, south, east, north


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------------------
# The grid every layer is resampled onto
# ---------------------------------------------------------------------------

g = np.load(OUT / "ukraine_grid.npz")
alpha, beta, land = g["alpha"].astype(np.float64), g["beta"].astype(np.float64), g["land"]
cell_adm1, cell_adm2 = g["adm1"], g["adm2"]
grid = Grid(x0=float(g["x0"]), y0=float(g["y0"]), res=float(g["res"]),
            width=int(g["width"]), height=int(g["height"]))
H, W = grid.shape
N = H * W
gx, gy = grid.centre_mesh()
glat, glon = UKRAINE_LAEA.inverse(gx, gy)
log(f"grid {W} x {H} at {grid.res} km; {int(land.sum()):,} land cells")


def bin_ll(lon, lat, weights=None):
    """Sum point weights into 5 km cells. Points outside the grid are dropped."""
    lon = np.asarray(lon, dtype=np.float64).ravel()
    lat = np.asarray(lat, dtype=np.float64).ravel()
    x, y = UKRAINE_LAEA.forward(lat, lon)
    cx, cy = grid.index_of(x, y)
    ok = grid.in_bounds(cx, cy)
    w = None if weights is None else np.asarray(weights, dtype=np.float64).ravel()[ok]
    return np.bincount((cy[ok] * W + cx[ok]), weights=w, minlength=N).reshape(H, W)


DISC = None


def within_reach(a):
    """Sum of `a` over every cell whose centre lies within REACH_KM."""
    global DISC
    if DISC is None:
        r = int(REACH_KM // grid.res)
        yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
        DISC = (np.hypot(yy, xx) * grid.res <= REACH_KM + 1e-9).astype(np.float64)
    return convolve(a, DISC, mode="constant", cval=0.0)


def pixel_lonlat(ds, arr_shape, window=None):
    """Centre lon/lat of every pixel of a (possibly decimated) read."""
    tr = ds.transform if window is None else ds.window_transform(window)
    h, w = arr_shape
    full_h = ds.height if window is None else window.height
    full_w = ds.width if window is None else window.width
    sy, sx = full_h / h, full_w / w
    cols = (np.arange(w) + 0.5) * sx
    rows = (np.arange(h) + 0.5) * sy
    lon = tr.c + cols * tr.a
    lat = tr.f + rows * tr.e
    return np.meshgrid(lon, lat)


# ---------------------------------------------------------------------------
# 1. Modelled mine density -- the criterion the other six modulate
# ---------------------------------------------------------------------------

mines = np.where(land, M.mean(np.maximum(alpha, 1e-12), np.maximum(beta, 1e-12)), 0.0)
density = mines / grid.cell_area
log(f"\ndensity   {mines.sum():,.0f} modelled mines, "
    f"max cell {density.max():.2f}/km^2")

# ---------------------------------------------------------------------------
# 2. Population within reach
# ---------------------------------------------------------------------------

with rasterio.open(RAW / "ukr_ppp_2020_1km.tif") as ds:
    pop = ds.read(1, masked=True).filled(0.0).astype(np.float64)
    plon, plat = pixel_lonlat(ds, pop.shape)
pop = np.where(pop > 0, pop, 0.0)
pop_cell = bin_ll(plon, plat, pop)
people = within_reach(pop_cell)
log(f"people    {pop_cell.sum():,.0f} people binned; "
    f"busiest cell has {people.max():,.0f} within {REACH_KM:.0f} km")

# ---------------------------------------------------------------------------
# 3. Farmland, and the ground cover that stops a machine
# ---------------------------------------------------------------------------

tiles = [f"N{la:02d}E{lo:03d}" for la in (42, 45, 48, 51) for lo in range(21, 42, 3)]


def read_worldcover(tile):
    """Cropland / blocked / total pixel counts per 5 km cell for one tile."""
    try:
        with rasterio.open("/vsicurl/" + WORLDCOVER.format(tile=tile)) as ds:
            a = ds.read(1, out_shape=(WC_READ_PX, WC_READ_PX),
                        resampling=Resampling.nearest)
            lon, lat = pixel_lonlat(ds, a.shape)
    except rasterio.errors.RasterioIOError:
        return None                      # no such tile: all sea, nothing to count
    valid = a > 0
    return (bin_ll(lon[valid], lat[valid], (a[valid] == WC_CROP).astype(float)),
            bin_ll(lon[valid], lat[valid], np.isin(a[valid], WC_BLOCKED).astype(float)),
            bin_ll(lon[valid], lat[valid], np.ones(int(valid.sum()))))


crop_px = np.zeros((H, W))
blocked_px = np.zeros((H, W))
total_px = np.zeros((H, W))
with concurrent.futures.ThreadPoolExecutor(6) as ex:
    got = 0
    for res in ex.map(read_worldcover, tiles):
        if res is None:
            continue
        got += 1
        crop_px += res[0]
        blocked_px += res[1]
        total_px += res[2]
log(f"farmland  {got} of {len(tiles)} WorldCover tiles carried land; "
    f"{total_px.sum():,.0f} samples")
seen = total_px > 0
farmland = np.divide(crop_px, total_px, out=np.zeros((H, W)), where=seen)
blocked = np.divide(blocked_px, total_px, out=np.zeros((H, W)), where=seen)
gap = int((land & ~seen).sum())
if gap:
    log(f"          WARNING {gap} land cells have no WorldCover sample")

# ---------------------------------------------------------------------------
# 4/5. Schools and hospitals within reach
# ---------------------------------------------------------------------------

def facility_points(zip_name, member, keep):
    """Representative lon/lat of every feature matching `keep(properties)`."""
    with zipfile.ZipFile(RAW / zip_name) as z, z.open(member) as f:
        fc = json.load(f)
    lons, lats = [], []
    for feat in fc["features"]:
        if not keep(feat["properties"]):
            continue
        geom = feat.get("geometry") or {}
        co = geom.get("coordinates")
        if co is None:
            continue
        if geom["type"] == "Point":
            lons.append(co[0])
            lats.append(co[1])
            continue
        # A mapped school is a building or a grounds polygon; its centroid is
        # the only location claim worth making at 5 km resolution.
        pts = np.array(_flatten(co), dtype=np.float64)
        lons.append(float(pts[:, 0].mean()))
        lats.append(float(pts[:, 1].mean()))
    return np.array(lons), np.array(lats)


def _flatten(co):
    if isinstance(co[0], (int, float)):
        return [co]
    out = []
    for c in co:
        out.extend(_flatten(c))
    return out


s_lon, s_lat = facility_points(
    "hotosm_ukr_education_facilities.zip", "education_facilities.geojson",
    lambda p: p.get("amenity") == "school")
h_lon, h_lat = facility_points(
    "hotosm_ukr_health_facilities.zip", "health_facilities.geojson",
    lambda p: p.get("amenity") == "hospital" or p.get("healthcare") == "hospital")
school_cell = bin_ll(s_lon, s_lat)
hospital_cell = bin_ll(h_lon, h_lat)
schools = within_reach(school_cell)
hospitals = within_reach(hospital_cell)
log(f"schools   {len(s_lon):,} OSM schools ({int(school_cell.sum()):,} inside the grid)")
log(f"hospitals {len(h_lon):,} OSM hospitals ({int(hospital_cell.sum()):,} inside the grid)")

# ---------------------------------------------------------------------------
# 6. Major roads within reach
# ---------------------------------------------------------------------------

road_density = np.zeros((H, W))          # metres of road per km^2
for zname, member in (("grip4_density_tp1.zip", "grip4_tp1_dens_m_km2.asc"),
                      ("grip4_density_tp2.zip", "grip4_tp2_dens_m_km2.asc")):
    with rasterio.open(f"/vsizip/{RAW / zname}/{member}") as ds:
        win = from_bounds(*UA_BBOX, transform=ds.transform)
        a = ds.read(1, window=win, masked=True).filled(0.0).astype(np.float64)
        tr = ds.window_transform(win)
    a = np.where(a > 0, a, 0.0)
    # Nearest-neighbour sample of a coarser grid: every 5 km cell takes the
    # density of the 5 arcmin cell it falls in.
    col = np.clip(((glon - tr.c) / tr.a).astype(int), 0, a.shape[1] - 1)
    row = np.clip(((glat - tr.f) / tr.e).astype(int), 0, a.shape[0] - 1)
    road_density += a[row, col]
road_km_cell = road_density * grid.cell_area / 1000.0
roads = within_reach(road_km_cell)
log(f"roads     {road_km_cell[land].sum():,.0f} km of highway/primary road over land, "
    f"max {roads.max():,.0f} km within {REACH_KM:.0f} km")

# ---------------------------------------------------------------------------
# 7. Terrain accessibility
# ---------------------------------------------------------------------------

slope_sum = np.zeros((H, W))
slope_n = np.zeros((H, W))
for name in ("gmted_30N000E_mea300.tif", "gmted_30N030E_mea300.tif",
             "gmted_50N000E_mea300.tif", "gmted_50N030E_mea300.tif"):
    with rasterio.open(RAW / name) as ds:
        b = ds.bounds
        if b.right <= UA_BBOX[0] or b.left >= UA_BBOX[2] or \
           b.top <= UA_BBOX[1] or b.bottom >= UA_BBOX[3]:
            continue
        win = from_bounds(max(UA_BBOX[0], b.left), max(UA_BBOX[1], b.bottom),
                          min(UA_BBOX[2], b.right), min(UA_BBOX[3], b.top),
                          transform=ds.transform)
        z = ds.read(1, window=win, masked=True).filled(0.0).astype(np.float64)
        lon, lat = pixel_lonlat(ds, z.shape, win)
    if z.size == 0:
        continue
    # Ground spacing of a 30 arc-second cell: constant north-south, shrinking
    # with cos(lat) east-west.
    m_lat = GMTED_ARCSEC / 3600.0 * 111_195.0
    m_lon = m_lat * np.cos(np.radians(lat))
    dzdy, dzdx = np.gradient(z)
    slope = np.degrees(np.arctan(np.hypot(dzdx / m_lon, dzdy / m_lat)))
    slope_sum += bin_ll(lon, lat, slope)
    slope_n += bin_ll(lon, lat, np.ones(z.size))
slope_deg = np.divide(slope_sum, slope_n, out=np.zeros((H, W)), where=slope_n > 0)
access = T.accessibility(slope_deg, blocked)
log(f"access    mean slope over land {slope_deg[land].mean():.2f} deg, "
    f"steepest cell {slope_deg[land].max():.1f} deg; "
    f"mean workability {access[land].mean():.2f}")

# ---------------------------------------------------------------------------
# Normalise and combine
# ---------------------------------------------------------------------------

RAW_LAYERS = {"density": density, "people": people, "farmland": farmland,
              "schools": schools, "hospitals": hospitals, "roads": roads,
              "access": access}
assert set(RAW_LAYERS) == set(T.KEYS), "layer set does not match the criteria"

scores = {k: T.percentile_score(v, mask=land) for k, v in RAW_LAYERS.items()}
WEIGHTS = T.weights_for(T.KEYS)
composite = np.where(land, T.composite(scores, WEIGHTS), 0.0)
# Freeze the class breaks from the default weighting. Evenly spaced breaks put
# most of the country in the top three classes -- a mean of seven percentile
# layers piles up around 0.5 -- and a map where everything is urgent ranks
# nothing.
breaks = T.priority_breaks(composite, mask=land)
log("\nweights (rank-order centroid over the stated order):")
for k, w in WEIGHTS.items():
    log(f"  {k:10} {w:.3f}   {T.BY_KEY[k].label}")
log("  class breaks at national quantiles "
    f"{T.BREAK_QUANTILES}: "
    + ", ".join(f"{b:.3f}" for b in breaks))

# ---------------------------------------------------------------------------
# District aggregates
# ---------------------------------------------------------------------------

def names_of(geo):
    blob = json.loads((DATA / "geo" / f"{geo}.json").read_text(encoding="utf-8"))
    return [f["n"] for f in blob["features"]]


adm1_names, adm2_names = names_of("ukr_adm1"), names_of("ukr_adm2")


def district(mask):
    n = int(mask.sum())
    area = n * grid.cell_area
    flat = np.flatnonzero(mask.ravel())
    best = flat[int(np.argmax(composite.ravel()[flat]))]
    by, bx = divmod(best, W)
    return {
        "n_cells": n,
        "scores": {k: round(float(scores[k][mask].mean()), 4) for k in T.KEYS},
        "raw": {
            "density": round(float(mines[mask].sum() / area), 4),
            "people": int(round(float(pop_cell[mask].sum()))),
            "farmland": round(float(100.0 * crop_px[mask].sum()
                                    / max(total_px[mask].sum(), 1.0)), 1),
            "schools": int(school_cell[mask].sum()),
            "hospitals": int(hospital_cell[mask].sum()),
            "roads": int(round(float(road_km_cell[mask].sum()))),
            "access": round(float(access[mask].mean()), 3),
            "slope": round(float(slope_deg[mask].mean()), 2),
        },
        # Where a robot would actually start: the highest-scoring single cell
        # in the district, not its centroid, which is usually farmland nobody
        # has any reason to sweep.
        "anchor": {"lat": round(float(glat[by, bx]), 4),
                   "lon": round(float(glon[by, bx]), 4),
                   "score": round(float(composite[by, bx]), 4)},
    }


levels = {}
for level, idx, names in (("oblasts", cell_adm1, adm1_names),
                          ("raions", cell_adm2, adm2_names)):
    rows = []
    for j, nm in enumerate(names):
        mask = (idx == j) & land
        if not mask.any():
            continue
        rec = district(mask)
        rec["name"] = nm
        if level == "raions":
            parent = cell_adm1[mask & (cell_adm1 >= 0)]
            rec["parent"] = adm1_names[int(np.bincount(parent).argmax())] if parent.size else ""
        rows.append(rec)
    levels[level] = T.rank_regions(rows, WEIGHTS)
    log(f"\n{level}: {len(rows)} ranked")

log("\ntasking order, top 12 raions:")
log(f"  {'#':>3} {'raion':22} {'oblast':16} {'score':>6}  "
    f"{'mines/km2':>9} {'people':>9} {'crop%':>6} {'sch':>4} {'hosp':>4} {'acc':>5}")
for r in levels["raions"][:12]:
    q = r["raw"]
    log(f"  {r['rank']:>3} {r['name'][:22]:22} {r['parent'][:16]:16} {r['score']:.3f}  "
        f"{q['density']:9.2f} {q['people']:9,} {q['farmland']:6.1f} "
        f"{q['schools']:4} {q['hospitals']:4} {q['access']:5.2f}")

# A ranking driven entirely by one criterion would mean the other six are
# decoration; a ranking uncorrelated with mine density would mean the hazard
# stopped mattering. Report both, rather than asserting either.
dens_rank = {r["name"]: i for i, r in enumerate(
    sorted(levels["raions"], key=lambda r: -r["scores"]["density"]))}
shift = [abs(dens_rank[r["name"]] - i) for i, r in enumerate(levels["raions"])]
log(f"\n  median rank shift against a density-only ordering: {int(np.median(shift))} places "
    f"(max {max(shift)}) -- the six impact criteria move the list without replacing it")

# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

SOURCES = [
    {"layer": "density", "source": "UCDP GED v25.1 via this model", "licence": "—",
     "vintage": "events to 2024"},
    {"layer": "people", "source": "WorldPop 1 km, Ukraine", "licence": "CC BY 4.0",
     "vintage": "2020, pre-invasion"},
    {"layer": "farmland", "source": "ESA WorldCover v200, class 40", "licence": "CC BY 4.0",
     "vintage": "2021"},
    {"layer": "schools", "source": "OpenStreetMap via HOT/HDX, amenity=school",
     "licence": "ODbL", "vintage": "2026 extract"},
    {"layer": "hospitals", "source": "OpenStreetMap via HOT/HDX, amenity/healthcare=hospital",
     "licence": "ODbL", "vintage": "2026 extract"},
    {"layer": "roads", "source": "GRIP4 highway + primary density, Meijer et al. 2018",
     "licence": "CC BY 4.0", "vintage": "c. 2018"},
    {"layer": "access", "source": "GMTED2010 30 arc-second relief + ESA WorldCover",
     "licence": "public domain / CC BY 4.0", "vintage": "2010 / 2021"},
]

meta = {
    "method": "rank-order-centroid weights over percentile-normalised layers",
    "reach_km": REACH_KM,
    "slope_limit_deg": T.SLOPE_LIMIT_DEG,
    "grid_km": grid.res,
    "tier_breaks": [round(b, 4) for b in breaks],
    "criteria": [{"key": c.key, "label": c.label, "unit": c.unit, "source": c.source,
                  "note": c.note, "weight": round(WEIGHTS[c.key], 4)} for c in T.CRITERIA],
    "sources": SOURCES,
    "counts": {"schools": int(school_cell.sum()), "hospitals": int(hospital_cell.sum()),
               "population": int(pop_cell.sum())},
    "caveats": [
        "Priority is not risk: a district scores low when few people are near, "
        "not when the ground is clear.",
        "Population and land cover pre-date the full-scale invasion, so this is "
        "where people lived and farmed, not where they are tonight.",
        "OpenStreetMap coverage is thinnest in the contested east, which biases "
        "the schools and hospitals layers DOWN exactly where contamination is worst.",
        "Terrain accessibility raises priority where clearance is feasible. "
        "Difficult ground is not safer ground.",
    ],
}

json.dump({"meta": meta, "oblasts": levels["oblasts"], "raions": levels["raions"]},
          open(OUT / "tasking.json", "w", encoding="utf-8"))

np.savez_compressed(
    OUT / "tasking_grid.npz",
    composite=np.clip(np.round(composite * 255), 0, 255).astype(np.uint8),
    **{k: np.clip(np.round(scores[k] * 255), 0, 255).astype(np.uint8) for k in T.KEYS},
)

ROBOT.mkdir(parents=True, exist_ok=True)
json.dump({
    "frame_id": "wgs84",
    "generated_from": "data/out/tasking.json",
    "method": meta["method"],
    "weights": {k: round(v, 4) for k, v in WEIGHTS.items()},
    "reach_km": REACH_KM,
    "order": [{
        "rank": r["rank"], "raion": r["name"], "oblast": r["parent"],
        "score": round(r["score"], 4),
        "anchor_lat": r["anchor"]["lat"], "anchor_lon": r["anchor"]["lon"],
        "contribution": {k: round(v, 4) for k, v in r["contrib"].items()},
        "raw": r["raw"],
    } for r in levels["raions"]],
    "WARNING": ("MODEL OUTPUT - NOT A CLEARANCE RECORD. This is an order in which to "
                "SURVEY districts, not a safe route, not a clearance certificate, and "
                "not a statement that districts lower down the list hold fewer mines."),
}, open(ROBOT / "tasking_priority.json", "w", encoding="utf-8"), indent=1)

for p in (OUT / "tasking.json", OUT / "tasking_grid.npz", ROBOT / "tasking_priority.json"):
    log(f"  wrote {p.relative_to(ROOT)} ({p.stat().st_size:,} bytes)")
