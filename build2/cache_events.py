"""Distil GED v25.1 into a compact .npz cache of only the fields the model uses.

Reading the 250 MB CSV takes ~40 s; the cache loads in well under a second, which
matters because the ETL gets re-run a lot while the kernel is being tuned.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CSV = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\rinoa\AppData\Local\Temp\claude\c--Users-rinoa\cdbe3cc9-ee66-4c79-a765-8d489a4e0a51\scratchpad\ged\GEDEvent_v25_1.csv"
OUT = Path(r"C:\Users\rinoa\landmine-bayes\data")

COLS = ["id", "year", "type_of_violence", "where_prec", "date_start", "date_end",
        "latitude", "longitude", "country", "country_id", "region",
        "adm_1", "adm_2", "best", "high", "low", "deaths_civilians", "event_clarity"]

df = pd.read_csv(CSV, usecols=COLS, low_memory=False)

# date_start/date_end give event duration, which separates a one-day raid from a
# months-long positional battle -- the latter is what actually gets mined.
ds = pd.to_datetime(df.date_start, errors="coerce")
de = pd.to_datetime(df.date_end, errors="coerce")
dur = (de - ds).dt.days.fillna(0).clip(lower=0).to_numpy(dtype=np.float32)

countries = sorted(df.country.astype(str).unique())
cidx = {c: i for i, c in enumerate(countries)}

adm1 = df.adm_1.fillna("").astype(str)
adm2 = df.adm_2.fillna("").astype(str)
adm1_vals = sorted(adm1.unique())
adm2_vals = sorted(adm2.unique())
a1idx = {v: i for i, v in enumerate(adm1_vals)}
a2idx = {v: i for i, v in enumerate(adm2_vals)}

np.savez_compressed(
    OUT / "ged_events.npz",
    lat=df.latitude.to_numpy(dtype=np.float32),
    lon=df.longitude.to_numpy(dtype=np.float32),
    year=df.year.to_numpy(dtype=np.int16),
    tov=df.type_of_violence.to_numpy(dtype=np.int8),
    where_prec=df.where_prec.to_numpy(dtype=np.int8),
    best=df.best.to_numpy(dtype=np.float32),
    civ=df.deaths_civilians.to_numpy(dtype=np.float32),
    clarity=df.event_clarity.to_numpy(dtype=np.int8),
    duration=dur,
    country=df.country.astype(str).map(cidx).to_numpy(dtype=np.int16),
    adm1=adm1.map(a1idx).to_numpy(dtype=np.int32),
    adm2=adm2.map(a2idx).to_numpy(dtype=np.int32),
)
json.dump({"countries": countries, "adm1": adm1_vals, "adm2": adm2_vals},
          open(OUT / "ged_labels.json", "w", encoding="utf-8"))

print(f"cached {len(df):,} events -> {(OUT / 'ged_events.npz').stat().st_size:,} bytes")
print(f"countries={len(countries)} adm1={len(adm1_vals)} adm2={len(adm2_vals)}")
print(f"duration: mean={dur.mean():.2f}d max={dur.max():.0f}d  >7d: {(dur > 7).sum():,}")
