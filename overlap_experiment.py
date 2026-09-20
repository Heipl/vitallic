"""
overlap_experiment.py - stress-test the headline number.

benchmark.py draws mine moments from (0.020, 0.120) and fragment moments from
(0.001, 0.010), while the MINE_SIZED threshold sits at 0.016 - in the EMPTY GAP
between the two populations. No simulated object lands near the decision boundary,
which flatters the 99%.

Real scrap is not so tidy: a big chunk of shrapnel or a steel plate fragment can
carry as much iron as a small mine body. This script re-runs the same pipeline with
populations that genuinely OVERLAP across the threshold and asks:

  1. how much of the 99% was the gap?
  2. does the dipole fit still beat the peak-signal baseline by a wide margin?

(2) is the claim that actually matters. Under real overlap NO moment-based classifier
can be perfect - that is a physical limit, not a bug. What must survive is the
SEPARATION between the fit and the thing a metal detector already gives you.

Run:  python overlap_experiment.py
"""
import sys
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, ".")
import benchmark as B

# (name, mine moment range, fragment moment range, note)
SCENARIOS = [
    ("as shipped (gap at threshold)", (0.020, 0.120), (0.001, 0.010),
     "no object near the 0.016 boundary"),
    ("touching at the threshold", (0.016, 0.120), (0.001, 0.016),
     "populations meet exactly at 0.016"),
    ("realistic overlap", (0.010, 0.120), (0.001, 0.030),
     "big shrapnel can out-mass a small mine"),
    ("severe overlap", (0.006, 0.120), (0.001, 0.060),
     "worst case: heavy scrap is common"),
]


def run(trials, mine_rng, frag_rng, seed, cfg):
    B.MINE_MOMENT, B.FRAG_MOMENT = mine_rng, frag_rng
    rng = np.random.default_rng(seed)
    trial_list = [(B.make_trial(rng), cfg) for _ in range(trials)]
    with Pool() as pool:
        rows = pool.map(B.run_trial, trial_list)
    truths = [r["truth"] for r in rows]
    cut, base_labels = B.best_baseline(rows)
    fit_labels = [r["label"] for r in rows]
    return rows, truths, base_labels, fit_labels, cut


def main():
    trials = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    cfg = dict(h_low=0.05, h_high=0.35, pattern="cross", points=9, step=0.05,
               samples=40, threshold=0.016)
    print(f"{trials} trials per scenario, MINE_SIZED threshold fixed at "
          f"{cfg['threshold']} A*m^2\n")
    print(f"{'scenario':<32} {'fit':>16} {'baseline':>16}   {'gain':>6}")
    print(f"{'':<32} {'correct  FA':>16} {'correct  FA':>16}")
    print("-" * 78)

    results = []
    for name, mine_rng, frag_rng, note in SCENARIOS:
        rows, truths, base_labels, fit_labels, cut = run(trials, mine_rng, frag_rng, 7, cfg)
        d_fit = B.detected_score(rows, fit_labels)
        d_base = B.detected_score(rows, base_labels)
        if not d_fit or not d_base:
            print(f"{name:<32}  (nothing above the detection floor)")
            continue
        gain = d_fit["accuracy"] - d_base["accuracy"]
        print(f"{name:<32} {d_fit['correct']:>4}/{d_fit['n']:<3} "
              f"{d_fit['false_alarms']:>2}/{d_fit['n_not_mine']:<3} "
              f"{d_base['correct']:>6}/{d_base['n']:<3} "
              f"{d_base['false_alarms']:>2}/{d_base['n_not_mine']:<3}   "
              f"{gain*100:>+5.0f}pp")
        print(f"{'  ' + note:<32}")
        results.append((name, d_fit, d_base, gain))

    print("\n" + "=" * 78)
    shipped = results[0] if results else None
    worst = min(results, key=lambda r: r[1]["accuracy"]) if results else None
    if shipped and worst:
        print(f"as shipped:      fit {shipped[1]['accuracy']*100:.0f}% vs "
              f"baseline {shipped[2]['accuracy']*100:.0f}%  "
              f"({shipped[3]*100:+.0f}pp)")
        print(f"worst overlap:   fit {worst[1]['accuracy']*100:.0f}% vs "
              f"baseline {worst[2]['accuracy']*100:.0f}%  "
              f"({worst[3]*100:+.0f}pp)   [{worst[0]}]")
        drop = (shipped[1]["accuracy"] - worst[1]["accuracy"]) * 100
        print(f"\nthe gap at the threshold is worth about {drop:.0f} percentage points "
              f"of the headline accuracy.")
        if worst[3] > 0.10:
            print("The SEPARATION from the peak-signal baseline survives overlap "
                  f"({worst[3]*100:+.0f}pp in the worst case), so the central claim holds; "
                  "only the absolute 99% is optimistic.")
        else:
            print("WARNING: the advantage over the baseline COLLAPSES under overlap. "
                  "The headline claim depends on the population gap and should not be "
                  "presented as-is.")


if __name__ == "__main__":
    main()
