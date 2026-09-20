"""Download the open datasets the clearance-priority layers are built from.

Everything here is a third-party source with a licence that permits
redistribution of derived figures; nothing is generated, and nothing is
committed to the repository.  The raw files land in data/tasking/ (gitignored);
only the small per-region aggregates written by build_tasking.py are kept.

Run: python build2/fetch_tasking.py
"""
from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "tasking"

UA = "landmine-bayes/1.0 (research build; contact via repository)"

# name -> (url, licence, what it is used for)
SOURCES = {
    "ukr_ppp_2020_1km.tif": (
        "https://data.worldpop.org/GIS/Population/Global_2000_2020_1km/2020/UKR/"
        "ukr_ppp_2020_1km_Aggregated.tif",
        "WorldPop 2020, CC BY 4.0",
        "population within reach of contamination",
    ),
    "hotosm_ukr_education_facilities.zip": (
        "https://production-raw-data-api.s3.amazonaws.com/ISO3/UKR/education_facilities/"
        "hotosm_ukr_education_facilities_osm_geojson.zip",
        "OpenStreetMap contributors via HOT/HDX, ODbL",
        "schools",
    ),
    "hotosm_ukr_health_facilities.zip": (
        "https://production-raw-data-api.s3.amazonaws.com/ISO3/UKR/health_facilities/"
        "hotosm_ukr_health_facilities_osm_geojson.zip",
        "OpenStreetMap contributors via HOT/HDX, ODbL",
        "hospitals and clinics",
    ),
    # GRIP4 rather than Natural Earth 10 m roads: NE carries only 1,122 road
    # features over the whole of Ukraine and classifies 40% of them as
    # "Unknown", so a length-per-district figure built from it would be mostly
    # an artefact of how the 1:10 m cartography was digitised. GRIP4 is a
    # purpose-built road-density product with an explicit type hierarchy.
    "grip4_density_tp1.zip": (
        "https://dataportaal.pbl.nl/downloads/GRIP4/GRIP4_density_tp1.zip",
        "GRIP4, Meijer et al. 2018 (CC BY 4.0)",
        "major roads: highways",
    ),
    "grip4_density_tp2.zip": (
        "https://dataportaal.pbl.nl/downloads/GRIP4/GRIP4_density_tp2.zip",
        "GRIP4, Meijer et al. 2018 (CC BY 4.0)",
        "major roads: primary roads",
    ),
    # GMTED2010 30 arc-second mean elevation. Tiles are 20 deg of latitude by
    # 30 deg of longitude, so Ukraine (44.4-52.4 N, 22.1-40.2 E) needs four:
    # rows 30N (30-50 N) and 50N (50-70 N) crossed with 000E and 030E.
    "gmted_30N000E_mea300.tif": (
        "https://edcintl.cr.usgs.gov/downloads/sciweb1/shared/topo/downloads/GMTED/"
        "Global_tiles_GMTED/300darcsec/mea/E000/30N000E_20101117_gmted_mea300.tif",
        "USGS/NGA GMTED2010, public domain",
        "terrain accessibility",
    ),
    "gmted_30N030E_mea300.tif": (
        "https://edcintl.cr.usgs.gov/downloads/sciweb1/shared/topo/downloads/GMTED/"
        "Global_tiles_GMTED/300darcsec/mea/E030/30N030E_20101117_gmted_mea300.tif",
        "USGS/NGA GMTED2010, public domain",
        "terrain accessibility",
    ),
    "gmted_50N000E_mea300.tif": (
        "https://edcintl.cr.usgs.gov/downloads/sciweb1/shared/topo/downloads/GMTED/"
        "Global_tiles_GMTED/300darcsec/mea/E000/50N000E_20101117_gmted_mea300.tif",
        "USGS/NGA GMTED2010, public domain",
        "terrain accessibility",
    ),
    "gmted_50N030E_mea300.tif": (
        "https://edcintl.cr.usgs.gov/downloads/sciweb1/shared/topo/downloads/GMTED/"
        "Global_tiles_GMTED/300darcsec/mea/E030/50N030E_20101117_gmted_mea300.tif",
        "USGS/NGA GMTED2010, public domain",
        "terrain accessibility",
    ),
}

# ESA WorldCover is NOT downloaded: the tiles are 72 MB each and 28 of them
# cover Ukraine. build_tasking.py reads their overviews over HTTP instead, which
# transfers a few hundred KB per tile for the ~1 km view the 5 km grid needs.
WORLDCOVER_NOTE = (
    "ESA WorldCover 2021 v200 (CC BY 4.0) is read over HTTP from "
    "s3://esa-worldcover, overviews only -- see build_tasking.py"
)


def fetch(name: str, url: str) -> Path:
    dest = OUT / name
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  {name:42} cached  {dest.stat().st_size:12,} bytes")
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    tmp.replace(dest)
    print(f"  {name:42} fetched {dest.stat().st_size:12,} bytes")
    return dest


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"fetching clearance-priority inputs into {OUT}")
    failed = []
    for name, (url, lic, use) in SOURCES.items():
        try:
            p = fetch(name, url)
        except Exception as e:                      # noqa: BLE001 - report, continue
            print(f"  {name:42} FAILED  {e}")
            failed.append(name)
            continue
        digest = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        print(f"      sha256:{digest}  {lic}  [{use}]")
    print(f"  {WORLDCOVER_NOTE}")
    if failed:
        print(f"\n{len(failed)} source(s) unavailable: {', '.join(failed)}")
        print("build_tasking.py will score the affected criterion as NO DATA "
              "rather than substituting a guess.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
