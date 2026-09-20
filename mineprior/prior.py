"""Turning UCDP GED conflict events into a spatial exposure field.

The whole difficulty here is that GED records where an event was REPORTED, at a
declared precision, and that precision varies from an exact point to "somewhere
in this country".  Treating every row as a point is the default implementation
and it is catastrophically wrong: in Ukraine all 1,194 where_prec=6 events sit
on the single coordinate (49.000000, 32.000000), and they carry 89,634 deaths --
36.6% of every fatality GED records for Ukraine -- onto a pixel in Cherkasy
oblast, which saw essentially no ground combat.  A death-weighted KDE therefore
puts its single largest hotspot on uncontaminated central farmland.

So precision is handled in two ways, and neither is a fudge factor:

  * The kernel is MASS-NORMALISED (it integrates to 1).  An imprecise event
    spreads the same total weight over a far larger area, so it contributes
    proportionally less to any one cell.  This matters more than any weight term.
  * where_prec 3 and 4 are administrative CENTROIDS, not locations.  Where the
    admin polygon is available they are spread uniformly across it rather than
    smeared as a Gaussian bulge over the centroid.
  * where_prec 6 (country) and 7 (international waters/airspace) are DROPPED.
    A country-level intercept carries no usable spatial signal for this purpose,
    and level 7 events are at sea.

Codebook definitions (UCDP GED v25.1, section 5.4.2), verbatim in substance:
  1  exact location, a place name with a specific coordinate pair
  2  "near"/"in the area of"/up to 25 km from an exact location
  3  second-order administrative division (ADM2)
  4  first-order administrative division (ADM1)
  5  a linear feature or fuzzy polygon; or between two points >25 km apart
  6  the whole country only
  7  international waters or airspace
"""
from __future__ import annotations

import numpy as np

# --- weights -----------------------------------------------------------------

W_TOV = {1: 1.00, 2: 0.45, 3: 0.15}
"""Weight by type_of_violence: state-based / non-state / one-sided.

Minefields are an engineering product of force protection, not a by-product of
lethality.  One-sided violence is massacres of civilians, committed at
population centres with small arms -- it predicts UXO and IEDs at best, never
patterned minefields.  In Ukraine this term is nearly inert (99.3% of events are
state-based) but it removes a real confounder on the global map.
"""

B0, GAMMA_FAT, FAT_CAP = 5.0, 0.5, 20.0
"""f_fat(b) = min((1 + b/B0)^GAMMA_FAT, FAT_CAP).

f_fat(0) = 1, not 0: a zero-fatality artillery exchange still deposits UXO, and
254 Ukraine events have best=0.  The square root gives strongly diminishing
returns, because fatalities scale with population exposure as much as with
ordnance expended.  The cap stops the single best=15,996 Mariupol record from
carrying ~6.5% of the national prior on its own.
"""

GAMMA_DUR, DUR_CAP = 0.30, 365.0
TAU_YEARS, F_INF = 12.0, 0.35
"""f_rec models NET SURVIVAL of contamination, not decay of information.

Mines do not self-neutralise: Falklands mines laid in 1982 were still live when
clearance finished in 2020, and the Cambodian K5 belt from 1985-89 remains the
densest contamination on earth.  The decrement is CLEARANCE, not decay, hence
the floor.  Letting this go to zero would erase the 2014-2021 Donbas contact
line, which is among the most heavily contaminated ground in Ukraine.
"""

W_CLARITY = {1: 1.0, 2: 0.6}

F_PREC = {1: 1.0, 2: 1.0, 3: 1.0, 4: 0.9, 5: 0.8, 6: 0.0, 7: 0.0}
"""A small RESIDUAL reliability penalty only -- coarsely geocoded records also
tend to be poorly sourced.  The primary handling of precision is the kernel
bandwidth; penalising much harder here would charge twice for the same defect.
"""

SIGMA_PHYS_KM = 2.0
"""Physical footprint of contamination around a reported battle point, non-zero
even for an exact location.  Also absorbs the fact that Ukraine's 31,547 events
collapse onto only ~2,440 distinct coordinates, so even "exact" points are
really settlement centroids with genuine intra-settlement spread.
"""

SIGMA_GEO_KM = {1: 0.3, 2: 12.5, 3: 15.0, 4: 45.0, 5: 75.0}
"""Geolocation sigma by where_prec, from matching the second moment of a uniform
disc of radius R to an isotropic 2-D Gaussian: E[r^2] = R^2/2 = 2*sigma^2, so
sigma = R/2 = sqrt(A/(4*pi)).

  wp=2  R = 25 km (the codebook's own bound)          -> 12.5
  wp=3  Ukraine raion, mean area ~4,400 km^2           -> ~18.8, default 15.0
  wp=4  Ukraine oblast, mean area ~24,100 km^2         -> ~43.8, default 45.0
  wp=5  ~3 oblasts                                     -> ~75.7, default 75.0

Recompute per country with the same rule.  wp 6 and 7 are absent because they
are dropped outright.
"""

DROP_PREC = (6, 7)

TRUNC = 3.5
TRUNC_NORM = 1.0 - np.exp(-TRUNC ** 2 / 2.0)  # 0.9978055


def event_weight(tov, best, duration_days, year, clarity, where_prec, t_ref=2025.0):
    """w(e) = w_tov * f_fat * f_dur * f_rec * f_clar * f_prec. Dimensionless."""
    tov = np.asarray(tov)
    w = np.select([tov == 1, tov == 2, tov == 3],
                  [W_TOV[1], W_TOV[2], W_TOV[3]], default=0.0)

    f_fat = np.minimum((1.0 + np.asarray(best, dtype=np.float64) / B0) ** GAMMA_FAT, FAT_CAP)

    d = np.clip(np.asarray(duration_days, dtype=np.float64) + 1.0, 1.0, DUR_CAP)
    f_dur = d ** GAMMA_DUR

    age = np.maximum(t_ref - np.asarray(year, dtype=np.float64), 0.0)
    f_rec = F_INF + (1.0 - F_INF) * np.exp(-age / TAU_YEARS)

    f_clar = np.where(np.asarray(clarity) == 2, W_CLARITY[2], W_CLARITY[1])

    wp = np.asarray(where_prec)
    f_prec = np.select([wp == k for k in (1, 2, 3, 4, 5)],
                       [F_PREC[k] for k in (1, 2, 3, 4, 5)], default=0.0)

    return w * f_fat * f_dur * f_rec * f_clar * f_prec


def event_sigma_km(where_prec, duration_days):
    """sigma_e = sqrt(sigma_geo^2 + sigma_phys^2 + sigma_dur^2), added in
    quadrature because the three displacements are independent.

    sigma_dur = min(1.5*sqrt(D-1), 15) km models front movement during a
    multi-day record: a GED row spanning many days aggregates fighting over
    ground that shifted.
    """
    wp = np.asarray(where_prec)
    s_geo = np.select([wp == k for k in (1, 2, 3, 4, 5)],
                      [SIGMA_GEO_KM[k] for k in (1, 2, 3, 4, 5)], default=np.nan)
    d = np.clip(np.asarray(duration_days, dtype=np.float64), 0.0, DUR_CAP)
    s_dur = np.minimum(1.5 * np.sqrt(d), 15.0)
    return np.sqrt(s_geo ** 2 + SIGMA_PHYS_KM ** 2 + s_dur ** 2)


def sigma_bins(sigma, n_bins=14):
    """Bin sigma log-spaced so exposure can be built with a few separable
    Gaussian blurs instead of one kernel evaluation per event.

    Returns (bin_index, bin_sigma). A blur is exact for a Gaussian, so the only
    approximation is the binning of sigma itself -- at 14 log-spaced bins the
    worst-case bandwidth error is a few percent, far below the uncertainty in
    sigma itself.
    """
    sigma = np.asarray(sigma, dtype=np.float64)
    lo, hi = float(np.min(sigma)), float(np.max(sigma))
    if hi <= lo * 1.001:
        return np.zeros(sigma.shape, dtype=np.int64), np.array([lo])
    edges = np.exp(np.linspace(np.log(lo), np.log(hi), n_bins + 1))
    edges[0] *= 0.999
    edges[-1] *= 1.001
    idx = np.clip(np.digitize(sigma, edges) - 1, 0, n_bins - 1)
    reps = np.array([
        float(np.exp(np.mean(np.log(sigma[idx == k])))) if np.any(idx == k)
        else float(np.sqrt(edges[k] * edges[k + 1]))
        for k in range(n_bins)
    ])
    return idx, reps
