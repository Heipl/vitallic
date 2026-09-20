"""
benchmark.py - does the dipole fit actually sort mines from scrap?

Runs N randomised buried objects through the same simulated two-phone scan and
the SAME fit + classify code the dog runs, then scores the labels against truth.

It also scores the baseline that a plain metal detector already gives you:
threshold the peak signal. That baseline is handed its best possible threshold,
chosen in hindsight on this very data, so the comparison is deliberately unfair
in its favour. Beating it anyway is the point of the whole project.

    python benchmark.py                 # 300 trials, writes benchmark.png
    python benchmark.py --trials 60     # quick check

Why the two are not the same: peak signal confounds size with depth. A big
object 20 cm down and a small one 3 cm down give the same peak. The fit uses the
WIDTH of the anomaly and the low/high phone ratio to get depth first, and only
then converts strength into size.
"""
import argparse
import json
from multiprocessing import Pool

import numpy as np

import dipole

MINE, FRAG, NONE, RESCAN = dipole.MINE, dipole.FRAG, dipole.NONE, dipole.RESCAN
TRUTHS = (MINE, FRAG, NONE)

# Object populations. Ranges overlap in peak signal on purpose: that overlap is
# exactly the false-alarm problem deminers have.
MINE_MOMENT = (0.020, 0.120)   # A*m^2, steel-cased mine / UXO body
MINE_DEPTH = (0.05, 0.25)      # m, buried
FRAG_MOMENT = (0.001, 0.010)   # A*m^2, nails, keys, bolts, shrapnel
FRAG_DEPTH = (0.01, 0.10)      # m, scrap sits shallow


def make_trial(rng):
    """One randomised buried object plus the conditions it is scanned under."""
    truth = rng.choice(TRUTHS, p=[0.4, 0.4, 0.2])
    inc = np.radians(rng.uniform(63, 69))          # Boston-ish inclination
    e_hat = np.array([np.cos(inc), 0.0, -np.sin(inc)])

    if truth == MINE:
        moment = rng.uniform(*MINE_MOMENT)
        depth = rng.uniform(*MINE_DEPTH)
        # An intact steel body magnetises along the Earth's field.
        d = e_hat + rng.normal(0, 0.18, 3)
    elif truth == FRAG:
        moment = rng.uniform(*FRAG_MOMENT)
        depth = rng.uniform(*FRAG_DEPTH)
        d = rng.normal(0, 1, 3)                    # scrap points anywhere
    else:
        moment, depth, d = 0.0, 0.10, e_hat

    return dict(
        truth=truth, e_hat=e_hat, moment=moment, depth=depth,
        m_vec=moment * d / np.linalg.norm(d),
        # the drone only flags the spot approximately
        offset=rng.uniform(-0.04, 0.04, 2),
        # the dog's own magnetism, constant per phone during a scan
        dog=np.array([rng.uniform(0.5, 2.5), rng.uniform(-1.5, 1.5), rng.uniform(-1, 1)]),
        noise=rng.uniform(0.3, 0.8),               # uT per sample
        jitter=rng.uniform(0.005, 0.015),          # m, how sloppily the dog steps
        seed=int(rng.integers(1 << 30)),
    )


def scan(trial, h_low, h_high, pattern, points, step, samples):
    """Simulate one scan: returns sensor positions, both phones' totals, noise (uT)."""
    rng = np.random.default_rng(trial["seed"])
    e_hat = trial["e_hat"]
    earth = 51.0 * e_hat
    src = np.array([*trial["offset"], -trial["depth"]])

    xy = dipole.scan_offsets(pattern, points, step)
    xy = xy + rng.normal(0, trial["jitter"], xy.shape)   # the dog misses its mark

    totals, ses = [], []
    for h, dog_scale in ((h_low, 1.0), (h_high, 0.6)):
        obs = np.column_stack([xy, np.full(len(xy), h)])
        b = earth + trial["dog"] * dog_scale
        if trial["moment"] > 0:
            b = b + dipole.dipole_b(obs, src, trial["m_vec"])
        b = np.broadcast_to(b, (len(xy), 3))
        # `samples` readings per point, as read_pair() averages them on real phones
        draws = b[:, None, :] + rng.normal(0, trial["noise"], (len(xy), samples, 3))
        norms = np.linalg.norm(draws, axis=2)
        totals.append(np.median(norms, axis=1))
        ses.append(np.std(norms, axis=1) / np.sqrt(samples))
    return xy, totals[0], totals[1], float(np.median(np.maximum(*ses)))


def run_trial(args):
    """Full pipeline on one trial, including the automatic rescan field_scan does."""
    trial, cfg = args
    for attempt, samples in enumerate([cfg["samples"], 2 * cfg["samples"]]):
        xy, t_low, t_high, noise = scan(trial, cfg["h_low"], cfg["h_high"],
                                        cfg["pattern"], cfg["points"], cfg["step"], samples)
        fit = dipole.fit_dipole(xy, t_low, t_high, cfg["h_low"], cfg["h_high"], trial["e_hat"])
        label = dipole.classify(fit, cfg["threshold"], noise)
        if label != RESCAN:
            break
    return dict(truth=trial["truth"], label=label, p2p=fit.p2p_uT, noise=noise,
                moment=fit.moment, depth=fit.depth, r2=fit.r2,
                true_moment=trial["moment"], true_depth=trial["depth"],
                detected=label != NONE, rescanned=attempt > 0)


def baseline_labels(rows, cut):
    """What a plain metal detector gives you: threshold the peak signal."""
    return [NONE if not r["detected"] else (MINE if r["p2p"] >= cut else FRAG) for r in rows]


def best_baseline(rows):
    """Hand the baseline its best possible peak threshold, chosen on this data."""
    truths = [r["truth"] for r in rows]
    cuts = sorted({round(r["p2p"], 3) for r in rows})
    best = max(cuts, key=lambda c: sum(a == b for a, b in zip(baseline_labels(rows, c), truths)))
    return best, baseline_labels(rows, best)


def confusion(truths, labels):
    cols = [MINE, FRAG, NONE, RESCAN]
    return {t: {c: sum(1 for a, b in zip(truths, labels) if a == t and b == c) for c in cols}
            for t in TRUTHS}


def score(truths, labels):
    n = len(truths)
    correct = sum(a == b for a, b in zip(truths, labels))
    # The dangerous error: a mine called scrap or called empty. RESCAN is not a
    # miss, it is never treated as safe and still goes to a human.
    missed = sum(1 for a, b in zip(truths, labels) if a == MINE and b in (FRAG, NONE))
    false_alarm = sum(1 for a, b in zip(truths, labels) if a != MINE and b == MINE)
    n_not_mine = sum(1 for t in truths if t != MINE)
    return dict(accuracy=correct / n, missed_mines=missed,
                n_mines=sum(1 for t in truths if t == MINE),
                false_alarms=false_alarm, n_not_mine=n_not_mine,
                false_alarm_rate=false_alarm / n_not_mine if n_not_mine else 0.0)


def detected_score(rows, labels):
    """Score only the objects the phones could actually see. This separates what
    the CLASSIFIER gets wrong from what the SENSOR simply cannot reach."""
    pairs = [(r["truth"], l) for r, l in zip(rows, labels) if r["detected"]]
    if not pairs:
        return None
    correct = sum(a == b for a, b in pairs)
    fa = sum(1 for a, b in pairs if a != MINE and b == MINE)
    n_not_mine = sum(1 for a, _ in pairs if a != MINE)
    return dict(n=len(pairs), correct=correct, accuracy=correct / len(pairs),
                false_alarms=fa, n_not_mine=n_not_mine)


def depth_reach(moment, e_hat, h_low, points, step, floor_uT):
    """Deepest a dipole of this moment can sit and still clear the detection floor."""
    xy = dipole.scan_offsets("cross", points, step)
    obs = np.column_stack([xy, np.full(len(xy), h_low)])
    lo, hi = 0.01, 1.2
    for _ in range(40):
        mid = (lo + hi) / 2
        t = dipole.tfa(obs, np.array([0.0, 0.0, -mid]), moment * e_hat, e_hat)
        if np.ptp(t) >= floor_uT:
            lo = mid
        else:
            hi = mid
    return lo


def print_table(name, truths, labels):
    s = score(truths, labels)
    cm = confusion(truths, labels)
    print(f"\n{name}")
    header = "truth \\ called"
    print(f"  {header:<16}{MINE:>12}{FRAG:>10}{NONE:>11}{RESCAN:>9}")
    for t in TRUTHS:
        row = cm[t]
        print(f"  {t:<16}{row[MINE]:>12}{row[FRAG]:>10}{row[NONE]:>11}{row[RESCAN]:>9}")
    print(f"  accuracy {s['accuracy']*100:.1f}%   "
          f"mines missed {s['missed_mines']}/{s['n_mines']}   "
          f"false alarms {s['false_alarms']}/{s['n_not_mine']} "
          f"({s['false_alarm_rate']*100:.0f}% of non-mines)")
    return s


def save_plot(path, rows, threshold, cut):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {MINE: "#d62728", FRAG: "#7f7f7f", NONE: "#2ca02c"}
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8), sharey=False)

    ax = axes[0]
    for t in TRUTHS:
        pts = [r for r in rows if r["truth"] == t and r["detected"]]
        if pts:
            ax.scatter([r["p2p"] for r in pts], [r["true_depth"] * 100 for r in pts],
                       c=colors[t], s=26, alpha=.75, edgecolors="none", label=t)
    ax.axvline(cut, color="k", ls="--", lw=1)
    ax.annotate("best possible\npeak threshold", (cut, ax.get_ylim()[1]), xytext=(4, -10),
                textcoords="offset points", fontsize=8, va="top")
    ax.set_xscale("log")
    ax.set_xlabel("peak signal, low phone (uT p2p)")
    ax.set_ylabel("true depth (cm)")
    ax.set_title("What a metal detector sees:\nmines and scrap overlap")
    ax.legend(fontsize=8, loc="lower right")
    ax.grid(alpha=.3)

    ax = axes[1]
    for t in TRUTHS:
        pts = [r for r in rows if r["truth"] == t and r["detected"]]
        if pts:
            ax.scatter([r["moment"] for r in pts], [r["true_depth"] * 100 for r in pts],
                       c=colors[t], s=26, alpha=.75, edgecolors="none", label=t)
    ax.axvline(threshold, color="k", ls="--", lw=1)
    ax.annotate("MINE_SIZED\nthreshold", (threshold, ax.get_ylim()[1]), xytext=(4, -10),
                textcoords="offset points", fontsize=8, va="top")
    ax.set_xscale("log")
    ax.set_xlabel("fitted moment (A*m^2)  ~ amount of steel")
    ax.set_ylabel("true depth (cm)")
    ax.set_title("What the fit sees:\ndepth removed, size separates")
    ax.legend(fontsize=8, loc="lower right")
    ax.grid(alpha=.3)

    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trials", type=int, default=300)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--h-low", type=float, default=0.05)
    ap.add_argument("--h-high", type=float, default=0.35)
    ap.add_argument("--pattern", choices=["cross", "grid"], default="cross")
    ap.add_argument("--points", type=int, default=9)
    ap.add_argument("--step", type=float, default=0.05)
    ap.add_argument("--samples", type=int, default=40, help="readings averaged per point")
    ap.add_argument("--threshold", type=float, default=0.016, help="moment for MINE_SIZED")
    ap.add_argument("--jobs", type=int, default=0, help="0 = all cores")
    ap.add_argument("--out", default="benchmark.json")
    ap.add_argument("--plot", default="benchmark.png")
    a = ap.parse_args()

    rng = np.random.default_rng(a.seed)
    cfg = dict(h_low=a.h_low, h_high=a.h_high, pattern=a.pattern, points=a.points,
               step=a.step, samples=a.samples, threshold=a.threshold)
    trials = [(make_trial(rng), cfg) for _ in range(a.trials)]

    print(f"{a.trials} randomised objects, {a.pattern} scan of {a.points} points "
          f"at {a.step*100:.0f} cm, {a.samples} readings averaged per point")
    with Pool(a.jobs or None) as pool:
        rows = pool.map(run_trial, trials)

    truths = [r["truth"] for r in rows]
    cut, base = best_baseline(rows)
    s_base = print_table(f"BASELINE  peak-signal threshold at {cut:.2f} uT "
                         f"(best possible, chosen on this data)", truths, base)
    s_fit = print_table("VITALLIC   dipole fit on the same scans", truths,
                        [r["label"] for r in rows])

    for nm, lab in (("BASELINE", base), ("VITALLIC ", [r["label"] for r in rows])):
        d = detected_score(rows, lab)
        if d:
            print(f"  {nm} on the {d['n']} objects above the detection floor: "
                  f"{d['correct']}/{d['n']} correct ({d['accuracy']*100:.0f}%), "
                  f"{d['false_alarms']}/{d['n_not_mine']} scrap called a mine")

    inc = np.radians(66)
    e = np.array([np.cos(inc), 0.0, -np.sin(inc)])
    print("\nsensor reach (peak >= 1.0 uT floor), depth for a given amount of steel:")
    for mom, what in ((0.120, "large UXO"), (0.050, "steel pot / mine stand-in"),
                      (0.020, "small mine body"), (0.005, "keys / bolt")):
        print(f"  {what:<26} {mom:>6.3f} A*m^2  ->  {depth_reach(mom, e, a.h_low, a.points, a.step, 1.0)*100:5.1f} cm")

    det = [r for r in rows if r["truth"] != NONE and r["detected"]]
    if det:
        derr = np.array([r["depth"] - r["true_depth"] for r in det]) * 100
        print(f"\ndepth error on detected objects: median |err| {np.median(np.abs(derr)):.1f} cm, "
              f"RMS {np.sqrt(np.mean(derr**2)):.1f} cm  (n={len(det)})")
    print(f"rescans triggered: {sum(r['rescanned'] for r in rows)}/{len(rows)}")

    save_plot(a.plot, rows, a.threshold, cut)
    json.dump({"config": {**cfg, "trials": a.trials, "seed": a.seed},
               "baseline": {"cut_uT": cut, **s_base}, "vitallic": s_fit,
               "rows": rows}, open(a.out, "w"), indent=1, default=float)
    print(f"\nplot: {a.plot}   data: {a.out}")
    print(f"\nHEADLINE: peak threshold misses {s_base['missed_mines']}/{s_base['n_mines']} mines "
          f"and false-alarms on {s_base['false_alarm_rate']*100:.0f}% of scrap; "
          f"the fit misses {s_fit['missed_mines']}/{s_fit['n_mines']} "
          f"and false-alarms on {s_fit['false_alarm_rate']*100:.0f}%.")


if __name__ == "__main__":
    main()
