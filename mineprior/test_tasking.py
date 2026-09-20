"""Checks on the tasking score. Run: python -m mineprior.test_tasking"""
import numpy as np

from mineprior import tasking as T

FAILS = []


def check(name, got, want, tol=1e-9):
    ok = abs(float(got) - float(want)) <= tol * max(1.0, abs(float(want)))
    print(f"  {'PASS' if ok else 'FAIL'}  {name:56} got={float(got):.6g} want={float(want):.6g}")
    if not ok:
        FAILS.append(name)


def assert_true(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        FAILS.append(name)


print("\n[1] rank-order-centroid weights encode the stated order and nothing else")
w = T.roc_weights(7)
check("weights sum to 1", w.sum(), 1.0)
assert_true("strictly decreasing", bool(np.all(np.diff(w) < 0)))
check("w1 = (1/7) * H_7", w[0], sum(1.0 / i for i in range(1, 8)) / 7)
check("w7 = 1/49", w[6], 1.0 / 49)
assert_true("rank 1 outweighs ranks 4-7 combined", w[0] > w[3:].sum())
check("n=1 is the degenerate case", T.roc_weights(1)[0], 1.0)
assert_true("seven criteria, in the briefed order",
            T.KEYS == ("density", "people", "farmland", "schools",
                       "hospitals", "roads", "access"))

print("\n[2] disabling a criterion renormalises rather than zero-filling")
sub = T.weights_for(["roads", "density", "people"])
check("subset sums to 1", sum(sub.values()), 1.0)
assert_true("canonical order survives an out-of-order request",
            list(sub) == ["density", "people", "roads"])
assert_true("dropping lower ranks raises the top weight",
            sub["density"] > T.roc_weights(7)[0])
check("three-criterion top weight", sub["density"], (1 + 0.5 + 1 / 3) / 3)

print("\n[3] percentile scoring: ties take the bottom, monotone transforms do not move it")
x = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 2.0, 50.0, 1000.0])
s = T.percentile_score(x)
assert_true("every empty cell scores exactly 0", bool(np.all(s[:4] == 0.0)))
check("the 5th of 8 values sits at 4/8", s[4], 0.5)
check("the largest value sits at 7/8", s[7], 0.875)
assert_true("order is preserved", bool(np.all(np.diff(s) >= 0)))
s_log = T.percentile_score(np.log1p(x))
assert_true("invariant under log1p -- calibration cannot move the ranking",
            bool(np.allclose(s, s_log)))
m = np.array([True] * 6 + [False] * 2)
s_m = T.percentile_score(x, mask=m)
check("masked cells score 0 and do not enter the reference set", s_m[7], 0.0)
check("in-mask top value is 5/6", s_m[5], 5 / 6)

print("\n[4] composite is a weighted mean of normalised layers")
layers = {"density": np.array([1.0, 0.0]), "people": np.array([0.0, 1.0])}
wts = T.weights_for(["density", "people"])
c = T.composite(layers, wts)
check("cell A takes the density weight", c[0], 0.75)
check("cell B takes the population weight", c[1], 0.25)
try:
    T.composite(layers, {"density": 0.5, "people": 0.2})
    assert_true("unnormalised weights are refused", False)
except ValueError:
    assert_true("unnormalised weights are refused", True)
try:
    T.composite({"density": np.array([1.0])}, wts)
    assert_true("a missing layer is refused, never treated as zero", False)
except KeyError:
    assert_true("a missing layer is refused, never treated as zero", True)

print("\n[5] terrain accessibility is a benefit term, bounded and multiplicative")
check("flat open ground is fully workable", T.accessibility(0.0, 0.0), 1.0)
check("at the slope limit nothing is workable", T.accessibility(T.SLOPE_LIMIT_DEG, 0.0), 0.0)
check("beyond the slope limit it stays at 0, never negative",
      T.accessibility(40.0, 0.0), 0.0)
check("half the cell under forest halves it", T.accessibility(0.0, 0.5), 0.5)
check("9 deg of slope with a third blocked",
      T.accessibility(9.0, 1 / 3), 0.5 * (2 / 3))

print("\n[6] display tiers are fixed, so a colour keeps its meaning")
check("a score below the first break is tier 0", T.tier_of(0.19), 0)
check("a score on a break takes the tier above", T.tier_of(0.20), 1)
check("the top of the scale is tier 5", T.tier_of(1.0), 5)
assert_true("six tiers, five breaks", len(T.TIER_BREAKS) == 5)

print("\n[7] ranking: a hole in one input layer must not drop a district")
regions = [
    {"name": "Hot",   "scores": {k: 0.95 for k in T.KEYS}},
    {"name": "Cold",  "scores": {k: 0.1 for k in T.KEYS}},
    {"name": "Holed", "scores": {**{k: 0.9 for k in T.KEYS}, "schools": None}},
]
ranked = T.rank_regions(regions, T.weights_for(T.KEYS))
assert_true("highest score first", [r["name"] for r in ranked][0] == "Hot")
assert_true("every district is ranked", len(ranked) == 3)
assert_true("the district with a missing layer is flagged partial",
            [r for r in ranked if r["name"] == "Holed"][0]["partial"])
assert_true("districts with complete data are not flagged",
            not [r for r in ranked if r["name"] == "Hot"][0]["partial"])
check("a partial score is renormalised over the layers it has, not zero-filled",
      [r for r in ranked if r["name"] == "Holed"][0]["score"], 0.9)
check("contributions sum to the score",
      sum(ranked[0]["contrib"].values()), ranked[0]["score"])
check("ranks are 1-based and dense", ranked[-1]["rank"], 3)

print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
raise SystemExit(1 if FAILS else 0)
