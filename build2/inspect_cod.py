import json

for lvl in ("ADM1", "ADM2"):
    p = rf"C:\Users\rinoa\landmine-bayes\data\COD-UKR-{lvl}_simplified.geojson"
    g = json.load(open(p, encoding="utf-8"))
    f = g["features"]
    print(lvl, "features:", len(f))
    print("  props:", list(f[0]["properties"].keys()))
    print("  sample:", [x["properties"].get("shapeName") for x in f[:6]])
    print("  iso   :", [x["properties"].get("shapeISO") for x in f[:6]])
