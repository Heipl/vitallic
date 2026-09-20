import json

for lvl in ("ADM1", "ADM2"):
    p = rf"C:\Users\rinoa\landmine-bayes\data\UKR-{lvl}.geojson"
    g = json.load(open(p, encoding="utf-8"))
    f = g["features"]
    print(lvl, "features:", len(f))
    print("  props keys:", list(f[0]["properties"].keys()))
    print("  sample names:", [x["properties"].get("shapeName") for x in f[:10]])
    print("  geom types:", set(x["geometry"]["type"] for x in f))
