"""Conjugate Gamma-Poisson model of landmine intensity.

State variable is the intensity DENSITY rho_i (mines per km^2); the per-cell
expected count is lambda_i = rho_i * A_i.  Parameterising counts directly would
make the model depend on the grid resolution, which it must not.

    lambda_i ~ Gamma(shape=alpha_i, rate=beta_i)
    alpha_i  = alpha_floor + m_i / psi
    beta_i   = alpha_i / m_i          =>  prior mean is exactly m_i

This parameterisation is invariant under cell merging (merge two equal-area
cells: m doubles, and for m >> psi*alpha_floor both alpha and Var double, which
matches the variance of the sum of two independent cells).  A fixed alpha_0
would break that, because the number of alpha_0 terms scales with cell count.

Observation model: the robot sweeps a cell covering effective fraction c of its
area with detector sensitivity s, so effective exposure is t = c * s.  By Poisson
thinning, detections are exactly Poisson(lambda * t) -- this is not an
approximation and does not require large counts.  A clean sweep therefore
updates the RATE only, leaving the shape (and hence the CV) unchanged, which is
the correct behaviour: a null sweep lowers the estimate without making you
proportionally more certain.

Everything here is closed form.  No MCMC, no special functions beyond lgamma,
so it runs at sensor rate on the robot and transcribes directly into JS.
"""
from __future__ import annotations

import math

import numpy as np

# ---------------------------------------------------------------------------
# Defaults.  Every one of these is a modelling choice, not a measurement.
# ---------------------------------------------------------------------------

PSI = 8.0
"""Asymptotic variance-to-mean ratio of the prior, in mines.

Strong over-dispersion, because mines are laid in patterned belts rather than
scattered as a Poisson process.  Observed densities span four orders of
magnitude -- ~0.72 items/ha area-wide over released Ukrainian land, ~6/ha inside
a generic confirmed minefield, ~60/ha in the Cambodian K5 belt, and a reported
peak of 5 mines/m^2 in parts of the Surovikin line -- so a single-rate Poisson
would under-predict exactly the barrier minefields that matter most.
"""

ALPHA_FLOOR = 0.4
"""Lower bound on the Gamma shape, giving CV = 1/sqrt(0.4) = 1.58 for near-empty
cells.  Without it a cell with m = 1e-6 gets alpha ~ 1e-6: a degenerate spike at
zero claiming near-certain emptiness, which also breaks the Wilson-Hilferty
quantile approximation.
"""

CLUSTER_DISCOUNT = 3.0
"""Divisor applied to effective exposure to account for within-cell clustering.

The thinning likelihood assumes mines are uniform within the cell.  Minefields
are the opposite: a few compact belts.  For a cell holding 100 mines swept over
1.2% of its area, P(zero detections) is 0.33 under Poisson-uniform but ~0.97 if
those mines sit in a single hectare -- so a clean sweep is roughly 3x less
informative than the uniform model claims, and the naive update shrinks risk
faster than the evidence warrants.  That is the unsafe direction of error, so
the discount is applied by default and must be set to 1.0 explicitly to disable.
"""


# ---------------------------------------------------------------------------
# Prior construction
# ---------------------------------------------------------------------------

def prior_from_mean(m, psi: float = PSI, alpha_floor: float = ALPHA_FLOOR):
    """Gamma(alpha, beta) whose mean is exactly `m` (expected mines in the cell)."""
    m = np.asarray(m, dtype=np.float64)
    m_safe = np.maximum(m, 1e-12)
    alpha = alpha_floor + m_safe / psi
    beta = alpha / m_safe
    return alpha, beta


def mean(alpha, beta):
    return np.asarray(alpha) / np.asarray(beta)


def var(alpha, beta):
    b = np.asarray(beta)
    return np.asarray(alpha) / (b * b)


def sd(alpha, beta):
    return np.sqrt(np.asarray(alpha)) / np.asarray(beta)


def cv(alpha, beta):
    """Coefficient of variation; depends on the shape alone."""
    return 1.0 / np.sqrt(np.asarray(alpha))


# ---------------------------------------------------------------------------
# Risk readouts.  These, not the posterior mean, are what a map should show.
# ---------------------------------------------------------------------------

def p_any(alpha, beta):
    """P(at least one mine present) = 1 - P(M=0), marginalising over lambda.

    M | lambda ~ Poisson(lambda), so P(M=0) = (beta/(beta+1))^alpha.
    """
    a, b = np.asarray(alpha), np.asarray(beta)
    return -np.expm1(a * np.log(b / (b + 1.0)))


def p_any_remaining(alpha, beta, t):
    """P(at least one mine REMAINS) after a sweep of effective exposure `t`.

    By the thinning lemma the undetected remainder is Poisson(lambda*(1-t)) and
    is independent of what was detected, so this is the correct residual-risk
    number to paint after a sweep -- and it is NOT the posterior mean of lambda.
    """
    a, b, t = np.asarray(alpha), np.asarray(beta), np.asarray(t)
    return -np.expm1(a * np.log((b + t) / (b + 1.0)))


# ---------------------------------------------------------------------------
# Updates
# ---------------------------------------------------------------------------

def effective_exposure(coverage, sensitivity, cluster_discount: float = CLUSTER_DISCOUNT):
    """t = c * s / cluster_discount, clipped to [0, 1)."""
    t = np.asarray(coverage, dtype=np.float64) * np.asarray(sensitivity, dtype=np.float64)
    return np.clip(t / cluster_discount, 0.0, 1.0 - 1e-12)


def update_confirmed(alpha, beta, t, y):
    """Exact conjugate update for `y` CONFIRMED mines at effective exposure `t`."""
    return np.asarray(alpha) + np.asarray(y), np.asarray(beta) + np.asarray(t)


def update_null(alpha, beta, t):
    """Clean sweep. Shape unchanged, rate increased -- mean and sd shrink by the
    same factor beta/(beta+t), so the CV is unchanged.

    Note the floor: since t <= 1, one sweep can never take the mean below
    m * beta/(beta+1), however perfect the sensor.
    """
    return np.asarray(alpha), np.asarray(beta) + np.asarray(t)


def update_alarms(alpha: float, beta: float, t: float, a: int, f: float):
    """Exact posterior when the robot reports ALARMS, not confirmed mines.

    With a false-alarm rate the likelihood is Poisson(lambda*t + f), which is not
    conjugate -- the additive f sits inside the power.  Expanding the binomial,

        (lambda*t + f)^a = sum_k C(a,k) (lambda*t)^k f^(a-k)

    makes the posterior an EXACT finite mixture of a+1 Gammas, where k is
    literally "how many of the a alarms were real mines".  Returns the
    moment-matched single Gamma so the rest of the pipeline stays conjugate.

    Note the mixture carries extra variance (uncertainty about which alarms were
    real) that Gamma(alpha + E[k], beta + t) cannot express; that shortcut has
    the right mean but is over-confident.

    a == 0 is exactly conjugate even with false positives, because exp(-f) is a
    constant in lambda and cancels in normalisation -- which matters, since null
    sweeps are the overwhelming majority of observations.
    """
    a = int(a)
    if a == 0:
        return float(alpha), float(beta) + float(t)
    if f <= 0.0:
        return float(alpha) + a, float(beta) + float(t)

    bt = beta + t
    log_w = np.empty(a + 1)
    for k in range(a + 1):
        log_w[k] = (
            math.lgamma(a + 1) - math.lgamma(k + 1) - math.lgamma(a - k + 1)
            + k * math.log(t) + (a - k) * math.log(f)
            + math.lgamma(alpha + k) - (alpha + k) * math.log(bt)
        )
    log_w -= log_w.max()
    w = np.exp(log_w)
    w /= w.sum()

    k = np.arange(a + 1)
    m1 = float(np.sum(w * (alpha + k))) / bt
    m2 = float(np.sum(w * (alpha + k) * (alpha + k + 1.0))) / (bt * bt)
    v = max(m2 - m1 * m1, 1e-300)
    return m1 * m1 / v, m1 / v


# ---------------------------------------------------------------------------
# Predictive and acquisition
# ---------------------------------------------------------------------------

def predictive(alpha, beta, t):
    """Negative-Binomial predictive for the next sweep: (mean, var, p_zero).

    y_new ~ NegBin(r=alpha, p=beta/(beta+t)).  Always over-dispersed relative to
    Poisson, because lambda itself is uncertain.
    """
    a, b, t = np.asarray(alpha), np.asarray(beta), np.asarray(t)
    mu = a * t / b
    return mu, mu * (1.0 + t / b), np.exp(a * np.log(b / (b + t)))


def voi(alpha, beta, t):
    """Expected posterior-variance reduction from a sweep of exposure `t`.

        E[Var_post] = alpha / (beta*(beta+t))
        VOI = Var_prior - E[Var_post] = Var_prior * t/(beta+t)

    Exact and O(1): the expected variance reduction does not depend on the
    realised count at all.  Monotone decreasing in beta, so repeated sweeps of
    the same cell yield strictly less -- the objective is submodular, and greedy
    selection is within (1 - 1/e) of optimal for the pure-information problem.
    """
    a, b, t = np.asarray(alpha), np.asarray(beta), np.asarray(t)
    return (a / (b * b)) * (t / (b + t))


# ---------------------------------------------------------------------------
# Aggregation to districts
# ---------------------------------------------------------------------------

def design_effect(corr_length_km: float, cell_area_km2: float, n_cells: int) -> float:
    """DEFF = min(n, max(1, 2*pi*L^2 / A_cell)).

    Neighbouring cells share smeared observations and the latent field is
    genuinely smooth, so summing independent per-cell variances badly understates
    a district total's uncertainty.  With an exponential correlation r(d) =
    exp(-d/L), the neighbour sum is (1/A) * int_0^inf exp(-r/L) 2*pi*r dr =
    2*pi*L^2/A.  Capped at n because a district smaller than one correlation
    patch is fully correlated.  This factor is large and it is real: reporting
    "4,200 +/- 12 mines" for a district is the failure mode it prevents.
    """
    return float(min(max(n_cells, 1), max(1.0, 2.0 * math.pi * corr_length_km ** 2 / cell_area_km2)))


def aggregate(alpha, beta, deff: float = 1.0):
    """Welch-Satterthwaite moment match for S = sum_i lambda_i over a district.

    A sum of independent Gammas with different rates is not Gamma, so match the
    first two moments.  Exact in both moments by construction, and exact as a
    distribution when all rates agree.

    Returns (A, B) of the fitted Gamma(A, B), with the variance inflated by
    `deff` before fitting.
    """
    a = np.asarray(alpha, dtype=np.float64)
    b = np.asarray(beta, dtype=np.float64)
    M = float(np.sum(a / b))
    V = float(np.sum(a / (b * b))) * deff
    if M <= 0 or V <= 0:
        return 0.0, 1.0
    return M * M / V, M / V


def wilson_hilferty(A: float, B: float, z: float) -> float:
    """Gamma quantile via the cube-root (Wilson-Hilferty) approximation.

    Relative error under ~1% for A > 5 and ~3% for A > 1.  Uses no special
    functions, so it transcribes directly into JS.
    """
    if A <= 0:
        return 0.0
    return max(0.0, (A / B) * (1.0 - 1.0 / (9.0 * A) + z / (3.0 * math.sqrt(A))) ** 3)


Z05, Z95 = -1.6448536269514729, 1.6448536269514729


def district_interval(alpha, beta, deff: float = 1.0):
    """District total: (mean, q05, q95) of the summed intensity.

    The Welch-Satterthwaite Gamma always UNDER-states the true skewness when the
    rates differ (Cauchy-Schwarz on sum(a/b^2)^2 <= sum(a/b) * sum(a/b^3)), so
    the upper tail is corrected with a Cornish-Fisher term and the larger of the
    two q95 estimates is returned.
    """
    a = np.asarray(alpha, dtype=np.float64)
    b = np.asarray(beta, dtype=np.float64)
    M = float(np.sum(a / b))
    V = float(np.sum(a / (b * b))) * deff
    if M <= 0 or V <= 0:
        return 0.0, 0.0, 0.0
    A, B = M * M / V, M / V
    q05 = wilson_hilferty(A, B, Z05)
    q95 = wilson_hilferty(A, B, Z95)

    mu3 = 2.0 * float(np.sum(a / (b ** 3))) * deff ** 1.5
    g1 = mu3 / V ** 1.5
    cf = M + math.sqrt(V) * (Z95 + (g1 / 6.0) * (Z95 * Z95 - 1.0))
    return M, q05, max(q95, cf)
