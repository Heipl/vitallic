"""Ordering the work: which ground to send a clearance robot to first.

The posterior in `model.py` answers "where are the mines, probably".  It does
not answer "where does clearing them matter most", and those are different
questions: an empty steppe cell with a high modelled density and no one within
40 km is worth less of a demining team's season than a moderately contaminated
field behind a village school.  Prioritisation in mine action is explicitly a
land-use question, not just a hazard question -- IMAS 07.11 land release is
driven by what the land is needed FOR.

This module turns a stated ORDER of importance into a defensible score.  The
inputs are per-cell layers; the output is a number per cell and per district
that can be sorted.  It deliberately contains no data: every layer is supplied
by the caller (see build2/build_tasking.py), so the maths can be tested without
a 5 km grid and the sources can be swapped without touching the arithmetic.

THREE THINGS THIS SCORE IS NOT.
  1. It is not risk to the public.  A cell can score low because nobody lives
     nearby, and still kill the one person who walks into it.
  2. It is not a safety ranking, and nothing about a low score licenses entry.
     The bottom of this scale means "clear it later", never "it is clear".
  3. It is not a route.  It orders DISTRICTS for tasking; the route inside an
     area of operations is `mission.select_next`, which optimises something
     else entirely (expected finds and variance reduction, against battery).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np


@dataclass(frozen=True)
class Criterion:
    key: str
    label: str
    unit: str
    source: str
    note: str


# The order IS the specification: rank 1 dominates, and the weights below are
# derived from this order alone. Reordering this tuple reorders the weights.
CRITERIA: tuple[Criterion, ...] = (
    Criterion(
        "density", "Modelled mine density", "mines/km²",
        "This model (UCDP GED v25.1 prior + robot posterior)",
        "The hazard itself. Ranked first because every other criterion is a "
        "multiplier on it: land with no contamination needs no clearance team.",
    ),
    Criterion(
        "people", "People within reach", "people within 10 km",
        "WorldPop 2020 1 km (CC BY 4.0)",
        "Proximity to populated areas. Population is counted with a distance "
        "decay rather than inside the cell, because a minefield 3 km from a "
        "village is a village problem.",
    ),
    Criterion(
        "farmland", "Farmland", "% of cell cropland",
        "ESA WorldCover 2021 v200, class 40 (CC BY 4.0)",
        "Contaminated cropland is the classic mine-action loss: it is not just "
        "an injury risk, it is the livelihood that stops and the reason people "
        "enter suspect land knowingly.",
    ),
    Criterion(
        "schools", "Schools within reach", "schools within 10 km",
        "OpenStreetMap via HOT/HDX, amenity=school (ODbL)",
        "Children route around obstacles less predictably than adults, and a "
        "school fixes a large daily population to one place.",
    ),
    Criterion(
        "hospitals", "Hospitals within reach", "hospitals within 10 km",
        "OpenStreetMap via HOT/HDX, amenity/healthcare=hospital (ODbL)",
        "Both an asset to protect and the thing that determines whether an "
        "accident here is survivable.",
    ),
    Criterion(
        "roads", "Major roads", "km of highway/primary road within 10 km",
        "GRIP4 road density, Meijer et al. 2018 (CC BY 4.0)",
        "Access for the clearance convoy, and the corridor civilians and "
        "returning traffic actually use.",
    ),
    Criterion(
        "access", "Terrain accessibility", "0–1 (1 = workable)",
        "GMTED2010 30 arc-second relief (public domain) + ESA WorldCover",
        "Slope, relief and ground cover, as a BENEFIT: flat open ground is "
        "where a team and a machine can actually work. Difficult terrain is "
        "not safer, it is only slower, so it lowers priority without lowering "
        "hazard.",
    ),
)

KEYS: tuple[str, ...] = tuple(c.key for c in CRITERIA)
BY_KEY: dict[str, Criterion] = {c.key: c for c in CRITERIA}


def roc_weights(n: int) -> np.ndarray:
    """Rank-order-centroid weights for `n` criteria ranked best-first.

        w_k = (1/n) * sum_{i=k}^{n} 1/i

    The brief gave an ORDER of importance and no numbers, and ROC is the
    standard way to honour exactly that much information: it is the centroid of
    the simplex {w_1 >= w_2 >= ... >= w_n, sum = 1}, i.e. the average of every
    weight vector consistent with the stated ranking.  Inventing "density 40%,
    population 25%, ..." would assert precision nobody supplied; ROC asserts
    only the ranking, and is known to recover the true first choice more often
    than rank-sum or equal weights (Barron & Barrett 1996).

    For n = 7 this gives 0.370, 0.228, 0.156, 0.109, 0.073, 0.044, 0.020 --
    the first criterion carries more than the last four combined, which is the
    intended reading of "in order of what matters most".
    """
    if n < 1:
        raise ValueError("need at least one criterion")
    inv = 1.0 / np.arange(1, n + 1, dtype=np.float64)
    return np.cumsum(inv[::-1])[::-1] / n


def weights_for(keys: Sequence[str]) -> dict[str, float]:
    """ROC weights over an ENABLED subset, keeping the canonical rank order.

    Switching a criterion off must not silently promote it to weight zero while
    leaving the others' weights unnormalised, or the composite stops being a
    weighted mean and scores become incomparable between settings.
    """
    ordered = [k for k in KEYS if k in set(keys)]
    if not ordered:
        raise ValueError("no criteria enabled")
    w = roc_weights(len(ordered))
    return {k: float(w[i]) for i, k in enumerate(ordered)}


def percentile_score(x, mask=None) -> np.ndarray:
    """Map a layer onto [0, 1] by its national percentile among valid cells.

    Returns, for each cell, the FRACTION OF VALID CELLS HOLDING A STRICTLY
    SMALLER VALUE.  Ties take the bottom of their band, so the empty half of
    the country -- every cell with no school, no road, no cropland -- scores a
    true 0 instead of drifting up to the middle of the tie block.

    Why rank and not min-max or log-min-max: these seven layers have no common
    unit, and four of them are heavy-tailed counts where a single Kyiv-sized
    cell would otherwise compress everything else into the bottom percent of
    the scale.  Rank normalisation is invariant to any monotone rescaling, so
    the calibration sliders in the UI cannot move the ordering.

    What it costs, stated plainly: rank throws away magnitude.  The 99th
    percentile cell may hold ten times or a thousand times the mines of the
    98th, and this score cannot tell them apart -- which is why the UI shows
    the raw value of every criterion next to its score.
    """
    a = np.asarray(x, dtype=np.float64)
    valid = np.ones(a.shape, dtype=bool) if mask is None else np.asarray(mask, dtype=bool)
    out = np.zeros(a.shape, dtype=np.float64)
    vals = a[valid]
    if vals.size == 0:
        return out
    order = np.sort(vals)
    # searchsorted "left" counts strictly smaller values, which is the tie rule
    # described above.
    out[valid] = np.searchsorted(order, vals, side="left") / vals.size
    return out


def composite(layers: Mapping[str, np.ndarray], weights: Mapping[str, float]) -> np.ndarray:
    """Weighted sum of already-normalised layers. Weights must cover `layers`."""
    missing = [k for k in weights if k not in layers]
    if missing:
        raise KeyError(f"no layer supplied for {missing}")
    total = float(sum(weights.values()))
    if not np.isclose(total, 1.0, atol=1e-9):
        raise ValueError(f"weights must sum to 1, got {total}")
    out = None
    for k, w in weights.items():
        term = w * np.asarray(layers[k], dtype=np.float64)
        out = term if out is None else out + term
    return out


def accessibility(slope_deg, blocked_fraction) -> np.ndarray:
    """Terrain workability in [0, 1] for a ground clearance team.

    Two multiplicative terms, because either one alone is disqualifying:

      slope   1 at flat, falling to 0 at SLOPE_LIMIT_DEG.  Mechanical demining
              assets are commonly rated to roughly 15-20 degrees; past that the
              ground is manual-only and the machine stays on the truck.
      cover   the fraction of the cell under forest, permanent water, wetland
              or built structures, all of which stop a flail or a survey robot
              for different reasons.

    Deliberately NOT a hazard term: hard ground is not less mined, it is only
    harder to work, so this multiplies priority and never reduces risk.
    """
    s = np.clip(1.0 - np.asarray(slope_deg, dtype=np.float64) / SLOPE_LIMIT_DEG, 0.0, 1.0)
    c = np.clip(1.0 - np.asarray(blocked_fraction, dtype=np.float64), 0.0, 1.0)
    return s * c


SLOPE_LIMIT_DEG = 18.0
"""Slope at which mechanised clearance is treated as unavailable. Between the
commonly quoted 15 deg working limit for flails/tillers and the ~20 deg maximum
some manufacturers claim on prepared ground; at 5 km resolution the mean slope
of a cell understates the worst slope inside it, so the softer end is honest."""

TIER_BREAKS: tuple[float, ...] = (0.20, 0.35, 0.50, 0.65, 0.80)
"""Fallback breaks for the six display tiers, used when a build does not supply
its own.

A weighted mean of seven percentile layers concentrates near 0.5 -- averaging
independent uniforms is a Bates distribution, not a uniform one -- so an evenly
spaced scale like this one puts most of the country in the top three classes
and the map reads as "everywhere is urgent", which ranks nothing.
build_tasking.py therefore freezes `priority_breaks` of the national composite
into the payload instead.

Frozen at build time, and deliberately not recomputed as criteria are switched
off: if the breaks moved with the settings, a colour would stop meaning a
number and two screenshots of the same district would disagree."""

BREAK_QUANTILES: tuple[float, ...] = (0.50, 0.75, 0.90, 0.96, 0.99)
"""Where the six display classes fall in the national distribution of ground.

Deliberately not an even split. A tasking map is read to answer "where do we
go first", so the top class has to be small enough to act on: this puts the
bottom class at half the country and the top class at its worst 1% of land,
about 1,500 km^2, which is the order of a season's work for a national
programme rather than a wish."""


def tier_of(score, breaks=None) -> np.ndarray:
    """Index 0..5 of the display tier for a composite score."""
    b = TIER_BREAKS if breaks is None else breaks
    return np.searchsorted(np.asarray(b), np.asarray(score), side="right")


def priority_breaks(score, mask=None) -> list[float]:
    """Class breaks at BREAK_QUANTILES of the scored ground."""
    v = np.asarray(score, dtype=np.float64)
    v = v[np.ones(v.shape, bool) if mask is None else np.asarray(mask, bool)]
    return [float(np.quantile(v, q)) for q in BREAK_QUANTILES]


def rank_regions(regions: Sequence[Mapping], weights: Mapping[str, float]) -> list[dict]:
    """Sort regions by composite score, highest first.

    Each region is a mapping with a "scores" sub-mapping of normalised
    criterion values. A region missing an enabled criterion is scored on what
    it has, with the weights renormalised over the criteria it does have, and
    is flagged `partial` -- a district is never dropped from the tasking list
    because one input layer has a hole in it, and never silently credited with
    a zero it did not earn.
    """
    out = []
    for r in regions:
        have = [k for k in weights if r["scores"].get(k) is not None]
        if not have:
            continue
        w = weights_for(have)
        score = sum(w[k] * float(r["scores"][k]) for k in have)
        parts = {k: w[k] * float(r["scores"][k]) for k in have}
        out.append({**r, "score": score, "contrib": parts,
                    "partial": len(have) != len(weights)})
    out.sort(key=lambda r: -r["score"])
    for i, r in enumerate(out, 1):
        r["rank"] = i
    return out
