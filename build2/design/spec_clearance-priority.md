## SUMMARY
The model says where the mines probably are. It does not say where to send the robot, and those are different questions: prioritisation in mine action is a land-use decision (IMAS 07.11 land release turns on what the land is needed FOR), not a hazard ranking. This spec defines the clearance tasking score that turns the briefed ORDER of importance — mine density, then proximity to populated areas, farmland, schools, hospitals, major roads, and terrain accessibility for clearance teams — into a reproducible ranking of Ukraine's 139 raions and 26 modelled oblasts, with every input taken from a citable open dataset and none invented. Weights are rank-order centroid over the stated ranking (0.370, 0.228, 0.156, 0.109, 0.073, 0.044, 0.020), which asserts the order that was actually specified and no numeric precision beyond it. Layers are normalised to national percentiles of 5 km cells so the seven incommensurable units combine, and so the UI's calibration sliders — which scale every mine count linearly — cannot move the ordering. The maths lives in `mineprior/tasking.py` and is checked by `mineprior/test_tasking.py`; the data build is `build2/fetch_tasking.py` + `build2/build_tasking.py`; outputs are `data/out/tasking.json`, `data/out/tasking_grid.npz` (seven uint8 layers on the national grid) and `dist/robot/tasking_priority.json` (the tasking order, with an AO anchor per district, for the robot).

## METHOD

### Unit of analysis: the same 5 km cell the posterior uses
Every layer is resampled onto the national 5 km equal-area grid in `data/out/ukraine_grid.npz`, and aggregated to districts through the `adm1`/`adm2` cell index that `build_prior.py` already stored there. This is not incidental: it guarantees that a district's tasking score and its mine estimate are computed over exactly the same cells, so the two numbers in the detail panel cannot disagree about what "Bakhmutskyi" means.

### "Within reach" — why four layers are neighbourhood sums
Population, schools, hospitals and roads are counted over every cell whose centre lies within **10 km**, not within the cell itself. A minefield 6 km from a village is still that village's problem: 10 km is roughly an hour's walk, and the range at which people graze livestock, collect firewood and take shortcuts. Counting only what sits inside a 5 km cell would task the robot to an empty cell and call the school one cell east invisible.

### Normalisation: national percentile among land cells
Each layer is mapped to [0, 1] as the fraction of land cells holding a strictly smaller value. Ties take the bottom of their band, so a cell with no school scores a true 0 rather than drifting to the middle of the tie block. Rank normalisation was chosen because (a) the seven layers share no unit, (b) four of them are heavy-tailed counts where one Kyiv-sized cell would otherwise compress everything else into the bottom percent of the scale, and (c) it is invariant to monotone rescaling, so moving the "mines per km²" slider changes every count on the page and changes no district's rank. The cost is real and is stated in the UI: rank discards magnitude, so the raw value of every criterion is displayed beside its percentile.

### Weights: rank-order centroid, because an order is all that was specified
w_k = (1/n) · Σ_{i=k..n} 1/i — the centroid of the simplex {w₁ ≥ w₂ ≥ … ≥ wₙ, Σw = 1}, i.e. the average of every weight vector consistent with the stated ranking (Barron & Barrett 1996). Writing "density 40%, population 25%" instead would assert precision nobody supplied. For n = 7 the first criterion outweighs the last four combined, which is the intended reading of "in order of what matters most". Switching a criterion off in the UI renormalises ROC over the remaining criteria rather than leaving a hole, so scores stay comparable between settings.

### Terrain accessibility is a BENEFIT, and this is the easiest thing to get backwards
access = clamp(1 − slope/18°) × clamp(1 − blocked_fraction), where blocked is the share of the cell under forest, built-up, permanent water or wetland. It multiplies priority UP where a team and a machine can actually work. Difficult ground is not safer ground — it is only slower to clear — so accessibility must never be allowed to reduce the modelled hazard, only the expected return on a season of work. 18° is between the ~15° commonly quoted as a flail/tiller working limit and the ~20° claimed on prepared ground; at 5 km resolution a cell's mean slope understates the worst slope inside it, so the softer end is the honest one.

### Composite and tiers
score(cell) = Σ w_k · percentile_k(cell); district score = the mean over its land cells. Display classes are frozen at build time from the national distribution of the default-weighted composite, at the 50th/75th/90th/96th/99th percentiles of modelled land (currently 0.483/0.595/0.699/0.783/0.853): the bottom class is half the country, the top class its worst 1% — about 1,500 km², the order of a season's work for a national programme rather than a wish. Evenly spaced breaks were tried and rejected: a mean of seven percentile layers piles up around 0.5 (a Bates distribution, not a uniform one), so an even scale puts most of the country in the top three classes and the map ranks nothing. Breaks do not move when a criterion is switched off, so a colour keeps its meaning across settings and screenshots.

The district's suggested area of operations is its **highest-scoring single 5 km cell**, not its centroid, which is usually farmland nobody has a reason to sweep.

### Build order
`build2/fetch_tasking.py` → `build2/build_tasking.py` → `build2/export_robot.py` → `build2/export_html.py`. The robot step reads `dist/robot/tasking_priority.json` and anchors its area of operations on the rank-1 district's best cell, falling back to the raw hazard peak with an explicit log line when no tasking order has been built; `next_mission.json` records which rule was used, because "why is the robot here" must never be a guess.

## SOURCES

| Layer | Source | Licence | Vintage | Transfer |
|---|---|---|---|---|
| density | This model (UCDP GED v25.1 prior) | — | events to 2024 | in repo |
| people | WorldPop 1 km, Ukraine | CC BY 4.0 | 2020 | 5.1 MB |
| farmland | ESA WorldCover v200, class 40 | CC BY 4.0 | 2021 | overviews only, ~1 MB |
| schools | OpenStreetMap via HOT/HDX, `amenity=school` | ODbL | 2026 extract | 6.9 MB |
| hospitals | OpenStreetMap via HOT/HDX, `amenity`/`healthcare=hospital` | ODbL | 2026 extract | 2.4 MB |
| roads | GRIP4 highway + primary density (Meijer et al. 2018) | CC BY 4.0 | c. 2018 | 4.5 MB |
| access | GMTED2010 30 arc-second relief + ESA WorldCover | public domain / CC BY 4.0 | 2010 / 2021 | 69 MB |

Raw files land in `data/tasking/`, which is gitignored: only the derived per-district aggregates are committed, so the repository does not redistribute the sources.

Two acquisition notes worth keeping. ESA WorldCover tiles are 72 MB each and 27 of them carry Ukrainian land; the build reads their COG overview pyramid over HTTP at an exact ÷32 decimation (~300 m, ~280 samples per 5 km cell) instead of downloading 1.9 GB. And Natural Earth 10 m roads was **rejected** as the road source: it holds 1,122 road features for the whole of Ukraine and types 40% of them "Unknown", so a length-per-district figure from it would mostly record how the 1:10 m cartography was digitised.

## FAILURE MODES

- **Reading the score as risk.** A district scores low when little is at stake near it, never because the ground is clear. Every surface that shows the score says so, and the bottom tier is labelled "Lowest tasking priority — NOT cleared". The lexical ban list from the UI spec applies unchanged.
- **OSM completeness is worst where it matters most.** Mapping density in contested Donetsk and Luhansk is thinner than in Lviv, so the schools and hospitals layers are lower bounds biased DOWN in exactly the oblasts this product exists for. Their combined ROC weight is 0.181, which caps the damage but does not remove it. A national facilities register from the Ministry of Education/Health would replace both layers without touching the arithmetic.
- **Population and land cover pre-date the invasion.** WorldPop 2020 and WorldCover 2021 describe where people lived and farmed, not where they are tonight. For return-planning — which is what clearance prioritisation usually serves — the pre-war distribution is arguably the right denominator, but it must be labelled, not assumed.
- **Percentiles hide magnitude.** The 99th-percentile cell may hold ten or a thousand times the mines of the 98th. Mitigated by showing raw values everywhere, not by changing the normalisation.
- **A single number nobody can decompose is not a defensible tasking decision.** The detail panel therefore prints every criterion's raw value, percentile and exact contribution, and any single layer can be put on the map on its own.
- **Averaging over a district hides a hot pocket inside it.** A raion whose score is driven by a handful of extreme cells ranks the same as one that is uniformly moderate. The AO anchor is the partial answer — it points at the worst cell, not the district's average — but the district ordering itself is still a mean.
- **5 km is coarse for terrain.** Mean slope over 25 km² cannot see the gully that stops a machine; accessibility is a screening layer, and route-level feasibility remains a survey question.

## CHECKS THAT RUN
`mineprior/test_tasking.py` covers the weight algebra (ROC closed form, renormalisation on disabling a criterion, refusal of unnormalised weights), the tie rule and monotone-transform invariance of percentile scoring, the bounds and multiplicativity of accessibility, tier breaks, and the ranking's treatment of a district with a missing layer (renormalised over what it has, flagged partial, never dropped and never zero-filled).

`build_tasking.py` additionally reports the **median rank shift against a density-only ordering** (currently 17 places, max 71). Both extremes would be a red flag: a shift near zero would mean the six impact criteria are decoration, and a ranking uncorrelated with mine density would mean the hazard had stopped mattering.
