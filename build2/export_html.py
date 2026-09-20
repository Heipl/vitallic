"""Pack every layer into one self-contained HTML file.

Nothing is fetched at runtime: geography, rasters and region tables are all
inlined. Rasters are quantised to bytes and base64'd; the page rebuilds them
into ImageData and blits the heatmap with a single drawImage per frame, so
frame cost does not depend on cell count.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mineprior import model as M
from mineprior.geo import UKRAINE_LAEA

ROOT = Path(r"C:\Users\rinoa\landmine-bayes")
DATA, OUT = ROOT / "data", ROOT / "dist"
OUT.mkdir(exist_ok=True)

GED_VERSION = "UCDP GED v25.1"
GED_COVERAGE = "1989-2024"


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode("ascii")


def log(*a):
    print(*a, flush=True)


payload = {}

# --- geography ---------------------------------------------------------------
# Geometry keys are prefixed so they cannot collide with the region tables
# written further down (payload["world"] is the country table).
for name in ("world", "ukr_adm1", "ukr_adm2"):
    key = f"geo_{name}"
    payload[key] = json.loads((DATA / "geo" / f"{name}.json").read_text(encoding="utf-8"))
    log(f"  geo {name:10} {len(payload[key]['features']):4} features")

# --- Ukraine 5 km grid -------------------------------------------------------
g = np.load(DATA / "out" / "ukraine_grid.npz")
alpha, beta, land = g["alpha"], g["beta"], g["land"]
res = float(g["res"])

rows = np.any(land, axis=1)
cols = np.any(land, axis=0)
r0, r1 = int(np.argmax(rows)), int(len(rows) - np.argmax(rows[::-1]))
c0, c1 = int(np.argmax(cols)), int(len(cols) - np.argmax(cols[::-1]))
alpha_c, beta_c, land_c = alpha[r0:r1, c0:c1], beta[r0:r1, c0:c1], land[r0:r1, c0:c1]
h, w = land_c.shape
log(f"  ukraine grid cropped {g['width']}x{g['height']} -> {w}x{h} "
    f"({land_c.sum():,} land cells)")

mean = np.where(land_c, M.mean(np.maximum(alpha_c, 1e-12), np.maximum(beta_c, 1e-12)), 0.0)

# Ship the PRIOR MEAN per cell, not a quantised display raster, so the page can
# rebuild (alpha, beta) exactly and run the conjugate update itself. Everything
# the map draws -- density, CV, P(any) -- derives from these, which also keeps a
# live posterior and the district tables from drifting apart.
#
# Land-only, in row-major order over the land mask: 40% of the grid is outside
# Ukraine and carries nothing.
lm = land_c.ravel()
m_land = mean.ravel()[lm].astype(np.float32)
a1_land = g["adm1"][r0:r1, c0:c1].ravel()[lm].astype(np.int8)
a2_land = g["adm2"][r0:r1, c0:c1].ravel()[lm].astype(np.int16)
assert a1_land.max() < 127 and a2_land.max() < 32767, "admin index overflows its dtype"

payload["ua"] = {
    "w": w, "h": h, "res": res,
    "x0": float(g["x0"]) + c0 * res, "y0": float(g["y0"]) + r0 * res,
    "lat0": float(g["lat0"]), "lon0": float(g["lon0"]),
    "land": b64(land_c.astype(np.uint8)),
    "m": b64(m_land), "adm1": b64(a1_land), "adm2": b64(a2_land),
    "n_land": int(lm.sum()),
    "psi": M.PSI, "alpha_floor": M.ALPHA_FLOOR,
    "cluster_discount": M.CLUSTER_DISCOUNT,
    "corr_length_km": 20.0,
    "n_star": float(g["n_star"]),
}
log(f"  per-cell prior: {len(m_land):,} land cells, "
    f"mean {m_land.mean():.2f} max {m_land.max():.1f} mines/cell")

# Names only -- the page recomputes every district statistic from the live
# posterior, so precomputed means would go stale the moment a user logs a
# detection.
# Names come from the PACKED geo files, which is the exact list build_prior.py
# indexed cells against -- reading the source GeoJSON instead would shift every
# index if prep_geo dropped a sliver feature.
payload["adm1_names"] = [f["n"] for f in payload["geo_ukr_adm1"]["features"]]
payload["adm2_names"] = [f["n"] for f in payload["geo_ukr_adm2"]["features"]]
assert a1_land.max() < len(payload["adm1_names"]), "adm1 index exceeds the name list"
assert a2_land.max() < len(payload["adm2_names"]), "adm2 index exceeds the name list"

# --- clearance tasking layers ------------------------------------------------
# Six of the seven criteria are static. The seventh -- mine density -- is
# recomputed in the page from the live posterior, so logging a detection
# reorders the tasking queue instead of leaving it frozen at the prior.
tk_path = DATA / "out" / "tasking.json"
if tk_path.exists():
    tk = json.loads(tk_path.read_text(encoding="utf-8"))
    tg = np.load(DATA / "out" / "tasking_grid.npz")
    static = [k for k in (c["key"] for c in tk["meta"]["criteria"]) if k != "density"]
    layers = {}
    for k in static:
        a = tg[k][r0:r1, c0:c1].ravel()[lm]
        layers[k] = b64(a.astype(np.uint8))
    payload["tasking"] = {
        "criteria": [{k: c[k] for k in ("key", "label", "unit", "source", "note", "weight")}
                     for c in tk["meta"]["criteria"]],
        "breaks": tk["meta"]["tier_breaks"],
        "reach_km": tk["meta"]["reach_km"],
        "slope_limit_deg": tk["meta"]["slope_limit_deg"],
        "layers": layers,
        "oblasts": {r["name"]: {"raw": r["raw"], "anchor": r["anchor"]}
                    for r in tk["oblasts"]},
        "raions": {r["name"]: {"raw": r["raw"], "anchor": r["anchor"],
                               "parent": r.get("parent", "")}
                   for r in tk["raions"]},
    }
    log(f"  tasking: {len(static)} static layers + live density, "
        f"{len(tk['raions'])} raions, {len(tk['oblasts'])} oblasts")
else:
    log("  tasking: no tasking.json -- priority layer will be hidden")

# --- world 0.5 deg exposure --------------------------------------------------
wg = np.load(DATA / "out" / "world_grid.npz")
we = wg["exposure"]
we = we.reshape(we.shape[0] // 2, 2, we.shape[1] // 2, 2).max(axis=(1, 3))
wh, ww = we.shape
wmax = float(we.max())
we_q = np.zeros((wh, ww), np.uint8)
wpos = we > 0
we_q[wpos] = np.clip(
    np.round(255.0 * np.log1p(we[wpos] / wmax * 255.0) / np.log1p(255.0)), 1, 255)
payload["world_raster"] = {"w": ww, "h": wh, "res": 0.5, "data": b64(we_q)}
log(f"  world raster {ww}x{wh} ({int(wpos.sum()):,} non-empty cells)")

# --- region tables -----------------------------------------------------------
regions = json.loads((DATA / "out" / "regions.json").read_text(encoding="utf-8"))


def trim(r):
    out = {"n": r["name"], "m": round(r["mean"], 1), "lo": round(r["q05"], 1),
           "hi": round(r["q95"], 1), "a": round(r["area_km2"], 1),
           "d": round(r["density"], 4), "c": r["n_cells"]}
    if r.get("parent"):
        out["p"] = r["parent"]
    return out


payload["oblasts"] = [trim(r) for r in regions["ukraine"]["oblasts"] if r["n_cells"]]
payload["raions"] = [trim(r) for r in regions["ukraine"]["raions"] if r["n_cells"]]
payload["world"] = [
    {"n": r["name"], "e": round(r["exposure"], 1),
     "m": round(r["mines"], 0) if r["mines"] is not None else None,
     "km2": r["contaminated_km2"], "rep": r["km2_reported"], "b": r["band"]}
    for r in regions["world"]]
log(f"  regions: {len(payload['oblasts'])} oblasts, {len(payload['raions'])} raions, "
    f"{len(payload['world'])} countries "
    f"({sum(1 for r in payload['world'] if r['m'] is not None)} with a mine estimate)")

# --- robot AO ----------------------------------------------------------------
ao_json = ROOT / "dist" / "robot" / "ao_posterior.json"
if ao_json.exists():
    side = json.loads(ao_json.read_text(encoding="utf-8"))
    d = np.load(ROOT / "dist" / "robot" / "ao_posterior.npz")
    a_ao, b_ao = d["alpha"].astype(np.float64), d["beta"].astype(np.float64)
    p = M.p_any(a_ao, b_ao)
    cov = np.clip(d["swept_area"] / side["cell_area_m2"], 0, 1)
    pmax = float(p.max())
    payload["ao"] = {
        "w": side["width"], "h": side["height"], "res": side["resolution_m"],
        "lat": side["origin_lat"], "lon": side["origin_lon"],
        "pmax": pmax,
        "p": b64(np.clip(np.round(p / max(pmax, 1e-12) * 255), 0, 255).astype(np.uint8)),
        "cov": b64(np.clip(np.round(cov * 255), 0, 255).astype(np.uint8)),
        "swept_frac": float(cov.mean()),
        "prior_source": side["prior_source"],
    }
    log(f"  robot AO {side['width']}x{side['height']} @ {side['resolution_m']} m, "
        f"{cov.mean():.1%} swept")

payload["meta"] = {
    "ged": GED_VERSION,
    "coverage": GED_COVERAGE,
    "grid_km": res,
    "ukraine_km2": float(land_c.sum()) * res * res,
    "mines_per_km2": 600.0,
    "n_star": float(g["n_star"]),
}

# --- assemble ----------------------------------------------------------------
tpl = (ROOT / "build" / "template.html").read_text(encoding="utf-8")
blob = json.dumps(payload, separators=(",", ":"))
html = tpl.replace("/*__DATA__*/null", blob)
dest = OUT / "landmine-bayes.html"
dest.write_text(html, encoding="utf-8")
log(f"\n  data payload {len(blob):,} bytes")
log(f"  wrote {dest} ({dest.stat().st_size:,} bytes, "
    f"{dest.stat().st_size / 16777216:.1%} of the 16 MB artifact budget)")
