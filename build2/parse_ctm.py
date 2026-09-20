"""Parse per-state AP mine contamination out of Mine Action Review's
'Clearing the Mines 2025' (1 November 2025).

Every country profile opens with a KEY DATA block in one of two shapes:

    AP MINE CONTAMINATION:          AP MINE CONTAMINATION:
    182km2                          Light, extent unknown
    Massive                         LAND RELEASE OUTPUTS
    (National authority estimate)
    LAND RELEASE OUTPUTS

The literal string also appears in running prose ("...covering an estimated
57km2 remained..."), and those mentions must NOT be parsed -- doing so picks up
the wrong figure for Angola and produces a nonsensical 279,388 km2 for Peru. The
discriminator is the LAND RELEASE OUTPUTS terminator, which only the KEY DATA
block has.

Landmine Monitor severity bands: Light <5, Medium 5-19, Heavy 20-99,
Massive >100 km2. Parsed figures are checked against their own band and any
inconsistency is rejected rather than silently trusted.
"""
import json
import re
from collections import Counter
from pathlib import Path

TXT = Path(r"C:\Users\rinoa\landmine-bayes\data\ctm2025.txt")
OUT = Path(r"C:\Users\rinoa\landmine-bayes\data\contamination.json")

full = TXT.read_text(encoding="utf-8")

STATES = [
    "Afghanistan", "Albania", "Algeria", "Angola", "Argentina", "Armenia",
    "Azerbaijan", "Bosnia and Herzegovina", "Burkina Faso", "Cambodia", "Cameroon",
    "Chad", "Chile", "Colombia", "Croatia", "Cyprus", "Democratic Republic of the Congo",
    "Ecuador", "Eritrea", "Ethiopia", "Falkland Islands", "Georgia", "Guinea-Bissau",
    "India", "Iran", "Iraq", "Israel", "Jordan", "Kyrgyzstan", "Lebanon", "Libya",
    "Mali", "Mauritania", "Moldova", "Mozambique", "Myanmar", "Niger", "Nigeria",
    "North Korea", "Oman", "Pakistan", "Palestine", "Peru", "Russia", "Senegal",
    "Serbia", "Somalia", "South Korea", "South Sudan", "Sri Lanka", "Sudan",
    "Syria", "Tajikistan", "Thailand", "Turkey", "Ukraine", "Uzbekistan",
    "Venezuela", "Vietnam", "Western Sahara", "Yemen", "Zimbabwe",
]
ALIASES = {"Turkiye": "Turkey", "Türkiye": "Turkey", "BiH": "Bosnia and Herzegovina",
           "DRC": "Democratic Republic of the Congo"}

BANDS = ("Massive", "Heavy", "Medium", "Light")
BAND_RANGE = {"Light": (0.0, 5.0), "Medium": (5.0, 19.0),
              "Heavy": (19.0, 100.0), "Massive": (100.0, float("inf"))}

block = re.compile(
    r"AP MINE CONTAMINATION:?\s*(.{0,200}?)LAND RELEASE OUTPUTS", re.S | re.I)

rows, rejected = {}, []
for m in block.finditer(full):
    body = m.group(1)
    num = re.search(r"([\d,]+(?:\.\d+)?)\s*km", body)
    band = next((b for b in BANDS if re.search(rf"\b{b}\b", body, re.I)), None)
    km2 = float(num.group(1).replace(",", "")) if num else None

    # The country name is most reliably recovered from the profile body that
    # follows the KEY DATA block, not from the page furniture before it.
    ctx = full[m.end(): m.end() + 6000]
    votes = Counter()
    for s in STATES:
        votes[s] += len(re.findall(rf"\b{re.escape(s)}\b", ctx))
    for a, s in ALIASES.items():
        votes[s] += len(re.findall(rf"\b{re.escape(a)}\b", ctx))
    if not votes or votes.most_common(1)[0][1] == 0:
        continue
    country = votes.most_common(1)[0][0]

    if km2 is not None and band:
        lo, hi = BAND_RANGE[band]
        if not (lo * 0.5 <= km2 <= hi * 1.5):
            rejected.append((country, km2, band))
            km2 = None
    if km2 is None and not band:
        continue
    rows[country] = {"km2": km2, "band": band}

OUT.write_text(json.dumps(rows, indent=1, sort_keys=True), encoding="utf-8")

print(f"parsed {len(rows)} states; {len(rejected)} figures rejected on band mismatch")
for c, k, b in rejected:
    print(f"  REJECTED {c}: {k:,.0f} km2 declared {b}")
print()
for k in sorted(rows, key=lambda k: -(rows[k]["km2"] or -1)):
    v = rows[k]
    km = f"{v['km2']:>10,.2f}" if v["km2"] is not None else "         -"
    print(f"  {k:34} {km} km2   {v['band'] or ''}")
