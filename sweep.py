"""sweep.py - walk the rig around and watch the map fill in.

field_scan.py visits a fixed list of drone-flagged spots and does a stationary
17-point cross at each. That is the rigorous mode. This is the other one: you
carry the two-phone boom and just walk, and anomalies are picked up as you pass
over them. It is how a hand-held demining survey actually works, and it is what
you want in front of an audience.

HOW IT KEEPS THE PROJECT'S CLAIM HONEST
The whole thesis is that a dipole FIT beats a peak-signal threshold. So this does
not classify on peak height. It logs a continuous track of (position, low, high),
and when an anomaly triggers it runs dipole.fit_dipole over the window of track
around the peak - the same fit, the same classifier, the same thresholds as the
stationary mode. A line of samples constrains depth through the WIDTH of the
anomaly, which is the part peak height throws away.

POSITION IS DEAD RECKONING, AND THAT IS A REAL LIMIT
Without the dog there is no odometry, so position comes from elapsed time along a
declared serpentine at a declared walking speed. Real hand-held surveys log the
same way. It is good enough to place pins and to measure area swept; it is not
survey-grade, and the map labels it as such. Walk at a steady pace and start each
lane on the beat.

    python sweep.py --low http://LOW:8080 --high http://HIGH:8080 \
        --lat 42.3601 --lon -71.0942 --heading 0

    then open http://localhost:8765/

Tuning for a demo: --trigger sets how big an anomaly has to be to count, and
--threshold is the usual moment cut between MINE_SIZED and FRAGMENT.
"""
from __future__ import annotations

import argparse
import math
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

import dipole
from bayes import REGIONS_M2, SurveyPosterior
from field_scan import StatusBoard
from geo import ArenaGeo
from phones import PhyphoxPhone, phone_to_arena


class Serpentine:
    """Dead-reckoned position along a back-and-forth sweep pattern."""

    def __init__(self, lane_len, lane_step, speed):
        self.lane_len, self.lane_step, self.speed = lane_len, lane_step, speed
        self.t0 = time.monotonic()

    def at(self, now=None):
        """Position (x, y) in metres at time `now`, walking lanes along +x."""
        t = (now or time.monotonic()) - self.t0
        d = t * self.speed                      # total distance walked
        lane = int(d // self.lane_len)
        along = d - lane * self.lane_len
        x = along if lane % 2 == 0 else self.lane_len - along   # boustrophedon
        return x, -lane * self.lane_step        # lanes march to the right (-y)

    def distance(self, now=None):
        return ((now or time.monotonic()) - self.t0) * self.speed


class Tracker:
    """Rolling-baseline anomaly detector over a continuous walk.

    The baseline is an exponential moving average, frozen while an event is in
    progress so a real anomaly is not absorbed into it. This is not optional
    polish: an iPhone magnetometer was measured drifting several uT over ~10 s as
    iOS recalibrated, which a fixed baseline would read as a target.
    """

    def __init__(self, tau=6.0, trigger=1.5, release=0.6, min_samples=4):
        self.tau, self.trigger, self.release = tau, trigger, release
        self.min_samples = min_samples
        self.bl = self.bh = None
        self.track = []            # (x, y, low, high) for the whole run
        self.event = None          # samples of the anomaly in progress

    def update(self, x, y, low, high, dt):
        if self.bl is None:
            self.bl, self.bh = low, high
        a = min(1.0, dt / self.tau)
        dl, dh = low - self.bl, high - self.bh
        hot = abs(dl) > self.trigger

        if not hot and self.event is None:
            self.bl += a * (low - self.bl)      # only track drift when quiet
            self.bh += a * (high - self.bh)

        self.track.append((x, y, low, high))

        if hot and self.event is None:
            self.event = {"start": len(self.track) - 1, "peak": abs(dl)}
        elif self.event is not None:
            self.event["peak"] = max(self.event["peak"], abs(dl))
            if abs(dl) < self.release:
                ev, self.event = self.event, None
                n = len(self.track) - ev["start"]
                if n >= self.min_samples:
                    return ev                    # a finished anomaly
        return None


def fit_event(track, ev, h_low, h_high, e_hat, pad=6):
    """Run the real dipole fit over the stretch of track containing the anomaly."""
    lo = max(0, ev["start"] - pad)
    hi = min(len(track), ev["start"] + pad + 40)
    seg = track[lo:hi]
    if len(seg) < 8:
        return None
    xy = np.array([[s[0], s[1]] for s in seg])
    tl = np.array([s[2] for s in seg])
    th = np.array([s[3] for s in seg])
    # A walked line has almost no spread across track; nudge the search box out so
    # the optimiser is not pinned against a degenerate bound.
    if np.ptp(xy[:, 1]) < 0.02:
        xy = xy + np.column_stack([np.zeros(len(xy)),
                                   np.linspace(-0.01, 0.01, len(xy))])
    try:
        # align=True: the path is a line, which cannot constrain a free moment
        # VECTOR. Forcing the moment parallel to the Earth's field (induced
        # magnetisation) keeps the MAGNITUDE identifiable, and magnitude is what
        # MINE_SIZED is decided on.
        return dipole.fit_dipole(xy, tl, th, h_low, h_high, e_hat, align=True), xy
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--low", required=True, help="phyphox URL of the LOW phone")
    ap.add_argument("--high", required=True, help="phyphox URL of the HIGH phone")
    ap.add_argument("--lat", type=float, default=42.3601)
    ap.add_argument("--lon", type=float, default=-71.0942)
    ap.add_argument("--heading", type=float, default=0.0,
                    help="compass bearing of the first lane: 0=north, 90=east")
    ap.add_argument("--h-low", type=float, default=0.05)
    ap.add_argument("--h-high", type=float, default=0.35)
    ap.add_argument("--speed", type=float, default=0.5, help="walking speed, m/s")
    ap.add_argument("--lane-len", type=float, default=6.0, help="lane length, m")
    ap.add_argument("--lane-step", type=float, default=0.5, help="lane spacing, m")
    ap.add_argument("--swath", type=float, default=0.5,
                    help="width of ground the boom actually clears, m")
    ap.add_argument("--trigger", type=float, default=1.5,
                    help="uT above baseline that starts an event")
    ap.add_argument("--threshold", type=float, default=0.016,
                    help="fitted moment (A*m^2) for MINE_SIZED")
    ap.add_argument("--rate", type=float, default=5.0, help="samples per second")
    ap.add_argument("--merge-dist", type=float, default=0.35,
                    help="fits closer together than this are the SAME object. A dipole "
                         "anomaly has a positive and a negative lobe, so one pass over "
                         "one object triggers twice; without merging they count as two "
                         "mines and inflate the posterior.")
    ap.add_argument("--status-port", type=int, default=8765)
    a = ap.parse_args()

    low, high = PhyphoxPhone(a.low), PhyphoxPhone(a.high)
    for p in (low, high):
        try:
            p.start()
        except Exception as exc:
            raise SystemExit(f"{p.url} did not answer: {exc}\n"
                             "phyphox must be open on Magnetometer, playing, with "
                             "remote access on, and on the same network as this laptop.")
    pool = ThreadPoolExecutor(2)

    geo = ArenaGeo(a.lat, a.lon, a.heading)
    posterior = SurveyPosterior()
    board = StatusBoard(a.status_port, geo=geo, posterior=posterior, regions=REGIONS_M2)
    print(f"LIVE MAP  ->  http://localhost:{a.status_port}/")

    def read():
        f1, f2 = pool.submit(low.latest), pool.submit(high.latest)
        return (float(np.linalg.norm(f1.result())),
                float(np.linalg.norm(f2.result())), f1.result())

    board.set("BASELINE")
    print("baselining 3 s - hold still, nothing ferrous near the rig ...")
    vecs = []
    t0 = time.time()
    while time.time() - t0 < 3:
        try:
            _, _, v = read()
            vecs.append(v)
        except Exception:
            pass
        time.sleep(0.15)
    if not vecs:
        raise SystemExit("no readings from the phones")
    e_hat = phone_to_arena(np.median(np.array(vecs), axis=0))
    e_hat = e_hat / np.linalg.norm(e_hat)
    print(f"field direction (arena) {e_hat.round(2)}")

    path = Serpentine(a.lane_len, a.lane_step, a.speed)
    trk = Tracker(trigger=a.trigger)
    results, n_found, last_area = [], 0, 0.0
    period = 1.0 / a.rate
    print("WALK NOW. Steady pace, lanes along +x. Ctrl-C to stop.\n")
    board.set("SCAN")

    try:
        prev = time.monotonic()
        while True:
            try:
                l, h, _ = read()
            except Exception:
                time.sleep(period)
                continue
            now = time.monotonic()
            dt, prev = now - prev, now
            x, y = path.at(now)

            # Area swept is distance walked times the boom's effective swath.
            area = path.distance(now) * a.swath
            posterior.area_m2 = area

            ev = trk.update(x, y, l, h, dt)
            if ev is None:
                continue

            out = fit_event(trk.track, ev, a.h_low, a.h_high, e_hat)
            if out is None:
                continue
            fit, xy = out
            noise = 0.15
            label = dipole.classify(fit, a.threshold, noise)
            if label == dipole.NONE:
                continue

            fx = float(np.clip(fit.x, xy[:, 0].min(), xy[:, 0].max()))
            fy = float(np.clip(fit.y, xy[:, 1].min() - 0.3, xy[:, 1].max() + 0.3))

            # Same object seen twice? Keep the stronger fit, do not double-count.
            dup = next((r for r in results
                        if math.hypot(r["fit"]["x"] - fx, r["fit"]["y"] - fy)
                        < a.merge_dist), None)
            if dup is not None:
                if fit.r2 > dup["fit"]["r2"]:
                    dup["fit"] = fit.as_dict()
                    dup["peak_uT"] = round(max(dup["peak_uT"], ev["peak"]), 2)
                    board.results = list(results)
                print(f"      (merged into {dup['id']}: same object, other lobe)")
                continue

            n_found += 1
            lat, lon = geo.to_latlon(fx, fy)
            rec = {"id": f"S{n_found}", "label": label, "lat": lat, "lon": lon,
                   "noise_uT": noise, "fit": fit.as_dict(),
                   "peak_uT": round(ev["peak"], 2)}
            results.append(rec)
            posterior.observe(label == dipole.MINE)
            board.results = list(results)
            board.set(label, rec["id"])

            hr = posterior.hit_rate()
            print(f"[{rec['id']}] {label:11s} peak {ev['peak']:5.2f} uT  "
                  f"depth {fit.depth*100:5.1f} cm  moment {fit.moment:.4f}  "
                  f"| {posterior.n_mines}/{posterior.n_spots} mines, "
                  f"P(mine)={hr['mean']*100:.0f}% [{hr['lo']*100:.0f}-{hr['hi']*100:.0f}]")
            time.sleep(period)
    except KeyboardInterrupt:
        board.set("DONE")
        d = posterior.density()
        print(f"\nStopped. {posterior.n_spots} anomalies, {posterior.n_mines} mine-sized, "
              f"{posterior.area_m2:.1f} m^2 swept.")
        print(f"density {d['per_hectare_mean']:.0f}/ha "
              f"[{d['per_hectare_lo']:.0f}, {d['per_hectare_hi']:.0f}]")
        for r in posterior.snapshot(REGIONS_M2)["regions"]:
            print(f"  {r['region']:38s} {r['expected']:>14,.0f}  "
                  f"[{r['lo']:,.0f} .. {r['hi']:,.0f}]")


if __name__ == "__main__":
    main()
