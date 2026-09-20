"""
dipole.py - magnetic dipole inversion for Vitallic's two-phone gradiometer.

Model: a compact buried steel object behaves like a magnetic dipole with moment
m (A*m^2) sitting at (x0, y0, -depth). Each phone reports the total field
magnitude. For small anomalies |B_earth + b| ~= |B_earth| + b . e_hat, so what we
fit is b . e_hat (the "total-field anomaly"), which does not depend on how the
phone is rotated.

Why the fit matters: a big deep object and a small shallow one can give the
same peak reading. The WIDTH of the anomaly (and the ratio between the low and
high phone) gives the depth; once depth is known, the strength gives the size
(moment ~ amount of steel).

Run `python dipole.py` for a synthetic self-test.
"""
from dataclasses import dataclass, asdict
import numpy as np
from scipy.optimize import least_squares

MU0_4PI = 1e-7  # T*m/A

MINE, FRAG, RESCAN, NONE = "MINE_SIZED", "FRAGMENT", "RESCAN", "NO_TARGET"


def dipole_b(obs, src, m):
    """Field (uT) of dipole m (A*m^2) at src, evaluated at obs points (N,3), metres."""
    r = obs - src
    rn = np.linalg.norm(r, axis=1)
    rhat = r / rn[:, None]
    mdot = rhat @ m
    b = MU0_4PI * (3.0 * mdot[:, None] * rhat - m[None, :]) / rn[:, None] ** 3
    return b * 1e6


def tfa(obs, src, m, e_hat):
    """Total-field anomaly (uT): dipole field projected on the Earth-field direction."""
    return dipole_b(obs, src, m) @ e_hat


def scan_offsets(pattern="cross", points=9, step=0.05):
    """Sensor offsets (metres) around a flagged spot, in visiting order."""
    k = np.arange(points) - (points - 1) / 2
    if pattern == "cross":
        arm_x = [(s * step, 0.0) for s in k]
        arm_y = [(0.0, s * step) for s in k if s != 0]
        return np.array(arm_x + arm_y)
    if pattern == "grid":  # serpentine so the dog never backtracks far
        pts = []
        for i, sy in enumerate(k):
            row = k if i % 2 == 0 else k[::-1]
            pts += [(sx * step, sy * step) for sx in row]
        return np.array(pts)
    raise ValueError(f"unknown pattern {pattern}")


def _design(xy, h_low, h_high, src, e_hat, align=False):
    """Columns: anomaly for unit moment along x, y, z, then offset(low), offset(high).

    With align=True there is ONE moment column instead of three: the moment is
    forced parallel to e_hat (induced magnetisation). Use that whenever the
    sensor path is close to a straight line. A line of samples does not see
    enough geometry to separate the three components of a moment vector from the
    source position, so the free fit is degenerate: it reports a high r2 while
    the moment wanders by more than an order of magnitude. Constraining the
    direction removes two degrees of freedom and makes the magnitude - the thing
    MINE_SIZED is decided on - identifiable again.
    """
    n = len(xy)
    obs = np.vstack([np.column_stack([xy, np.full(n, h_low)]),
                     np.column_stack([xy, np.full(n, h_high)])])
    units = [e_hat] if align else list(np.eye(3))
    cols = [tfa(obs, src, unit, e_hat) for unit in units]
    off_low = np.r_[np.ones(n), np.zeros(n)]
    off_high = np.r_[np.zeros(n), np.ones(n)]
    return np.column_stack(cols + [off_low, off_high])


def _solve(xy, t, h_low, h_high, p, e_hat, align=False):
    """For a fixed source position p=(x0,y0,depth), m and offsets are linear -> lstsq."""
    A = _design(xy, h_low, h_high, np.array([p[0], p[1], -p[2]]), e_hat, align)
    coef, *_ = np.linalg.lstsq(A, t, rcond=None)
    return coef, t - A @ coef


@dataclass
class DipoleFit:
    x: float                   # metres, arena frame
    y: float
    depth: float               # metres below ground
    m: tuple                   # A*m^2, arena frame
    moment: float              # |m|, A*m^2  (~ amount of steel)
    remanence_angle_deg: float  # 0 = magnetised along Earth's field (intact steel body)
    r2: float                  # fit quality, 0..1
    rms_uT: float              # residual
    p2p_uT: float              # peak-to-peak of the low phone's raw readings (fit-independent)

    def as_dict(self):
        return asdict(self)


def fit_dipole(xy, t_low, t_high, h_low, h_high, e_hat, max_depth=0.40, align=False):
    """Fit one dipole to total-field readings from the low and high phone.

    xy: (N,2) sensor positions (m). t_low/t_high: (N,) total field (uT).
    h_low/h_high: phone heights above ground (m). e_hat: Earth-field direction.
    """
    xy = np.asarray(xy, float)
    t = np.r_[np.asarray(t_low, float), np.asarray(t_high, float)]
    e_hat = np.asarray(e_hat, float) / np.linalg.norm(e_hat)
    n = len(xy)

    lo, hi = xy.min(0) - 0.08, xy.max(0) + 0.08
    # 1) coarse grid search over position (robust: no local minima)
    best_cost, best_p = np.inf, None
    for d in np.linspace(0.01, max_depth, 30):
        for x0 in np.linspace(lo[0], hi[0], 13):
            for y0 in np.linspace(lo[1], hi[1], 13):
                _, res = _solve(xy, t, h_low, h_high, (x0, y0, d), e_hat, align)
                c = res @ res
                if c < best_cost:
                    best_cost, best_p = c, (x0, y0, d)
    # 2) refine the 3 nonlinear parameters
    sol = least_squares(lambda p: _solve(xy, t, h_low, h_high, p, e_hat, align)[1], best_p,
                        bounds=([lo[0], lo[1], 0.005], [hi[0], hi[1], max_depth]))
    coef, res = _solve(xy, t, h_low, h_high, sol.x, e_hat, align)
    m = coef[0] * e_hat if align else coef[:3]
    ss_tot = np.sum((t[:n] - t[:n].mean()) ** 2) + np.sum((t[n:] - t[n:].mean()) ** 2)
    r2 = 1.0 - (res @ res) / ss_tot if ss_tot > 0 else 0.0
    moment = float(np.linalg.norm(m))
    angle = float(np.degrees(np.arccos(np.clip(m @ e_hat / moment, -1, 1)))) if moment > 0 else 0.0
    return DipoleFit(x=float(sol.x[0]), y=float(sol.x[1]), depth=float(sol.x[2]),
                     m=tuple(float(v) for v in m), moment=moment,
                     remanence_angle_deg=angle, r2=float(r2),
                     rms_uT=float(np.sqrt(np.mean(res ** 2))),
                     p2p_uT=float(np.ptp(t[:n])))


def classify(fit, threshold, noise_uT, min_p2p_uT=1.0, snr=5.0, min_r2=0.7):
    """Label a fitted anomaly. Designed so a mine is never silently dropped:

    NO_TARGET  only if the raw peak-to-peak signal is small AND not clearly above
               the measured noise (noise_uT = standard error of one averaged
               reading, from the phones themselves). Uses raw data, not the fit,
               so a bad fit can never hide a real object.
    RESCAN     something is there but the fit is poor. Never treat as safe.
    MINE_SIZED decided by size (moment) alone; remanence never downgrades it.
    """
    if fit.p2p_uT < max(min_p2p_uT, snr * noise_uT):
        return NONE
    if fit.r2 < min_r2:
        return RESCAN
    return MINE if fit.moment >= threshold else FRAG


def _selftest(noise=0.15, seed=1):
    rng = np.random.default_rng(seed)
    inc = np.radians(66)                            # Boston-ish inclination
    e = np.array([np.cos(inc), 0.0, -np.sin(inc)])  # field points north and down
    h_low, h_high = 0.05, 0.35
    xy = scan_offsets("cross", 9, 0.05)
    cases = [("big steel, 12 cm deep", 0.05, 0.12),
             ("small steel, 3 cm deep", 0.005, 0.03)]
    print(f"{'case':26s} {'p2p':>7s} {'depth':>7s} {'moment':>8s} {'r2':>5s}")
    for name, mom, depth in cases:
        src = np.array([0.02, -0.01, -depth])
        def read(h):
            obs = np.column_stack([xy, np.full(len(xy), h)])
            return 51.0 + tfa(obs, src, mom * e, e) + rng.normal(0, noise, len(xy))
        f = fit_dipole(xy, read(h_low) + 1.2, read(h_high) - 0.7, h_low, h_high, e)
        print(f"{name:26s} {f.p2p_uT:5.2f}uT {f.depth*100:5.1f}cm {f.moment:8.4f} {f.r2:5.2f}"
              f"   -> {classify(f, threshold=0.016, noise_uT=noise)}")


if __name__ == "__main__":
    _selftest()
