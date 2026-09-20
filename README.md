# Minefield Prior

A Bayesian model of landmine contamination. The prior comes from UCDP GED v25.1
georeferenced conflict events; the posterior is updated by a DimensionalOS robot
sweeping ground and reporting what it finds.

Two deliverables:

- **`dist/landmine-bayes.html`** — a self-contained interactive map. Nothing is
  fetched at runtime.
- **`dist/robot/`** — an `OccupancyGrid`-compatible cost surface, a waypoint
  plan, and a sweep log, for the dimOS side.

---

## What this is, and what it is not

This is **non-technical survey support information**: a desk assessment that
ranks ground for survey. It is not survey, not clearance, and not a land-release
decision. Under IMAS 08.10 "former combat zones" are *indirect* evidence —
enough to justify suspecting an area, never enough to cancel one.

Nothing here declares any area free of explosive ordnance, and the word "safe"
appears nowhere in the output vocabulary. There is no green on the map: people
read green as permission regardless of the legend.

**The absolute counts rest on an assumption.** Mine Action Review's *Clearing the
Mines 2025* records Ukraine's contamination verbatim as "Massive but no reliable
estimate". There is no trusted national denominator, so the count is
contaminated-area × mines-per-km², both exposed as sliders. The **ranking between
districts** is the claim the data actually supports; the absolute number is not.

---

## Running it

Python 3.12, `numpy scipy pandas shapely pypdf`.

```
python build/cache_events.py     # 250 MB GED CSV -> 2.5 MB .npz cache
python build/prep_geo.py         # simplify + quantise boundaries
python build/parse_ctm.py        # per-state contamination from Mine Action Review
python build/build_prior.py      # the model: exposure -> Gamma prior -> districts
python build/export_robot.py     # AO posterior + simulated mission + dimOS export
python build/export_html.py      # pack everything into one HTML file
python -m mineprior.test_model   # 40 checks on the closed forms
```

`build/prep_geo.py` and `build/parse_ctm.py` need files already in `data/`; the
download URLs are in each script's docstring.

---

## The model

Intensity **density** `rho_i` (mines/km²) is the state variable, with
`lambda_i = rho_i * A_i`. Parameterising counts directly would make the model
depend on grid resolution.

```
lambda_i ~ Gamma(alpha_i, beta_i)
alpha_i  = alpha_floor + m_i / psi        psi = 8, alpha_floor = 0.4
beta_i   = alpha_i / m_i                  => prior mean is exactly m_i
```

This is invariant under cell merging; a fixed `alpha_0` is not.

**Prior mean** `m_i = A_i * (a0 + kappa * rho_E_i)`, where exposure `rho_E` is a
mass-normalised kernel sum over weighted events. `a0` and `kappa` follow in
closed form from a national target `N*` and a background share `pi = 0.15`.

**Likelihood.** The robot sweeps coverage `c` with sensitivity `s`. By Poisson
thinning, detections are *exactly* `Poisson(lambda * t)` with `t = c*s` — not an
approximation. So:

| observation | posterior |
|---|---|
| `y` confirmed mines | `Gamma(alpha + y, beta + t)` |
| nothing found | `Gamma(alpha, beta + t)` — shape unchanged |
| `a` alarms, false-alarm rate `f` | exact `(a+1)`-term Gamma mixture, moment-matched |

A null sweep shrinks mean and sd by the same factor `beta/(beta+t)`, leaving the
CV unchanged: a clean sweep lowers your estimate without making you
proportionally more certain. `a = 0` stays exactly conjugate even with false
positives, which matters because null sweeps are most of the data.

**Effective exposure is divided by 3** (`CLUSTER_DISCOUNT`). Thinning assumes
mines are uniform within a cell; minefields are compact belts. For a cell with
100 mines swept over 1.2% of its area, `P(zero detections)` is 0.33 under
uniformity but ~0.97 if the mines sit in one hectare — so a clean sweep is ~3×
less informative than the naive model claims, and that error runs in the unsafe
direction.

**District totals** use Welch–Satterthwaite moment matching with a design-effect
correction `DEFF = min(n, 2*pi*L^2/A_cell)`. At L = 20 km on a 5 km grid that
inflates the sd about 10×. Summing independent per-cell variances would produce
absurdly tight intervals.

**Acquisition** is `VOI = Var * t/(beta+t)` — exact, O(1), and submodular, so
greedy selection is within (1−1/e) of optimal for the pure-information problem.

### Live updating in the page

`dist/landmine-bayes.html` ships the per-cell prior mean, not a display raster,
and rebuilds `(alpha, beta)` in the browser — so the conjugate update above runs
there too. *Log on click* folds an observation into the posterior and everything
recomputes: the cell, the district total and its interval, the rankings, the
tasking queue and the heatmap.

Moving the calibration sliders rebuilds the prior and **replays** the
observation log, exactly as `SweepLog.replay` does on the Python side, so
recalibrating doesn't discard evidence.

---

## Clearance tasking

`mineprior/tasking.py` answers a different question from the posterior: not
"where are the mines" but "where does clearing them matter most". That is a
land-use decision — IMAS 07.11 land release turns on what the land is needed
FOR — so an empty steppe cell with a high modelled density and nobody within
40 km ranks below a moderately contaminated field behind a village school.

Seven criteria in a stated order of importance, weighted by **rank-order
centroid** (the centroid of every weight vector consistent with that order):

| # | Criterion | Weight | Source |
|---|---|---|---|
| 1 | Modelled mine density | 0.370 | this model (live posterior) |
| 2 | People within 10 km | 0.228 | WorldPop 2020 |
| 3 | Farmland | 0.156 | ESA WorldCover 2021 |
| 4 | Schools within 10 km | 0.109 | OSM via HOT/HDX |
| 5 | Hospitals within 10 km | 0.073 | OSM via HOT/HDX |
| 6 | Major roads | 0.044 | GRIP4 |
| 7 | Terrain accessibility | 0.020 | GMTED2010 + WorldCover |

Layers are normalised to national percentiles of 5 km cells, so the seven
incommensurable units combine and the calibration sliders — which scale every
mine count linearly — cannot move the ordering. Accessibility is a **benefit**,
not a hazard term: difficult ground is not safer, only slower to clear.

The density criterion is recomputed in the page from the live posterior, so
logging detections reorders the queue (verified: Melitopolskyi #61 → #54 after
25 confirmed detections).

Two queues, because they answer different questions:

- **Clearance queue** — which district to go to, ordered by tasking score, each
  with the AO anchor to start from (the district's highest-scoring single cell,
  not its centroid, which is usually farmland nobody has a reason to sweep).
- **Sweep route** — once there, which cells to sweep, by expected finds plus
  value of information against travel.

A district scores low when little is at stake near it, **never** because the
ground is clear; the bottom tier reads "Lowest tasking priority — NOT cleared".

Build: `build/fetch_tasking.py` → `build/build_tasking.py`. Checks:
`python -m mineprior.test_tasking`.

---

## How precision is handled

This is where a naive implementation fails hardest. In Ukraine, **all 1,194
`where_prec = 6` events sit on one coordinate (49.000000, 32.000000)**, carrying
89,634 deaths — 36.6% of every fatality GED records for the country — onto a
pixel in Cherkasy oblast, which saw essentially no ground combat. A
death-weighted KDE puts its single largest hotspot on uncontaminated farmland.

| `where_prec` | meaning | treatment |
|---|---|---|
| 1 | exact point | Gaussian, σ_geo 0.3 km |
| 2 | within ~25 km | Gaussian, σ_geo 12.5 km |
| 3 | ADM2 centroid | spread **uniformly over the raion polygon** |
| 4 | ADM1 centroid | spread **uniformly over the oblast polygon** |
| 5 | linear/fuzzy feature | Gaussian, σ_geo 75 km |
| 6 | country only | **dropped** |
| 7 | international waters | **dropped** |

The kernel is mass-normalised, so an imprecise event spreads the same total
weight over a larger area and contributes less per cell. `build_prior.py`
asserts that no single cell holds >5% of national exposure; it currently holds
1.04%.

**Resolution is capped at 5 km.** Ukraine's occupied-cell count saturates —
0.05° → 1,922 cells, 0.01° → 2,346 — because 31,547 events sit on ~2,440
distinct coordinates, with a median nearest-neighbour spacing of 3.58 km. There
is no information below ~5 km, so the robot's fine grid inherits a **flat**
prior from its parent cell and every sub-5 km feature comes from sensor data.
`PosteriorField.prior_is_flat` records this.

---

## Deliverable B: the dimOS side

`mineprior/` has no dimOS dependency except `dimos_module.py`, which is
import-guarded — the maths runs and tests anywhere, which matters because dimOS
targets Linux/macOS.

```python
from mineprior.dimos_module import MinePosterior, build_occupancy_grid, build_path
from dimos.core.coordination.blueprints import autoconnect
from dimos.navigation.replanning_a_star.module import ReplanningAStarPlanner

bp = autoconnect(
    MinePosterior.blueprint(posterior_npz="ao_posterior.npz",
                            sidecar_json="ao_posterior.json"),
    ReplanningAStarPlanner.blueprint(),
)
```

`ReplanningAStarPlanner` is the only shipped planner with an
`global_costmap: In[OccupancyGrid]` port, so `MinePosterior` stands in for
`CostMapper` and autoconnect wires it by `(property_name, message_type)`.
`DanLocalPlanner` is a replan gate and path smoother with no map input;
`MLSPlannerNative` searches a voxel `PointCloud2`. Neither would ever connect.

Cost is `P(at least one mine present) × 100` on the int8 0–100 scale. `-1`
(UNKNOWN) is reserved strictly for cells outside the modelled domain — a
never-surveyed cell with a high prior is encoded as **high cost**, not unknown.

dimOS ships no projection, so `mineprior.geo.ENU` anchors a local tangent plane
at the AO origin and the sidecar carries origin lat/lon, resolution and grid
order. Rebuild from the sidecar, never from the `.npy` alone —
`OccupancyGrid.from_path()` discards resolution and origin.

### Provenance is a hard gate

```
synthetic -> sensor_anomaly -> operator_confirmed -> eod_disposed
```

`export_registered()` **raises** on synthetic or unadjudicated records rather
than filtering them, because a silent filter also silently drops good records
when a provenance string is misspelled. Only the last two tiers meet the IMAS
direct-evidence bar and may be drawn as confirmed hazards.

**The shipped HTML contains zero confirmed-mine records, and none are invented.**
Load your own registry through the sidebar; it stays in the browser.

### The exploration arm is not optional

`mission.select_next` sends 15% of sweeps to randomly chosen, risk-decile-
stratified cells and records the selection propensity. Without it the robot only
visits cells the model already calls risky, so "we predicted high risk, went
there, found mines" can never be falsified. Log every sweep including nulls.

---

## Honest limitations

1. **The update is nearly inert at realistic coverage.** Measured in
   `export_robot.py`: one full-cell clean sweep shrinks the posterior mean by
   **0.0064%**; halving one cell's estimate needs ~15,600 sweeps. Show the
   coverage layer — it is deterministic and moves visibly — and let the risk
   posterior move as slowly as the evidence warrants.
2. **Mines mark where fighting was prevented.** Defensive belts exist to deny
   approach; where they worked there was no combat and so no GED event. The
   signal is systematically displaced from the densest minefields, typically by
   the depth of a belt. The single highest-value improvement would be a signed
   distance-to-line-of-contact feature.
3. **Deaths measure lethality, not mining effort.** A well-laid minefield deters
   rather than kills.
4. **The prior ends in 2024**, ~21 months stale, and the newest contamination is
   where the front now sits.
5. **GED is a reported-event dataset.** Occupied territory and rural treeline
   engagements are under-reported, and that bias correlates with the covariate
   of interest rather than averaging out.
6. **No ground truth anywhere.** There is no point at which this model can be
   wrong in a way anyone would notice. RELand — 70 features, 500 m cells, real
   demining labels — reports PR-AUC 29%. Expect worse.
7. **Dual use.** RELand's authors withheld their public interface because a
   predictive minefield map is dangerous in the wrong hands. Publishing this
   should be a deliberate decision.

---

## Sources

- UCDP GED v25.1 (Uppsala Conflict Data Program), 1989–2024, 385,918 events
- Mine Action Review, *Clearing the Mines 2025*, 1 Nov 2025 — per-state AP mine
  contamination
- Landmine Monitor 2025 (ICBL-CMC) — severity bands, Ukraine 105.88 km²
- geoBoundaries `gbHumanitarian` UKR ADM1/ADM2 (CC BY 3.0 IGO; OCHA COD via
  Kartographia, 2022) — 27 oblasts, 139 post-reform raions. The `gbOpen` ADM2
  release is the 2006 495-raion system and must not be used.
- Natural Earth via world-atlas 2.0.2 (ISC)
- IMAS 07.11, 08.10, 08.20, 09.10
