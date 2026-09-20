"""Quick ground-truth profile of UCDP GED v25.1 -- used to sanity-check the model build."""
import json
import sys

import numpy as np
import pandas as pd

CSV = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\rinoa\AppData\Local\Temp\claude\c--Users-rinoa\cdbe3cc9-ee66-4c79-a765-8d489a4e0a51\scratchpad\ged\GEDEvent_v25_1.csv"

COLS = [
    "id", "year", "type_of_violence", "conflict_name", "dyad_name",
    "where_prec", "adm_1", "adm_2", "latitude", "longitude", "priogrid_gid",
    "country", "country_id", "region", "event_clarity", "date_prec",
    "date_start", "date_end", "deaths_a", "deaths_b", "deaths_civilians",
    "deaths_unknown", "best", "high", "low",
]

df = pd.read_csv(CSV, usecols=COLS, low_memory=False)
out = {}
out["n_rows"] = int(len(df))
out["year_min"] = int(df.year.min())
out["year_max"] = int(df.year.max())
out["events_per_decade"] = {
    str(k): int(v) for k, v in (df.year // 10 * 10).value_counts().sort_index().items()
}
out["type_of_violence"] = {str(k): int(v) for k, v in df.type_of_violence.value_counts().sort_index().items()}
out["where_prec"] = {str(k): int(v) for k, v in df.where_prec.value_counts().sort_index().items()}
out["date_prec"] = {str(k): int(v) for k, v in df.date_prec.value_counts().sort_index().items()}
out["event_clarity"] = {str(k): int(v) for k, v in df.event_clarity.value_counts().sort_index().items()}
out["null_latlon"] = int(df.latitude.isna().sum() + df.longitude.isna().sum())
out["lat_range"] = [float(df.latitude.min()), float(df.latitude.max())]
out["lon_range"] = [float(df.longitude.min()), float(df.longitude.max())]
out["best_total"] = int(df.best.sum())
out["top30_by_events"] = {str(k): int(v) for k, v in df.country.value_counts().head(30).items()}
out["top30_by_deaths"] = {
    str(k): int(v) for k, v in df.groupby("country", observed=True).best.sum().sort_values(ascending=False).head(30).items()
}

# Occupied cell counts at candidate resolutions
for res in (0.5, 0.25, 0.1, 0.05, 0.01):
    key = f"occupied_cells_{res}"
    ci = np.floor(df.longitude / res).astype(np.int64)
    cj = np.floor(df.latitude / res).astype(np.int64)
    out[key] = int(len(np.unique(ci * 100000 + cj)))

# Ukraine deep dive
ua = df[df.country == "Ukraine"].copy()
out["ukraine"] = {
    "n_events": int(len(ua)),
    "year_min": int(ua.year.min()) if len(ua) else None,
    "year_max": int(ua.year.max()) if len(ua) else None,
    "events_per_year": {str(k): int(v) for k, v in ua.year.value_counts().sort_index().items()},
    "bbox": [float(ua.longitude.min()), float(ua.latitude.min()),
             float(ua.longitude.max()), float(ua.latitude.max())],
    "where_prec": {str(k): int(v) for k, v in ua.where_prec.value_counts().sort_index().items()},
    "type_of_violence": {str(k): int(v) for k, v in ua.type_of_violence.value_counts().sort_index().items()},
    "adm_1_counts": {str(k): int(v) for k, v in ua.adm_1.value_counts().items()},
    "n_adm_2": int(ua.adm_2.nunique()),
    "best_total": int(ua.best.sum()),
    "conflicts": {str(k): int(v) for k, v in ua.conflict_name.value_counts().head(15).items()},
}
for res in (0.25, 0.1, 0.05, 0.01):
    ci = np.floor(ua.longitude / res).astype(np.int64)
    cj = np.floor(ua.latitude / res).astype(np.int64)
    out["ukraine"][f"occupied_cells_{res}"] = int(len(np.unique(ci * 100000 + cj)))

print(json.dumps(out, indent=1, default=str))
