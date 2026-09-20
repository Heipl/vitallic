"""
field_scan.py - Vitallic: the dog visits every "drone-flagged" spot, scans it with the
two-phone gradiometer, fits a magnetic dipole, and sorts it into
MINE_SIZED / FRAGMENT / NO_TARGET / RESCAN. Only MINE_SIZED spots go to a human.

Arena frame: origin = dog body centre at start, +x = the direction the dog faces
(it never turns), +y = left. Phones sit on a boom `--boom` metres ahead of the
body centre, low phone at --h-low, high phone at --h-high above the ground.

Examples
  python field_scan.py --sim                                   # no hardware at all
  python field_scan.py --manual --low http://IP1:8080 --high http://IP2:8080
  python field_scan.py --low http://IP1:8080 --high http://IP2:8080 --dimos /path/to/dimos
  add --calibrate to print moments for known objects and pick --threshold
"""
import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

import dipole
from bayes import REGIONS_M2, SurveyPosterior
from geo import ArenaGeo
from phones import PhyphoxPhone, phone_to_arena, read_pair

SKIPPED = "SKIPPED"  # no safe path to this spot; never means "clear"

# ---------------------------------------------------------------- status server


class StatusBoard:
    """Live server for the scan.

      GET /state  -> plain text state       (the UNO Q LED display polls this)
      GET /api    -> JSON: state, results with lat/lon, Bayesian posterior
      GET /       -> live_map.html          (map + posterior, polls /api)
    """

    def __init__(self, port, geo=None, posterior=None, regions=None):
        self.state, self.spot, self.results = "IDLE", "", []
        self.geo, self.posterior, self.regions = geo, posterior, regions
        board = self
        page = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_map.html")

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith("/state"):
                    body, ctype = board.state.encode(), "text/plain"
                elif self.path.startswith("/api"):
                    body, ctype = json.dumps(board.payload()).encode(), "application/json"
                else:
                    try:
                        with open(page, "rb") as fh:
                            body = fh.read()
                        ctype = "text/html; charset=utf-8"
                    except OSError:
                        body = b"live_map.html not found next to field_scan.py"
                        ctype = "text/plain"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def payload(self):
        out = {"state": self.state, "spot": self.spot, "results": self.results}
        if self.geo is not None:
            out["geo"] = self.geo.as_dict()
        if self.posterior is not None:
            out["bayes"] = self.posterior.snapshot(self.regions)
        return out

    def set(self, state, spot=""):
        self.state, self.spot = state, spot

# ---------------------------------------------------------------- safety


class Footprint:
    """Where the dog's feet can land, relative to the body centre, plus a margin.
    Rule: no flagged spot may ever be inside this box - the dog never steps on
    anything that has not been cleared."""

    def __init__(self, half_len, half_wid, margin):
        self.hl, self.hw, self.m = half_len + margin, half_wid + margin, margin

    def hits(self, body_xy, spots_xy):
        d = np.abs(spots_xy - body_xy)
        return np.any((d[:, 0] <= self.hl) & (d[:, 1] <= self.hw))

    def leg_clear(self, a, b, spots_xy, n=25):
        return not any(self.hits(a + (b - a) * t, spots_xy) for t in np.linspace(0, 1, n))


def plan_move(body_now, body_target, spots_xy, fp):
    """L-shaped path (x then y, or y then x) that keeps every flagged spot outside
    the footprint. Returns list of (dx, dy) legs or raises if blocked."""
    corner_xy = [np.array([body_target[0], body_now[1]]), np.array([body_now[0], body_target[1]])]
    for corner in corner_xy:
        if fp.leg_clear(body_now, corner, spots_xy) and fp.leg_clear(corner, body_target, spots_xy):
            return [tuple(corner - body_now), tuple(body_target - corner)]
    raise RuntimeError(f"no safe path from {body_now.round(2)} to {body_target.round(2)} - "
                       "reposition flagged spots or move the dog by hand")

# ---------------------------------------------------------------- map


def save_map(path, spots, results, body_start):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = {dipole.MINE: "#d62728", dipole.FRAG: "#7f7f7f", dipole.NONE: "#2ca02c",
              dipole.RESCAN: "#ff7f0e", "CALIBRATION": "#1f77b4", SKIPPED: "#9467bd"}
    fig, ax = plt.subplots(figsize=(6, 6))
    done = {r["id"]: r for r in results}
    for s in spots:
        r = done.get(s["id"])
        c = colors.get(r["label"], "k") if r else "#cccccc"
        ax.scatter(s["y"], s["x"], s=260, c=c, edgecolors="k", zorder=3)
        if not r:
            txt = s["id"]
        elif r["label"] in (dipole.NONE, dipole.RESCAN, SKIPPED):
            txt = f'{s["id"]} {r["label"]}'
        else:
            txt = f'{s["id"]} {r["label"]}\n~{r["fit"]["depth"]*100:.0f} cm deep'
        ax.annotate(txt, (s["y"], s["x"]), xytext=(0, -16), textcoords="offset points",
                    fontsize=8, ha="center", va="top")
    ax.scatter(body_start[1], body_start[0], marker="s", s=200, c="k")
    ax.annotate("dog start", (body_start[1], body_start[0]), xytext=(10, -12),
                textcoords="offset points", fontsize=8)
    ax.set_xlabel("y  (m, left +)")
    ax.set_ylabel("x  (m, forward +)")
    ax.invert_xaxis()  # so "left" is on the left when looking forward
    ax.set_aspect("equal")
    ax.margins(0.2)
    ax.grid(alpha=.3)
    ax.set_title("Vitallic: flagged spots, classified")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)

# ---------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spots", default="flagged_spots.json")
    ap.add_argument("--low", help="phyphox URL of the LOW phone")
    ap.add_argument("--high", help="phyphox URL of the HIGH phone")
    ap.add_argument("--sim", action="store_true", help="simulated world, phones and dog")
    ap.add_argument("--manual", action="store_true", help="handheld rig instead of the dog")
    ap.add_argument("--h-low", type=float, default=0.05, help="low phone height above ground (m)")
    ap.add_argument("--h-high", type=float, default=0.35, help="high phone height above ground (m)")
    ap.add_argument("--boom", type=float, default=0.65, help="phones ahead of dog body centre (m)")
    ap.add_argument("--foot-half-len", type=float, default=0.25)
    ap.add_argument("--foot-half-wid", type=float, default=0.18)
    ap.add_argument("--margin", type=float, default=0.10)
    ap.add_argument("--pattern", choices=["cross", "grid"], default="cross")
    ap.add_argument("--points", type=int, default=9, help="points per arm/row")
    ap.add_argument("--step", type=float, default=0.05, help="spacing between scan points (m)")
    ap.add_argument("--avg", type=float, default=0.8, help="seconds per reading (adaptive, up to 4 s)")
    ap.add_argument("--threshold", type=float, default=0.016, help="moment (A*m^2) for MINE_SIZED")
    ap.add_argument("--calibrate", action="store_true", help="just print fits for known objects")
    ap.add_argument("--skill", default="precise_move",
                    help="dimOS move skill. Default precise_move bypasses the 20 cm "
                         "planner trap (requires: dimos run vitallic-dimos.scan). "
                         "Pass move_to to use the stock planner skill.")
    ap.add_argument("--observe-skill", default="observe")
    ap.add_argument("--dimos", default="dimos",
                    help="path to the dimos binary, e.g. "
                         "/root/dimensional-applications/.venv/bin/dimos")
    ap.add_argument("--allow-small-moves", action="store_true",
                    help="permit legs below dimOS's 20 cm arrival tolerance. Only pass this if "
                         "tools/min_move_test.py proved your dog really executes them.")
    ap.add_argument("--status-port", type=int, default=8765)
    ap.add_argument("--lat", type=float, default=42.3601,
                    help="latitude of the arena origin (dog start), for the live map")
    ap.add_argument("--lon", type=float, default=-71.0942,
                    help="longitude of the arena origin")
    ap.add_argument("--heading", type=float, default=0.0,
                    help="compass bearing of arena +x: 0=north, 90=east")
    ap.add_argument("--out", default="results.json")
    ap.add_argument("--map", default="results_map.png")
    a = ap.parse_args()

    spots = json.load(open(a.spots))["spots"]
    spots_xy = np.array([[s["x"], s["y"]] for s in spots])
    boom = np.array([a.boom, 0.0])
    body = np.zeros(2)                  # dog body centre, arena frame
    sensor = body + boom
    fp = Footprint(a.foot_half_len, a.foot_half_wid, a.margin)
    if fp.hits(body, spots_xy):
        raise SystemExit("a flagged spot is under the dog's starting position")

    if a.sim:
        from sim import SimMover, SimPhone, SimWorld
        world = SimWorld(spots, a.h_low, a.h_high, sensor)
        phones, mover = [SimPhone(world, 0), SimPhone(world, 1)], SimMover(world)
    else:
        if not (a.low and a.high):
            raise SystemExit("give --low and --high phone URLs (or --sim)")
        phones = [PhyphoxPhone(a.low), PhyphoxPhone(a.high)]
        if a.manual:
            from robot import ManualMover
            mover = ManualMover()
        else:
            from robot import DimosMover
            # move_to reports "goal reached" for any step shorter than the planner's
            # 0.20 m arrival tolerance, without moving. precise_move does not go
            # through the planner, so the 5 cm cross is allowed. See DIMOS_PORT.md.
            if (a.skill in DimosMover.PLANNER_SKILLS
                    and a.step < DimosMover.GOAL_TOLERANCE_M
                    and not a.allow_small_moves):
                raise SystemExit(
                    f"--step {a.step:.2f} m is below dimOS's "
                    f"{DimosMover.GOAL_TOLERANCE_M:.2f} m arrival tolerance, so "
                    f"{a.skill} would never actually move between scan points.\n"
                    "Default is --skill precise_move: start "
                    "`dimos run vitallic-dimos.scan --robot-ip <DOG_IP>` and leave "
                    "--skill alone. If you insist on move_to, run "
                    "`python tools/min_move_test.py --skill move_to` first.")
            mover = DimosMover(skill=a.skill, observe_skill=a.observe_skill, dimos=a.dimos,
                               allow_small_moves=a.allow_small_moves)
    try:
        mover.preflight()   # fail now, not halfway through the demo
    except RuntimeError as exc:
        raise SystemExit(f"preflight failed: {exc}")
    for p in phones:
        try:
            p.start()
        except Exception as exc:
            raise SystemExit(f"phone {getattr(p, 'url', p)} did not answer: {exc}\n"
                             "Check phyphox is open on Magnetometer with remote access on, "
                             "and that both phones and this laptop are on ONE hotspot.")

    geo = ArenaGeo(a.lat, a.lon, a.heading)
    posterior = SurveyPosterior()
    # Ground each scan clears: the cross/grid footprint plus a half-step margin.
    span = (a.points - 1) * a.step + a.step
    spot_area = span * span if a.pattern == "grid" else span * a.step * 2
    board = StatusBoard(a.status_port, geo=geo, posterior=posterior, regions=REGIONS_M2)
    print(f"status server on :{a.status_port}  (UNO Q polls /state)")
    print(f"LIVE MAP  ->  http://localhost:{a.status_port}/")

    # Baseline over clean ground: gives the Earth-field direction for the fit.
    board.set("BASELINE")
    (v_low, t_low0, _), _ = read_pair(phones, 1.5)
    e_hat = phone_to_arena(v_low)
    e_hat /= np.linalg.norm(e_hat)
    print(f"baseline {t_low0:.1f} uT, field direction (arena) {e_hat.round(2)}")

    def go_sensor(target_sensor):
        nonlocal body, sensor
        target_body = target_sensor - boom
        for dx, dy in plan_move(body, target_body, spots_xy, fp):
            mover.move(dx, dy, target=body + np.array([dx, dy]) + boom)
            body = body + np.array([dx, dy])
        sensor = body + boom

    def scan(center, avg):
        xy, tl, th, se = [], [], [], []
        for off in dipole.scan_offsets(a.pattern, a.points, a.step):
            go_sensor(center + off)
            (_, t1, s1), (_, t2, s2) = read_pair(phones, avg)
            xy.append(sensor.copy()); tl.append(t1); th.append(t2); se.append(max(s1, s2))
        return np.array(xy), np.array(tl), np.array(th), float(np.median(se))

    results = []
    for s in spots:
        center = np.array([s["x"], s["y"]])
        label = None
        t0 = time.time()
        try:
            for attempt, avg in enumerate([a.avg, 2 * a.avg]):  # one automatic rescan
                board.set("SCAN", s["id"])
                print(f'\n[{s["id"]}] scanning at x={center[0]:.2f} y={center[1]:.2f}'
                      + (" (rescan, longer averaging)" if attempt else ""))
                t0 = time.time()
                xy, tl, th, noise = scan(center, avg)
                fit = dipole.fit_dipole(xy, tl, th, a.h_low, a.h_high, e_hat)
                label = "CALIBRATION" if a.calibrate else dipole.classify(fit, a.threshold, noise)
                if label != dipole.RESCAN:
                    break
        except RuntimeError as exc:
            # A blocked path must not end the run: skip this spot and carry on.
            # SKIPPED is never "clear" - it still goes to a human.
            print(f'[{s["id"]}] SKIPPED: {exc}')
            board.set(SKIPPED, s["id"])
            slat, slon = geo.to_latlon(center[0], center[1])
            results.append({"id": s["id"], "label": SKIPPED, "reason": str(exc),
                            "lat": slat, "lon": slon,
                            "scan_seconds": round(time.time() - t0, 1)})
            board.results = [{k: v for k, v in r.items() if k != "raw"} for r in results]
            json.dump(results, open(a.out, "w"), indent=1)
            save_map(a.map, spots, results, np.zeros(2))
            continue
        board.set(label, s["id"])
        photo = mover.observe() if label in (dipole.MINE, dipole.RESCAN) else ""
        # Fit the object where it actually is, not where the drone guessed.
        lat, lon = geo.to_latlon(fit.x, fit.y)
        rec = {"id": s["id"], "label": label, "noise_uT": noise, "fit": fit.as_dict(),
               "lat": lat, "lon": lon,
               "scan_seconds": round(time.time() - t0, 1), "observe": photo,
               "raw": {"xy": xy.tolist(), "t_low": tl.tolist(), "t_high": th.tolist()}}
        results.append(rec)
        # Evidence for the live posterior. --calibrate is a bench measurement,
        # not a survey, so it must not pollute the contamination estimate.
        if not a.calibrate:
            posterior.observe(label == dipole.MINE, area_m2=spot_area)
        board.results = [{k: v for k, v in r.items() if k != "raw"} for r in results]
        if label == dipole.NONE:
            print(f'[{s["id"]}] NO_TARGET: signal {fit.p2p_uT:.2f} uT p2p vs noise {noise:.2f} uT')
        else:
            print(f'[{s["id"]}] {label}: depth {fit.depth*100:.1f} cm, moment {fit.moment:.4f} A*m^2, '
                  f'p2p {fit.p2p_uT:.2f} uT, noise {noise:.2f} uT, fit r2 {fit.r2:.2f}, '
                  f'remanence {fit.remanence_angle_deg:.0f} deg')
        json.dump(results, open(a.out, "w"), indent=1)
        save_map(a.map, spots, results, np.zeros(2))

    # back to start along a safe path, then summary
    board.set("DONE")
    try:
        go_sensor(boom)
    except RuntimeError as exc:
        print(f"could not walk back to the start ({exc}) - carry the dog back")
    n_mine = sum(r["label"] == dipole.MINE for r in results)
    n_skip = sum(r["label"] == SKIPPED for r in results)
    print(f"\nDone. {len(results)} spots checked, {n_mine} sent to a human"
          + (f", {n_skip} skipped (no safe path - also for a human)" if n_skip else "")
          + f". Map: {a.map}, data: {a.out}")
    if a.sim:
        print("sim truth:", {s["id"]: s.get("sim_truth", {}).get("label", "empty") for s in spots})


if __name__ == "__main__":
    main()
