"""Simplify + quantise boundary geometry so the whole map fits inside one HTML file.

Rings are stored as integer delta-encoded coordinate streams on a fixed grid,
which is ~3x smaller than 4-decimal GeoJSON and decodes in a few lines of JS.

Sources:
  world   world-atlas@2.0.2 countries-110m TopoJSON (ISC; Natural Earth, public domain)
  ukr_*   geoBoundaries gbHumanitarian UKR ADM1/ADM2 (CC BY 3.0 IGO; OCHA COD via
          Kartographia, 2022 vintage = the post-2020 reform 27 oblasts / 139 raions).
          The gbOpen UKR ADM2 release is the 2006 495-raion system and must NOT be used.
"""
import json
from pathlib import Path

from shapely.geometry import shape
from shapely.ops import transform

DATA = Path(r"C:\Users\rinoa\landmine-bayes\data")
OUT = DATA / "geo"
OUT.mkdir(exist_ok=True)

SCALE = 1000  # 1/1000 degree ~= 111 m; ample for a national/global map


def topo_to_features(path, object_name):
    """Minimal TopoJSON decoder -- avoids a dependency for one file."""
    t = json.load(open(path, encoding="utf-8"))
    tr = t.get("transform")
    sx, sy = (tr["scale"] if tr else (1, 1))
    tx, ty = (tr["translate"] if tr else (0, 0))

    arcs = []
    for arc in t["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty) if tr else (x, y))
        arcs.append(pts)

    def resolve(idx):
        return arcs[idx] if idx >= 0 else arcs[~idx][::-1]

    def ring_of(indices):
        pts = []
        for i in indices:
            seg = resolve(i)
            pts.extend(seg if not pts else seg[1:])
        return pts

    feats = []
    for geom in t["objects"][object_name]["geometries"]:
        gt = geom.get("type")
        if gt == "Polygon":
            g = {"type": "Polygon", "coordinates": [ring_of(r) for r in geom["arcs"]]}
        elif gt == "MultiPolygon":
            g = {"type": "MultiPolygon",
                 "coordinates": [[ring_of(r) for r in poly] for poly in geom["arcs"]]}
        else:
            continue
        feats.append({"props": geom.get("properties", {}), "geom": g})
    return feats


def encode(geom, tol):
    """Simplify, quantise, delta-encode. Returns a list of flat int arrays (one per ring)."""
    g = shape(geom)
    if not g.is_valid:
        g = g.buffer(0)
    if tol:
        g = g.simplify(tol, preserve_topology=True)
    g = transform(lambda x, y, z=None: (round(x * SCALE), round(y * SCALE)), g)
    if g.is_empty:
        return []
    polys = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
    rings = []
    for p in polys:
        if p.is_empty or p.geom_type != "Polygon":
            continue
        # exterior only: holes are invisible at this scale and cost bytes
        xs, ys = p.exterior.coords.xy
        if len(xs) < 4:
            continue
        px, py = int(xs[0]), int(ys[0])
        flat = [px, py]
        n = 0
        for i in range(1, len(xs)):
            cx, cy = int(xs[i]), int(ys[i])
            if cx == px and cy == py:
                continue  # drop duplicates created by quantisation
            flat.append(cx - px)
            flat.append(cy - py)
            px, py = cx, cy
            n += 1
        if n >= 3:
            rings.append(flat)
    return rings


def build(name, feats, tol, key, parent_key=None):
    out = []
    for f in feats:
        rings = encode(f["geom"], tol)
        if not rings:
            continue
        rec = {"n": f["props"].get(key, ""), "r": rings}
        if parent_key:
            rec["p"] = f["props"].get(parent_key, "")
        out.append(rec)
    blob = {"scale": SCALE, "features": out}
    p = OUT / f"{name}.json"
    p.write_text(json.dumps(blob, separators=(",", ":")), encoding="utf-8")
    pts = sum(len(r) // 2 for f in out for r in f["r"])
    print(f"{name:12} {len(out):4} features  {pts:7,} pts  {p.stat().st_size:9,} bytes")


world = topo_to_features(DATA / "countries-110m.json", "countries")
build("world", world, tol=0.08, key="name")

for lvl, tol in (("ADM1", 0.008), ("ADM2", 0.004)):
    gj = json.load(open(DATA / f"COD-UKR-{lvl}_simplified.geojson", encoding="utf-8"))
    feats = [{"props": f["properties"], "geom": f["geometry"]} for f in gj["features"]]
    build(f"ukr_{lvl.lower()}", feats, tol=tol, key="shapeName")
