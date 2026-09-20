"""bayes.py - what the scan implies about how many mines are out there.

field_scan.py classifies individual spots. That answers "is THIS one a mine".
It does not answer the question a demining organisation actually asks:

    given what we have surveyed so far, how contaminated is this area,
    and how sure are we?

Two conjugate models, both updated online as each spot is classified, so the
estimate tightens live while the dog walks.

1. HIT RATE - Beta-Binomial.
   Every flagged spot is a Bernoulli trial: MINE_SIZED or not.
     prior      p ~ Beta(a0, b0)
     after k mines in n spots:  p ~ Beta(a0 + k, b0 + n - k)
   Answers "of the spots a drone flags, what fraction are real threats?"

2. AREA DENSITY - Gamma-Poisson.
   Mines are a Poisson process over the ground with rate lambda per m^2.
     prior      lambda ~ Gamma(shape a0, rate b0)
     after k mines found while sweeping area A:  lambda ~ Gamma(a0 + k, b0 + A)
   Answers "mines per hectare", which is the number that scales.

3. EXTRAPOLATION - posterior predictive, a Negative Binomial.
   For a region of area R, N | lambda ~ Poisson(lambda R) with lambda ~ Gamma(a, b)
   marginalises exactly to N ~ NegBinom(r = a, p = b / (b + R)). This carries the
   posterior uncertainty in lambda through to the count, which is why the interval
   widens honestly instead of pretending lambda is known.

HONESTY, because a judge will ask. Extrapolating a room to a city assumes the
density is UNIFORM between them. It is not. That assumption, not the counting
statistics, dominates the real error, and `regional_estimate` says so in the
payload it returns. The arithmetic here is exact; the premise is the weak part,
and it should be presented that way.

    python bayes.py    # self-test
"""
from __future__ import annotations

from dataclasses import dataclass, field

from scipy import stats

HECTARE_M2 = 10_000.0


@dataclass
class SurveyPosterior:
    """Online Bayesian summary of a scan in progress.

    Priors are deliberately weak. a0=b0=1 on the hit rate is uniform on [0,1];
    the density prior is near-flat so a handful of observations dominate it.
    """

    # Beta prior on P(mine | flagged spot)
    hit_a0: float = 1.0
    hit_b0: float = 1.0
    # Gamma prior on mines per m^2: mean a0/b0, very broad
    den_a0: float = 0.5
    den_b0: float = 100.0

    n_spots: int = 0            # spots classified (any label)
    n_mines: int = 0            # spots labelled MINE_SIZED
    area_m2: float = 0.0        # ground area actually swept

    _events: list = field(default_factory=list)

    # ---------------------------------------------------------------- update

    def observe(self, is_mine: bool, area_m2: float = 0.0) -> None:
        """Fold in one classified spot. `area_m2` is the ground it cleared."""
        self.n_spots += 1
        self.n_mines += 1 if is_mine else 0
        self.area_m2 += max(0.0, area_m2)
        self._events.append({"mine": bool(is_mine), "area_m2": area_m2})

    # ---------------------------------------------------------------- 1. hit rate

    @property
    def hit_post(self):
        return stats.beta(self.hit_a0 + self.n_mines,
                          self.hit_b0 + self.n_spots - self.n_mines)

    def hit_rate(self, cred: float = 0.95) -> dict:
        """P(mine | a drone-flagged spot), with a credible interval."""
        d = self.hit_post
        lo, hi = d.ppf((1 - cred) / 2), d.ppf(1 - (1 - cred) / 2)
        return {"mean": float(d.mean()), "lo": float(lo), "hi": float(hi),
                "cred": cred, "n_spots": self.n_spots, "n_mines": self.n_mines}

    # ---------------------------------------------------------------- 2. density

    @property
    def density_post(self):
        # scipy's gamma takes a shape and a SCALE; scale = 1 / rate.
        return stats.gamma(self.den_a0 + self.n_mines,
                           scale=1.0 / (self.den_b0 + self.area_m2))

    def density(self, cred: float = 0.95) -> dict:
        """Mines per hectare, with a credible interval."""
        d = self.density_post
        lo, hi = d.ppf((1 - cred) / 2), d.ppf(1 - (1 - cred) / 2)
        return {"per_hectare_mean": float(d.mean() * HECTARE_M2),
                "per_hectare_lo": float(lo * HECTARE_M2),
                "per_hectare_hi": float(hi * HECTARE_M2),
                "per_m2_mean": float(d.mean()),
                "cred": cred, "area_swept_m2": self.area_m2}

    # ---------------------------------------------------------------- 3. extrapolate

    def regional_estimate(self, region_area_m2: float, region_name: str = "region",
                          cred: float = 0.95) -> dict:
        """Posterior predictive count of mines in a region of this area.

        Exact marginalisation of Poisson(lambda*R) over the Gamma posterior gives
        a Negative Binomial, so the interval includes our uncertainty in lambda
        rather than conditioning on a point estimate.
        """
        a = self.den_a0 + self.n_mines
        b = self.den_b0 + self.area_m2
        R = float(region_area_m2)
        p = b / (b + R)
        nb = stats.nbinom(a, p)
        lo, hi = nb.ppf((1 - cred) / 2), nb.ppf(1 - (1 - cred) / 2)
        return {
            "region": region_name,
            "region_area_m2": R,
            "region_area_km2": R / 1e6,
            "expected": float(a * R / b),
            "lo": float(lo), "hi": float(hi), "cred": cred,
            # Surfaced deliberately: this is the dominant error, not the statistics.
            "assumption": ("Assumes the surveyed density is uniform across the whole "
                           "region. It is not. This assumption dominates the error - "
                           "the interval below reflects only sampling uncertainty."),
        }

    # ---------------------------------------------------------------- payload

    def snapshot(self, regions: dict | None = None, cred: float = 0.95) -> dict:
        out = {"hit_rate": self.hit_rate(cred), "density": self.density(cred)}
        if regions:
            out["regions"] = [self.regional_estimate(a, n, cred)
                              for n, a in regions.items()]
        return out


# Areas people recognise, for the extrapolation panel.
REGIONS_M2 = {
    "a football pitch": 7_140.0,
    "Boston (city limits)": 232.1e6,
    "Ukraine's contaminated land (est.)": 174_000e6,
}


def _selftest() -> None:
    import math

    s = SurveyPosterior()
    # No data: the hit-rate posterior is the uniform prior, mean 1/2.
    assert abs(s.hit_rate()["mean"] - 0.5) < 1e-9, "empty prior should be uniform"

    # 3 mines in 10 spots over 40 m^2.
    for i in range(10):
        s.observe(is_mine=i < 3, area_m2=4.0)
    hr = s.hit_rate()
    assert s.n_spots == 10 and s.n_mines == 3
    # Beta(1+3, 1+7) has mean 4/12.
    assert abs(hr["mean"] - 4 / 12) < 1e-9, f"beta mean wrong: {hr['mean']}"
    assert hr["lo"] < hr["mean"] < hr["hi"], "interval must bracket the mean"

    den = s.density()
    # Gamma(0.5+3, rate 100+40) mean = 3.5/140 per m^2.
    assert abs(den["per_m2_mean"] - 3.5 / 140) < 1e-12, "gamma mean wrong"
    assert den["per_hectare_lo"] < den["per_hectare_mean"] < den["per_hectare_hi"]

    # Negative-Binomial mean must equal lambda_mean * R exactly.
    R = 1e6
    reg = s.regional_estimate(R, "test")
    assert abs(reg["expected"] - den["per_m2_mean"] * R) < 1e-6, "NB mean mismatch"
    assert reg["lo"] < reg["expected"] < reg["hi"], "NB interval must bracket"

    # More evidence at the same rate must SHRINK the relative interval.
    wide = s.hit_rate()
    s2 = SurveyPosterior()
    for i in range(100):
        s2.observe(is_mine=i < 30, area_m2=4.0)
    tight = s2.hit_rate()
    assert (tight["hi"] - tight["lo"]) < (wide["hi"] - wide["lo"]), \
        "more data must tighten the credible interval"

    # Predictive interval must be WIDER than pretending lambda is known
    # (that is the whole point of marginalising).
    pois_hi = stats.poisson(den["per_m2_mean"] * R).ppf(0.975)
    assert reg["hi"] > pois_hi, "NB must be over-dispersed relative to Poisson"

    print("bayes.py self-test passed")
    print(f"  after 3/10 spots over 40 m^2:")
    print(f"    hit rate  {hr['mean']*100:.0f}%  [{hr['lo']*100:.0f}, {hr['hi']*100:.0f}]")
    print(f"    density   {den['per_hectare_mean']:.0f}/ha  "
          f"[{den['per_hectare_lo']:.0f}, {den['per_hectare_hi']:.0f}]")
    b = s.regional_estimate(REGIONS_M2["Boston (city limits)"], "Boston")
    print(f"    Boston    {b['expected']:,.0f} mines  [{b['lo']:,.0f}, {b['hi']:,.0f}]")


if __name__ == "__main__":
    _selftest()
