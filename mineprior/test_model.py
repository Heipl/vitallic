"""Checks on the closed forms in model.py. Run: python -m mineprior.test_model"""
import math

import numpy as np

from mineprior import model as M

FAILS = []


def check(name, got, want, tol=1e-6):
    ok = abs(float(got) - float(want)) <= tol * max(1.0, abs(float(want)))
    print(f"  {'PASS' if ok else 'FAIL'}  {name:52} got={float(got):.6g} want={float(want):.6g}")
    if not ok:
        FAILS.append(name)


def assert_true(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        FAILS.append(name)


print("\n[1] prior_from_mean reproduces its mean exactly and is scale-invariant")
m = 0.2
a, b = M.prior_from_mean(m)
check("alpha", a, 0.425)
check("beta", b, 2.125)
check("mean == m", M.mean(a, b), 0.2)
check("var", M.var(a, b), 0.425 / 2.125 ** 2)
check("sd", M.sd(a, b), math.sqrt(0.425) / 2.125)

# Merging two equal cells must agree with the sum of two independent cells in
# both moments. The mean is exact at every scale; the variance is asymptotic in
# m >> psi*alpha_floor, the residual being exactly the alpha_floor term:
#   Var(2m) / 2Var(m) = (1 + a_f*psi/m) / (1 + a_f*psi/(2m))
m1 = 40.0
a1, b1 = M.prior_from_mean(m1)
a2, b2 = M.prior_from_mean(2 * m1)
check("merge: mean doubles exactly", M.mean(a2, b2), 2 * M.mean(a1, b1))
ratio = M.var(a2, b2) / (2 * M.var(a1, b1))
check("merge: var ratio matches the alpha_floor residual", ratio,
      (1 + M.ALPHA_FLOOR * M.PSI / m1) / (1 + M.ALPHA_FLOOR * M.PSI / (2 * m1)))
ratios = [float(M.var(*M.prior_from_mean(2 * m)) / (2 * M.var(*M.prior_from_mean(m))))
          for m in (40.0, 400.0, 4000.0)]
assert_true("merge: var ratio -> 1 as m grows", ratios[0] > ratios[1] > ratios[2] > 1.0)
check("merge: var ratio ~ 1 at m=4000", ratios[2], 1.0, tol=1e-3)

print("\n[2] null sweep: worked example from the spec (cluster_discount disabled)")
t = M.effective_exposure(0.9, 0.85, cluster_discount=1.0)
check("t = c*s", t, 0.765)
a0, b0 = M.prior_from_mean(0.2)
check("P(>=1 mine) before", M.p_any(a0, b0), 0.1511, tol=1e-3)
an, bn = M.update_null(a0, b0, t)
check("posterior alpha unchanged", an, 0.425)
check("posterior beta", bn, 2.890)
check("posterior mean", M.mean(an, bn), 0.1471, tol=1e-3)
check("shrink factor", M.mean(an, bn) / M.mean(a0, b0), 2.125 / 2.890)
check("posterior sd", M.sd(an, bn), 0.2256, tol=1e-3)
check("CV unchanged by a null sweep", M.cv(an, bn), M.cv(a0, b0))
check("P(>=1 REMAINING) after", M.p_any_remaining(a0, b0, t), 0.0327, tol=1e-3)
assert_true("a null sweep strictly lowers the mean",
            M.mean(an, bn) < M.mean(a0, b0))
assert_true("one perfect sweep cannot drive the mean to zero",
            M.mean(*M.update_null(a0, b0, 1.0)) > 0.0)

print("\n[3] cluster discount makes a clean sweep less informative, not more")
t_disc = M.effective_exposure(0.9, 0.85)
check("t discounted by 3", t_disc, 0.765 / 3.0)
assert_true("discounted null sweep shrinks the mean less",
            M.mean(*M.update_null(a0, b0, t_disc)) > M.mean(*M.update_null(a0, b0, t)))

print("\n[4] alarms: exact Gamma mixture")
aa, bb = M.update_alarms(0.425, 2.125, t=0.765, a=0, f=1.3)
check("a=0 is exactly conjugate even with f>0 (alpha)", aa, 0.425)
check("a=0 is exactly conjugate even with f>0 (beta)", bb, 2.125 + 0.765)
aa, bb = M.update_alarms(0.425, 2.125, t=0.765, a=3, f=0.0)
check("f=0 reduces to the confirmed update (alpha)", aa, 0.425 + 3)
check("f=0 reduces to the confirmed update (beta)", bb, 2.125 + 0.765)

# With a high false-alarm rate most alarms are clutter, so the posterior mean
# must sit well below the f=0 case.
m_fp = M.mean(*M.update_alarms(0.425, 2.125, t=0.765, a=3, f=5.0))
m_clean = M.mean(*M.update_alarms(0.425, 2.125, t=0.765, a=3, f=0.0))
prior_m = M.mean(a0, b0)
assert_true("high false-alarm rate discounts the alarms", m_fp < m_clean)

# Alarms raise the estimate only when there are more of them than clutter alone
# would produce. f=0.5 expected false alarms against a=3 observed is evidence
# for mines; f=5.0 against a=3 observed is evidence AGAINST them, and the mean
# must fall below the prior.
m_few_fp = M.mean(*M.update_alarms(0.425, 2.125, t=0.765, a=3, f=0.5))
assert_true("alarms above the clutter rate raise the mean", m_few_fp > prior_m)
assert_true("fewer alarms than clutter alone predicts lowers the mean", m_fp < prior_m)
assert_true("more alarms always means a higher mean, at fixed f",
            M.mean(*M.update_alarms(0.425, 2.125, t=0.765, a=6, f=5.0))
            > M.mean(*M.update_alarms(0.425, 2.125, t=0.765, a=3, f=5.0)))

# The moment-matched mixture must be WIDER than the naive plug-in, which is the
# whole reason for not using Gamma(alpha + E[k], beta + t).
amix, bmix = M.update_alarms(0.425, 2.125, t=0.765, a=4, f=2.0)
naive_a = 0.425 + 4 * (0.2 * 0.765) / (0.2 * 0.765 + 2.0)
naive_b = 2.125 + 0.765
assert_true("mixture is wider than the naive plug-in",
            M.var(amix, bmix) > M.var(naive_a, naive_b))

print("\n[5] predictive is over-dispersed relative to Poisson")
mu, v, p0 = M.predictive(0.425, 2.125, 0.765)
check("predictive mean", mu, 0.425 * 0.765 / 2.125)
assert_true("var > mean (over-dispersed)", v > mu)
check("P(find nothing)", p0, (2.125 / (2.125 + 0.765)) ** 0.425)

print("\n[6] VOI is exact, positive, and submodular in repeated sweeps")
v1 = M.voi(0.425, 2.125, 0.3)
check("VOI closed form", v1, M.var(0.425, 2.125) * 0.3 / (2.125 + 0.3))
a_sw, b_sw = M.update_null(0.425, 2.125, 0.3)
assert_true("second sweep of the same cell is worth less",
            M.voi(a_sw, b_sw, 0.3) < v1)
assert_true("VOI rises with exposure", M.voi(0.425, 2.125, 0.6) > v1)

print("\n[7] district aggregation")
rng = np.random.default_rng(0)
ms = rng.lognormal(0.0, 1.0, size=500) * 3.0
al, be = M.prior_from_mean(ms)
tot, q05, q95 = M.district_interval(al, be)
check("district mean == sum of cell means", tot, float(np.sum(ms)), tol=1e-9)
assert_true("q05 < mean < q95", q05 < tot < q95)

deff = M.design_effect(corr_length_km=20.0, cell_area_km2=25.0, n_cells=500)
check("DEFF for L=20km on a 5km grid", deff, 2 * math.pi * 400 / 25, tol=1e-9)
_, q05d, q95d = M.district_interval(al, be, deff=deff)
assert_true("correlation correction widens the interval", (q95d - q05d) > (q95 - q05))
check("DEFF capped at n_cells", M.design_effect(500.0, 25.0, 10), 10.0)

print("\n[8] p_any behaves at the limits")
assert_true("p_any -> 0 as the mean -> 0", M.p_any(*M.prior_from_mean(1e-9)) < 1e-6)
assert_true("p_any -> 1 for a heavily mined cell", M.p_any(*M.prior_from_mean(500.0)) > 0.99)
assert_true("p_any_remaining < p_any after any sweep",
            M.p_any_remaining(a0, b0, 0.3) < M.p_any(a0, b0))
assert_true("p_any_remaining == p_any at zero exposure",
            abs(M.p_any_remaining(a0, b0, 0.0) - M.p_any(a0, b0)) < 1e-12)

print("\n" + ("ALL CHECKS PASSED" if not FAILS else f"{len(FAILS)} FAILURES: {FAILS}"))
raise SystemExit(1 if FAILS else 0)
