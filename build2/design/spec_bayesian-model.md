## SUMMARY
I inspected GEDEvent_v25_1.csv inside ged251-csv.zip (48 columns, 250 MB) and extracted all 31,547 Ukraine events (2014-2024, bbox lat 44.38-52.34, lon 22.72-39.85) to ground the spec in real field distributions. Key empirical facts that drive the math: where_prec is 1:7259 / 2:16820 / 3:1311 / 4:3265 / 5:1688 / 6:1194 / 7:10, and cross-tabulation PROVES the semantics — all 1194 where_prec=6 events sit at exactly one coordinate (49.000000, 32.000000 = Ukraine centroid) with blank adm_1/adm_2, where_prec=4 has only 21 distinct coordinates with adm_2 always blank (oblast centroids), where_prec=3 has 72 distinct coordinates with both admin fields populated (raion centroids), while where_prec=2 has 1718 distinct coordinates (so it is NOT a centroid code — it is a real point with ~25 km radius uncertainty). type_of_violence is 99.3% state-based (1:31320, 2:1, 3:226); 31,547 events collapse onto only 2442 distinct coordinate pairs, so any kernel with a sub-kilometre bandwidth will produce spurious spikes at town centroids. I specify a complete conjugate Gamma-Poisson model in intensity-density form with a variance-to-mean parameterisation (psi, alpha_floor) that is provably scale-invariant under cell merging, an exact thinning lemma showing the Poisson likelihood is exact (not an approximation), an exact finite Gamma-mixture posterior under detector false positives (no MCMC), an exact closed-form expected-variance-reduction acquisition function Var_prior * t/(beta+t), closed-form empirical-Bayes hyperparameters via Clayton-Kaldor moments, and an explicit, quantified error budget for the evidence-spreading spatial coupling (bias = (sigma_c^2/2) * Laplacian(lambda); district variance under-stated, corrected by DEFF = 2*pi*L^2/A_cell). Every default parameter value is given with a numeric justification.

## FINDINGS

### [verified] GED v25.1 schema: exact column names and Ukraine row counts
File inside ged251-csv.zip is a single entry GEDEvent_v25_1.csv (250,393,383 bytes), 48 columns. Column order (0-indexed) relevant to the model: 0 id, 2 year, 5 type_of_violence, 24 where_prec, 27 adm_1, 28 adm_2, 29 latitude, 30 longitude, 32 priogrid_gid, 33 country, 36 event_clarity, 37 date_prec, 38 date_start, 39 date_end, 42 deaths_civilians, 44 best, 45 high, 46 low. date_start/date_end format is 'YYYY-MM-DD 00:00:00.000'. Ukraine subset: 31,547 events. Year histogram: 2014:1303, 2015:871, 2016:514, 2017:216, 2018:153, 2019:199, 2020:145, 2021:167, 2022:7429, 2023:10181, 2024:10369. sum(best)=245,068, mean(best)=7.768, max(best)=15,996, 254 events with best=0. event_clarity 1:26588, 2:4959. date_prec 1:23221, 2:7600, 3:200, 4:389, 5:137. Duration (date_end - date_start): mean 1.063 days, median 0, max 365, 26.4% of events span more than one day. 28 distinct adm_1 values (2170 blank), 172 distinct adm_2, 225 distinct priogrid_gid. Top adm_1: Donetsk 16222, Luhansk 3168, Kharkiv 3126, Kherson 2731, Zaporizhzhya 2295.
_source: Streamed the zip entry with a custom C# RFC4180 parser via Add-Type in PowerShell; printed header and Group-Object tallies._

### [verified] where_prec semantics PROVEN from the data (not assumed from the codebook)
Cross-tab of where_prec x (distinct lat/lon pairs, adm_1 blank, adm_2 blank) over the 31,547 Ukraine rows:
  wp=1: n=7259, 1452 distinct XY, 0 adm1-blank, 57 adm2-blank  -> exact point locations, heavy repetition on town centroids (5.0 events per coordinate).
  wp=2: n=16820, 1718 distinct XY, 0 adm1-blank, 72 adm2-blank  -> a REAL point with radius uncertainty, NOT an admin centroid (1718 distinct coords rules that out).
  wp=3: n=1311, 72 distinct XY, both admin fields always populated -> adm_2 (raion) centroid.
  wp=4: n=3265, 21 distinct XY, adm_2 blank in ALL 3265 rows -> adm_1 (oblast) centroid. Top coords 48.14/37.74 (n=1200), 46.6406/32.61589 (n=615), 48.92/39.02 (n=400).
  wp=5: n=1688, 34 distinct XY, adm_2 blank in 1681, adm_1 blank in 966 -> multi-adm1 area.
  wp=6: n=1194, exactly ONE distinct coordinate 49.000000,32.000000 for all 1194 rows, adm_1 and adm_2 blank in all -> country centroid.
  wp=7: n=10, 8 distinct XY, coordinates cluster at lat~45.2 lon~30.6-31.4 which is the Black Sea -> international waters / unknown.
CONSEQUENCE: a naive point-KDE puts 1194 events (mean best = 75.07, the highest of any precision class) on a single pixel at 49N 32E in Cherkasy oblast, which saw essentially no ground combat. This is the single largest failure mode of the naive prior and MUST be handled by bandwidth widening or polygon spreading.
_source: PowerShell Group-Object cross-tabulation of the extracted Ukraine TSV; the wp=6 single-coordinate result and wp=4 adm_2-always-blank result are direct counts._

### [verified] Foundations: coordinates, grid, intensity-density formulation
UNITS: distance km, area km^2, counts = mines.
PROJECTION (local equirectangular, valid over a country-sized domain): pick reference (phi0, l0) = domain centroid. For a point at (lat phi, lon l) in degrees:
  x = R_E * cos(phi0) * (l - l0) * pi/180 ,  y = R_E * (phi - phi0) * pi/180 ,  R_E = 6371.0 km.
  => 111.195 km per degree latitude; 111.195*cos(phi0) km per degree longitude. For Ukraine phi0 = 48.5 deg: 73.65 km per degree longitude.
  Distance d(a,b) = sqrt((x_a-x_b)^2 + (y_a-y_b)^2). Use haversine only if the domain exceeds ~20 deg of latitude.
GRID: partition the domain into disjoint cells i = 1..n with area A_i (km^2) and centroid x_i. Two scales, SAME model:
  - National/district display: square cells of edge h = 5 km (A_i = 25). Ukraine bbox from the data is 17.13 deg lon x 7.96 deg lat = 1262 km x 885 km -> 253 x 177 = 44,781 cells. Mask to land and to cells within 3.5 sigma of any event to cut this by ~60%.
  - Robot local grid (Ukraine AO): edge h = 5 m (A_i = 2.5e-5 km^2). A 2 km x 2 km AO is 400 x 400 = 160,000 cells.
STATE VARIABLE: model the intensity DENSITY rho_i (mines per km^2), and define the per-cell expected count lambda_i = rho_i * A_i. Never parameterise counts directly, or the model stops being resolution-consistent.
DECOMPOSITION OF WHAT IS DISPLAYED: total mines in cell i = R_i + U_i, where R_i = number of REGISTERED/confirmed mines whose exact coordinates are known (deterministic, drawn as dots, NOT modelled) and U_i = unknown residual mines (Poisson(lambda_i), the Bayesian part). Registered mines must be SUBTRACTED from the modelled component, not double-counted: the district headline number is R_D + E[sum of U_i over D].
_source: Bbox computed from the Ukraine subset (lat 44.38-52.34006, lon 22.72313-39.85471); projection constants are standard (2*pi*6371/360 = 111.195)._

### [likely] (a) EXACT functional form of the event weight w(e)
w(e) = w_tov(tov_e) * f_fat(best_e) * f_dur(D_e) * f_rec(t_e) * f_clar(clar_e) * f_prec(wp_e).   [dimensionless]

1. TYPE OF VIOLENCE. w_tov(1) = 1.00 (state-based armed conflict), w_tov(2) = 0.45 (non-state conflict), w_tov(3) = 0.15 (one-sided violence). Justification: ERW/mine contamination is produced by territorial, front-line, ordnance-intensive warfare. One-sided violence (massacres, executions) is lethal but deposits almost no ordnance. In Ukraine this term is nearly inert (99.3% of events are tov=1) but it matters for the global overview map.

2. FATALITIES. f_fat(b) = min( (1 + b/b0)^gamma_f , F_max ),  b0 = 5,  gamma_f = 0.5,  F_max = 20.
   Values: b=0 -> 1.000; b=5 -> 1.414; b=50 -> 3.317; b=500 -> 10.05; b=1995 -> 20.0 (cap binds); b=15996 (Ukraine max) -> capped at 20.
   Justification: (i) f_fat(0) = 1 > 0 is REQUIRED because 254 Ukraine events have best=0 yet a zero-fatality artillery exchange still deposits UXO; (ii) square-root gives strongly diminishing returns, appropriate because fatalities scale with population exposure as much as with ordnance expenditure; (iii) the cap prevents the Mariupol-scale event (best=15,996) from carrying 6.5% of the national prior mass on its own. Optional variant: use max(best - deaths_civilians, 0) if you believe civilian deaths are less predictive of ordnance than combatant deaths; I do NOT recommend it as the default because civilian deaths in Ukraine largely arise from shelling, which is exactly the mine/UXO-generating process.

3. DURATION. D_e = 1 + (date_end_e - date_start_e) in whole days; f_dur(D) = min(D, D_max)^gamma_d, gamma_d = 0.30, D_max = 365.
   Values: D=1 -> 1.000; D=7 -> 1.750; D=30 -> 2.773; D=90 -> 3.857; D=365 -> 5.87.
   Justification: a GED record spanning many days is an aggregate of sustained fighting over the same ground. 26.4% of Ukraine events span >1 day, so this term is active. gamma_d = 0.30 (rather than 1.0) because a 365-day record is an editorial aggregation artefact, not 365x the ordnance. Duration ALSO widens the kernel - see (b).

4. RECENCY. Let t_e = decimal year of date_start_e, T_ref = the analysis date in decimal years (use 2025.0, the GED v25.1 coverage end, or today's date if you also ingest newer data). Age a_e = max(T_ref - t_e, 0).
   f_rec(t_e) = f_inf + (1 - f_inf) * exp(-a_e / tau),   tau = 12 years,  f_inf = 0.35.
   Values (T_ref = 2025.0): 2024 event -> 0.947; 2022 -> 0.872; 2019 -> 0.775; 2014 -> 0.614.
   Justification: this term models NET SURVIVAL of contamination, not the decay of information. Mines persist for decades, hence the floor f_inf = 0.35, which is the asymptotic fraction still present after clearance, self-neutralisation and burial/loss beyond ~40 years. tau = 12 y (equivalent half-life 8.3 y) reflects the observed pace at which the most accessible contamination is cleared or attrited. WARNING: do NOT let f_rec go to zero - the 2014-2021 Donbas contact line (3,523 Ukraine events) is some of the densest legacy contamination in the country.

5. EVENT CLARITY. f_clar(1) = 1.0 (clear single event), f_clar(2) = 0.6 (unclear / aggregated). Justification: clarity=2 records (4959 of 31,547 in Ukraine) bundle several incidents with weaker sourcing; down-weight but do not discard.

6. GEOCODING PRECISION (residual reliability only). f_prec(1) = 1.0, f_prec(2) = 1.0, f_prec(3) = 1.0, f_prec(4) = 0.9, f_prec(5) = 0.8, f_prec(6) = 0.6, f_prec(7) = 0.0 (DROP the event entirely).
   CRITICAL: the PRIMARY handling of where_prec is the kernel bandwidth in (b), not this factor. Because the kernel is mass-normalised, an imprecise event already contributes far less per cell. f_prec is only a small extra penalty for the fact that coarsely-geocoded records also tend to be poorly sourced. Setting f_prec == 1 for all levels 1-6 is also defensible; do NOT set it much below the values above or you are penalising the same defect twice. where_prec = 7 is dropped because the Ukraine wp=7 events are in the Black Sea (lat ~45.2, lon ~30.6-31.4) where landmines are not the hazard of interest; there are only 10 of them.

WORKED EXAMPLE: a 2023 Bakhmut-area record, tov=1, best=50, D=1, wp=1, clarity=1, T_ref=2025.0:
  w = 1.00 * 3.317 * 1.000 * (0.35 + 0.65*exp(-2/12) = 0.900) * 1.0 * 1.0 = 2.985.
_source: Functional forms and parameter values are my specification; the empirical anchors (254 zero-best events, max best=15996, 26.4% multi-day, clarity=2 count 4959, 10 wp=7 events in the Black Sea) are verified counts from the Ukraine subset._

### [likely] (b) EXACT kernel K and the where_prec -> sigma mapping, with derivation
BANDWIDTH COMPOSITION. Each event gets one scalar bandwidth combining three independent sources of spread, added in quadrature (valid because they are independent displacements):
  sigma_e = sqrt( sigma_geo(wp_e)^2 + sigma_phys^2 + sigma_dur(D_e)^2 )
  - sigma_phys = 2.0 km : the PHYSICAL footprint of contamination around a reported battle point (minefields, artillery UXO scatter, defensive belts). Non-zero even for wp=1. Also absorbs the fact that 31,547 events collapse onto only 2442 distinct coordinates, i.e. even 'exact' points are really town centroids with genuine intra-settlement spread.
  - sigma_dur(D) = min( 1.5 * sqrt(D - 1) , 15.0 ) km : a diffusive model of front movement during a multi-day record. D=1 -> 0; D=7 -> 3.67; D=30 -> 8.08; D=101 -> 15.0 (cap binds); D=365 -> 15.0.
  - sigma_geo(wp) : geolocation uncertainty, table below.

DERIVATION OF sigma_geo. If the true location is uniform on a disc of radius R about the coded point, then E[r^2] = R^2/2. An isotropic 2-D Gaussian with per-axis sd sigma has E[r^2] = 2*sigma^2. Matching the second moment gives the master rule
      sigma = R/2 = sqrt(A/pi)/2 = sqrt( A / (4*pi) )
where A is the area of the admin unit the event was coded to.

TABLE (defaults for Ukraine; recompute per country with the same rule):
  wp=1 exact point            : sigma_geo = 0.3 km   (coordinate rounding only). sigma_e = sqrt(0.09+4) = 2.02 km.
  wp=2 point with ~25 km radius: R = 25 -> sigma_geo = 12.5 km. sigma_e = sqrt(156.25+4) = 12.66 km.
  wp=3 adm_2 (raion) centroid : Ukraine post-2020 raion mean area 603,550/136 = 4,438 km^2 -> R = 37.6 -> sigma = 18.8; pre-2020 raion 603,550/490 = 1,232 km^2 -> R = 19.8 -> sigma = 9.9. GED's 172 distinct Ukraine adm_2 names are a mix of both regimes, so DEFAULT sigma_geo = 15.0 km. sigma_e = 15.13 km.
  wp=4 adm_1 (oblast) centroid: Ukraine 603,550 km^2 over ~25 oblasts = 24,100 km^2 -> R = 87.6 -> sigma = 43.8. DEFAULT sigma_geo = 45.0 km. sigma_e = 45.04 km. (Donetsk oblast specifically: 26,517 km^2 -> R = 91.9 -> sigma = 45.9.)
  wp=5 multi-adm1 area        : effective area ~3 oblasts = 72,000 km^2 -> R = 151.4 -> sigma = 75.7. DEFAULT sigma_geo = 75.0 km. sigma_e = 75.03 km.
  wp=6 country centroid       : Ukraine A = 603,550 km^2 -> R = 438.3 -> sigma = 219.2. DEFAULT sigma_geo = 220.0 km. sigma_e = 220.0 km.
  wp=7                        : DROPPED (w = 0). Equivalent to sigma = infinity.

STRONGLY PREFERRED REFINEMENT for wp in {3,4,5,6}: do not use a Gaussian at the centroid at all. Spread w_e UNIFORMLY (area-weighted) over the actual admin polygon's cells: K_e(x_i) = 1{x_i in P_e} / Area(P_e). This is strictly better because the true posterior over the location IS uniform-ish over the polygon, and it removes the artefact of a Gaussian bulge at the centroid. For Ukraine this is decisive: all 1194 wp=6 events sit at 49.000000/32.000000, and a Gaussian there puts a spurious mound over Cherkasy oblast, which had almost no fighting. Since the HTML must embed geography at build time anyway, you will already have adm1/adm2 polygons; use them. Fall back to the Gaussian table only where a polygon is unavailable.

KERNEL (Gaussian default, truncated and renormalised):
  K_e(x) = (1 / (2*pi*sigma_e^2)) * exp( -||x - x_e||^2 / (2*sigma_e^2) ) / Z   for ||x - x_e|| <= 3.5*sigma_e, else 0.
  Z = 1 - exp(-3.5^2/2) = 1 - exp(-6.125) = 0.9978055.
  Units: km^-2. Integral over the plane = 1 exactly. This MASS NORMALISATION is the whole point: a country-level event spreads the same total weight over 1.5e5 km^2 instead of concentrating it.

EXPOSURE:
  E_i = A_i * sum_over_events_e [ w_e * K_e(x_i) ]     [units: dimensionless weight-count per cell]
  rho^E_i = E_i / A_i = sum_e w_e * K_e(x_i)            [units: weight per km^2]
  Total mass identity: sum_i E_i = sum_e w_e * q_e, where q_e = fraction of K_e's mass falling inside the modelled land domain (edge/coast correction, computed at build time by summing K_e over land cells). Use q_e in the calibration of (f).

HEAVY-TAILED ALTERNATIVE (recommended if you want robustness to minefields laid far from the reported battle): bivariate Student-t with nu degrees of freedom,
  K_e(x) = (1 / (2*pi*s_e^2)) * (1 + ||x - x_e||^2 / (nu * s_e^2))^(-(nu+2)/2),  with  s_e = sigma_e * sqrt((nu-2)/nu).
  (The d=2 multivariate-t prefactor Gamma((nu+2)/2)/Gamma(nu/2) = nu/2 cancels to exactly 1/(2*pi*s^2).) Matching E[||r||^2] = 2*s^2*nu/(nu-2) = 2*sigma^2 gives the s_e above. Default nu = 4 -> s_e = sigma_e/sqrt(2). Truncate at 10*sigma_e and renormalise numerically.

COMPUTE NOTE: truncation at 3.5 sigma keeps this O(events * cells_in_support). For Ukraine at h=5 km the wp=6 events touch the whole country (~24,000 land cells x 1194 events = 2.9e7 ops) - do this ONCE at build time, never in the browser.
_source: sigma = sqrt(A/(4*pi)) derived by matching E[r^2] of a uniform disc to an isotropic 2-D Gaussian; Ukraine area 603,550 km^2 and raion/oblast counts are standard geography; the wp -> centroid mapping is verified from the data cross-tab; the bivariate-t normalisation is derived from the standard multivariate-t density at d=2._

### [likely] Prior: the CORRECT Gamma parameterisation (critique of the proposed skeleton)
PROPOSED PRIOR MEAN (mines per cell):
  m_i = A_i * ( a0 + kappa * rho^E_i )  =  a0 * A_i  +  kappa * E_i
  where a0 [mines/km^2] is a diffuse non-conflict-explained background and kappa [mines per unit exposure weight] converts conflict exposure to mines.

PROBLEM WITH THE SKELETON AS WRITTEN (alpha_i = alpha_0 + kappa*E_i, beta_i = beta_0): it implies alpha_i = beta_0 * m_i exactly (since m_i = alpha_i/beta_0), i.e. a constant variance-to-mean ratio of 1/beta_0 - which is actually the right idea - but (i) alpha_0 does not scale with cell area, so the model is NOT invariant to grid resolution, and (ii) there is no floor on the shape, so a cell with m_i = 1e-6 gets alpha_i ~ 1e-6, a degenerate spike at zero with CV ~ 1000.

RECOMMENDED PARAMETERISATION:
  alpha_i = alpha_floor + m_i / psi
  beta_i  = alpha_i / m_i
  lambda_i ~ Gamma(shape = alpha_i, rate = beta_i)
  Prior mean  = alpha_i/beta_i = m_i  (exact, by construction)
  Prior var   = alpha_i/beta_i^2 = m_i^2 / alpha_i = m_i^2 / (alpha_floor + m_i/psi)
  Variance-to-mean ratio VMR_i = m_i / alpha_i -> psi as m_i grows; CV_i -> 1/sqrt(alpha_floor) as m_i -> 0.
  DEFAULTS: psi = 8.0 mines (strong over-dispersion; minefields are laid in clustered belts, not as a Poisson scatter), alpha_floor = 0.4 (CV = 1.58 for near-empty cells - honest uncertainty about emptiness, not false confidence).

SCALE-INVARIANCE PROOF (why this parameterisation and not the skeleton's): merge two adjacent cells of equal area into one. m doubles. For m >> psi*alpha_floor, alpha ~ m/psi doubles, and Var ~ m*psi doubles. The variance of the SUM of two independent cells is also 2*m*psi. So the merged-cell prior and the summed-cells prior agree in both moments. The skeleton's fixed alpha_0 breaks this: at half the cell edge you get 4x as many alpha_0 terms.

RELATION TO THE SKELETON: set alpha_floor = 0 and psi = 1/beta_0 and the two coincide with m_i = (alpha_0 + kappa*E_i)/beta_0. So the skeleton is a special case; I am adding area-scaling of the background term and a shape floor.
_source: reasoning; scale-invariance verified by the two-moment merge argument shown._

### [verified] Likelihood: the Poisson form is EXACT, not an approximation (thinning lemma)
SETUP. The robot sweeps cell i covering an effective fraction c_i in [0,1] of the cell's area (c_i = swept_area / A_i, adjusted for terrain the platform cannot enter). Detector sensitivity s in (0,1] = P(a mine inside the swept footprint is detected). Define the EFFECTIVE EXPOSURE
  t_i = c_i * s          [dimensionless, in (0,1]]

LEMMA (Poisson thinning). Let M_i | lambda_i ~ Poisson(lambda_i) be the true number of mines in cell i. Each mine is independently detected with probability t_i (it must be inside the swept fraction, prob c_i, AND be picked up, prob s). Then:
  (1) D_i | lambda_i ~ Poisson(lambda_i * t_i)   EXACTLY - not an approximation, and it does not require M_i to be large.
  (2) The undetected remainder N_i = M_i - D_i satisfies N_i | lambda_i ~ Poisson(lambda_i * (1 - t_i)), and N_i is INDEPENDENT of D_i given lambda_i.
Proof: the standard Poisson colouring/thinning theorem. This matters: the skeleton's Poisson likelihood is exactly right, and (2) gives the post-clearance state for free.

CONJUGATE POSTERIOR (no false positives; see (j) for the FP case):
  lambda_i | y_i  ~ Gamma( alpha_i + y_i , beta_i + t_i )
  where y_i is the observed count of CONFIRMED mines.

SEQUENTIAL SWEEPS. If the robot sweeps cell i repeatedly with exposures t_i^(1), t_i^(2), ... yielding y_i^(1), y_i^(2), ..., the posterior is Gamma(alpha_i + sum_k y_i^(k), beta_i + sum_k t_i^(k)). Two sufficient statistics per cell: a running (Y_i, T_i). This is the ONLY state the robot needs to carry - critical for the deliverable-B log format.

CLEARANCE ACCOUNTING (what the robot actually cares about). After the sweep, the number of mines REMAINING in cell i has the marginal
  N_i | y_i  ~  NegBin( r = alpha_i + y_i , p = (beta_i + t_i) / (beta_i + t_i + 1 - t_i) ) = NegBin( r = alpha_i + y_i , p = (beta_i + t_i)/(beta_i + 1) )
  E[N_i | y_i] = (alpha_i + y_i) * (1 - t_i) / (beta_i + t_i)
  P(cell i is now clean) = P(N_i = 0) = ( (beta_i + t_i) / (beta_i + 1) )^(alpha_i + y_i)
This is the correct residual-risk number to paint on the map after a sweep, and it is NOT the same as the posterior mean of lambda_i.
_source: Poisson thinning/colouring theorem; the NegBin marginal follows from the Gamma-Poisson mixture with rate (1-t)._

### [verified] (c) NEGATIVE result: robot sweeps and finds nothing
Set y_i = 0. The likelihood is p(y_i = 0 | lambda_i) = exp(-lambda_i * t_i), which is an exponential in lambda_i and therefore conjugate: it updates the RATE only.

  POSTERIOR:  lambda_i | y_i = 0  ~  Gamma( alpha_i , beta_i + t_i )        [shape unchanged, rate increased]
  POSTERIOR MEAN:     E[lambda_i | 0] = alpha_i / (beta_i + t_i) = m_i * beta_i/(beta_i + t_i)
  SHRINK FACTOR:      E[lambda_i | 0] / m_i = beta_i / (beta_i + t_i)  < 1  strictly, for any t_i > 0.  <-- this is the required demonstration that the mean drops.
  POSTERIOR VARIANCE: Var[lambda_i | 0] = alpha_i / (beta_i + t_i)^2 = Var_prior * (beta_i/(beta_i+t_i))^2
  POSTERIOR CV:       unchanged at 1/sqrt(alpha_i). A null sweep rescales the whole distribution towards zero without changing its shape - it reduces the mean and the sd by the SAME factor. This is the correct behaviour: a clean sweep lowers your estimate but does not make you proportionally more certain.

NOTE ON DIMINISHING RETURNS: the shrink factor beta/(beta+t) is bounded below by beta/(beta+1) (since t <= 1). A single perfect sweep (c=1, s=1) of a cell can never drive the posterior mean below m_i * beta_i/(beta_i+1). With beta_i large (low-mean cells) the drop is small; with beta_i small (high-mean cells) one clean sweep is very informative. This is exactly right and is the reason the acquisition function in (i) is proportional to t/(beta+t).

PROBABILITY THE CELL IS CLEAN (what the UI should display, not the mean):
  Prior:     P(M_i = 0) = ( beta_i / (beta_i + 1) )^alpha_i
  After a null sweep: P(N_i = 0 | y=0) = ( (beta_i + t_i) / (beta_i + 1) )^alpha_i

WORKED NUMERIC EXAMPLE (robot-scale, 10 m x 10 m cell = 1e-4 km^2, contamination density rho = 2000 mines/km^2 so m = 0.2 mines; psi = 8, alpha_floor = 0.4):
  alpha = 0.4 + 0.2/8 = 0.425 ;  beta = 0.425/0.2 = 2.125 ;  Var_prior = 0.425/2.125^2 = 0.09412, sd = 0.3068.
  Sweep with c = 0.9, s = 0.85 -> t = 0.765. Find NOTHING.
  Posterior: Gamma(0.425, 2.890). Mean = 0.1471 (shrink factor 2.125/2.890 = 0.7353). Var = 0.425/2.890^2 = 0.05089, sd = 0.2256.
  P(>=1 mine present) before: 1 - (2.125/3.125)^0.425 = 1 - exp(0.425*ln 0.68) = 1 - exp(-0.1638) = 0.1511.
  P(>=1 mine REMAINING) after: 1 - (2.890/3.125)^0.425 = 1 - exp(0.425*(-0.07821)) = 1 - exp(-0.03324) = 0.0327.
  So a single imperfect sweep takes the cell from 15.1% to 3.3% residual risk. It does NOT take it to zero, and any UI that paints it green is lying.
_source: Direct algebra on the Gamma-Poisson conjugate pair; the numeric example was computed by hand and each intermediate is shown._

### [likely] (d) Spatial coupling: column-stochastic evidence spreading, with an EXPLICIT error budget
THE PROBLEM. Per-cell conjugate updating is independent by construction, so a detection in cell A leaves cell B untouched. That is wrong: minefields are laid in belts with a spatial correlation length of tens to hundreds of metres.

WHAT I REJECT AND WHY. A log-Gaussian Cox process or a CAR/GMRF prior with a Laplace approximation gives the right joint posterior but requires a sparse Cholesky solve per update (O(n^1.5) for a 2-D lattice) and destroys conjugacy. On a 160,000-cell robot grid with updates at sensor rate, this is not viable. I therefore specify an approximation and state its error honestly.

THE APPROXIMATION - COLUMN-STOCHASTIC EVIDENCE SPREADING.
  Define a spatial spread matrix S with entries
    S_ij = (1 - ell) * delta_ij  +  ell * [ A_i * g(d_ij) / sum_k A_k * g(d_kj) ]
  where g(d) = exp( -d^2 / (2 * sigma_c^2) ) truncated at 3*sigma_c, ell in [0,1] is the LEAK FACTOR, and sigma_c is the minefield correlation length.
  KEY PROPERTY: every COLUMN of S sums to 1 (sum_i S_ij = 1). This is the mass-conservation condition, and it is column sums, not row sums. Getting this backwards invents or destroys evidence.
  DEFAULTS: ell = 0.35; sigma_c = 60 m for the robot grid (typical minefield belt width / pattern spacing), sigma_c = 3 km for the national display grid.

  SMOOTHED SUFFICIENT STATISTICS:
    y~_i = sum_j S_ij * y_j        (real-valued; Gamma accepts a non-integer shape, this is fine)
    t~_i = sum_j S_ij * t_j
  UPDATE:  lambda_i | data ~ Gamma( alpha_i + y~_i , beta_i + t~_i )
  CONSERVATION: sum_i y~_i = sum_j y_j and sum_i t~_i = sum_j t_j, exactly. No evidence is created or lost.

WHEN IT IS EXACT. E[y~_i | lambda] = sum_j S_ij * lambda_j * t_j. The pretended model says this equals lambda_i * t~_i = lambda_i * sum_j S_ij t_j. These are equal IF AND ONLY IF lambda_j = lambda_i for all j in the support of S_i*. So the method is EXACT on a locally-constant field and nowhere else. It is NOT conjugate Bayes on any model; it is a moment-matching heuristic.

ERROR BUDGET - BE EXPLICIT ABOUT ALL THREE:
  (E1) MEAN BIAS. Second-order Taylor of lambda about x_i:
         bias_i = E[y~_i] - lambda_i*t~_i  ~=  (t~_i * sigma_c^2 / 2) * Laplacian(lambda)(x_i) * ell
       i.e. RELATIVE bias ~= (ell * sigma_c^2 / 2) * (Laplacian lambda)/lambda. The estimator is biased UP inside local minima and DOWN on local maxima - it smears minefield EDGES by roughly sigma_c. OPERATIONAL RULE: choose sigma_c no larger than the smallest minefield feature you need to resolve; the boundary of a cleared lane will be blurred over ~sigma_c and you must not treat a cell within sigma_c of a detection as surveyed.
  (E2) PER-CELL VARIANCE (conservative). True Var(y~_i | lambda) = sum_j S_ij^2 * lambda_j * t_j, but the pretended Poisson model assumes Var = lambda_i * t~_i = sum_j S_ij lambda_j t_j. Since 0 <= S_ij <= 1, we have S_ij^2 <= S_ij, so the TRUE variance is SMALLER than assumed. Therefore the per-cell marginal posterior is too WIDE - the method is conservative/under-confident per cell. This is the safe direction for a demining application. The inflation factor is n_eff,i = (sum_j S_ij t_j) / (sum_j S_ij^2 t_j) >= 1.
  (E3) JOINT VARIANCE (anti-conservative - THE DANGEROUS ONE). Neighbouring cells share the same raw observations, so their posteriors are strongly positively correlated, yet the model treats them as independent. Any AGGREGATE (district total, total mines on a planned route) computed by summing independent per-cell variances will UNDER-STATE its uncertainty, badly. This must be corrected explicitly - see the DEFF formula in (g). Do not skip this.

CONSISTENCY WITH THE HIERARCHY. Short-range coupling (metres to kilometres) is handled by S; long-range coupling (raion, oblast, country) is handled EXACTLY and conjugately by the hierarchical shrinkage in (e). The two act on disjoint scales, so set sigma_c well below the adm_2 scale (15 km for Ukraine) to avoid double-counting the same correlation.
_source: reasoning; the exactness condition, the column-stochastic conservation identity, the Laplacian bias expansion and the S_ij^2 <= S_ij variance inequality are each derived above and are checkable._

### [likely] (e) Hierarchical structure and the closed-form empirical-Bayes estimator
TREE. country -> adm_1 (28 distinct in the Ukraine GED subset) -> adm_2 (172 distinct) -> cell. Use the GED adm_1/adm_2 strings joined to your embedded polygons; assign each cell to the polygon containing its centroid.

MODEL (relative-risk / offset form - this is the standard disease-mapping trick and it keeps everything conjugate):
  lambda_i = theta_v(i) * e_i,
  where e_i = A_i * (a0 + kappa * rho^E_i) = m_i is the OFFSET (expected mines from the conflict prior alone) and theta_v is a dimensionless relative risk attached to node v = the cell's parent in the tree. theta == 1 means 'the conflict prior was right here'.
  Observation: y_i | theta ~ Poisson( theta_v(i) * e_i * t_i ). Write the EXPECTED COUNT under theta=1 as  Ehat_i = e_i * t_i.

EMPIRICAL-BAYES AT ONE LEVEL (Clayton-Kaldor method of moments, closed form, O(M)).
Let a node have children m = 1..M with observed counts y_m and expected counts Ehat_m (for an internal node, y_m and Ehat_m are the SUMS over that child's descendant cells). Assume theta_m ~ Gamma(a, b) i.i.d. with mean mu = a/b and variance v = a/b^2. Then:
  mu_hat = ( sum_m y_m ) / ( sum_m Ehat_m )
  v_hat  = [ sum_m Ehat_m * ( y_m/Ehat_m - mu_hat )^2  -  (M - 1) * mu_hat ]  /  [ sum_m Ehat_m  -  (sum_m Ehat_m^2) / (sum_m Ehat_m) ]
  v_hat <- max( v_hat , v_min )   with v_min = mu_hat^2 / alpha_max , alpha_max = 200 (prevents a degenerate zero-variance fit when all children agree)
  a_hat = mu_hat^2 / v_hat ,  b_hat = mu_hat / v_hat
The subtracted (M-1)*mu_hat term removes the Poisson sampling variance so that v_hat estimates the BETWEEN-child variance only. Both a_hat and b_hat are closed form; there is no iteration.

SHRINKAGE (the payoff):
  theta_m | y_m ~ Gamma( a_hat + y_m , b_hat + Ehat_m )
  E[theta_m | y_m] = (a_hat + y_m)/(b_hat + Ehat_m) = W_m * (y_m/Ehat_m) + (1 - W_m) * mu_hat ,  W_m = Ehat_m / (b_hat + Ehat_m)
A cell with little robot exposure is pulled to its raion's mean; a raion with little exposure is pulled to its oblast's; an oblast to the country. Exactly the behaviour required.

TWO-PASS ALGORITHM (O(n) total, run on the robot in real time):
  UP-PASS (leaves to root): for each node v, Y_v = sum of y over descendant cells, Ehat_v = sum of Ehat over descendant cells. At each internal node, fit (a_hat_v, b_hat_v) from its children by the formula above.
  DOWN-PASS (root to leaves): the prior for node v's children uses mean mu_v* = E[theta_v | data] (the parent's POSTERIOR mean, not mu_hat_v) and variance v_v* = v_hat_v + Var[theta_v | data]. Then a = mu_v*^2 / v_v*, b = mu_v* / v_v*. The added Var[theta_v | data] = (a_hat + Y_v)/(b_hat + Ehat_v)^2 is what propagates the parent's remaining uncertainty down. Skipping it is the single most common error in cascaded EB.
  FINAL: lambda_i | data ~ Gamma( a_leaf + y_i , (b_leaf + Ehat_i) / e_i ). [The 1/e_i on the rate converts theta back to lambda: if theta ~ Gamma(A,B) then lambda = theta*e ~ Gamma(A, B/e).]

APPROXIMATION ERROR (state it): this is plug-in / type-II-maximum-likelihood EB. It (i) ignores uncertainty in (a_hat, b_hat) themselves, which makes the shrinkage slightly too aggressive when M is small - inflate v_hat by M/(M-2) for M > 4 as a cheap Morris-style correction, and do not fit a level with M < 4 children (pass the parent's hyperparameters straight through instead); (ii) does the up-pass with moment estimators rather than the exact marginal likelihood. Neither is MCMC-free-lunch: the estimator is consistent as M grows and is the standard tool in small-area disease mapping.

COLD START: with zero robot data everywhere, sum_m y_m = 0 and mu_hat = 0/0. Then EB is undefined and must be SKIPPED: theta == 1 everywhere and the prior is purely the calibrated conflict prior of (f). EB only activates in subtrees containing at least one swept cell.
_source: Clayton-Kaldor (1987) moment estimator for the Poisson-Gamma small-area model, transcribed and adapted; the offset/relative-risk reparameterisation and the two-pass variance propagation are my specification. adm_1=28, adm_2=172 verified from the data._

### [likely] (f) Calibration to an external national total - exact closed form
TARGETS. Let the externally supplied ground truth for country C be:
  N*  = target total number of mines in C, and/or
  A*  = target contaminated area in C (km^2).
If you only have A* (e.g. a Landmine Monitor confirmed/suspected hazardous area figure), convert with a mine areal density: N* = A* * delta, delta in mines per km^2 of CONTAMINATED land. delta MUST be an explicit, user-facing slider in the HTML, not a buried constant - it is the single most uncertain number in the whole pipeline and it multiplies every output linearly. [CAUTION: the widely quoted Ukraine figure of ~139,000-174,000 km^2 is a POTENTIALLY-contaminated survey envelope, not confirmed hazardous area; using it as A* will overstate N* by one to two orders of magnitude. Source A* and delta explicitly and display the citation in the UI.]

ONE-TARGET CALIBRATION (closed form, exact, O(1)). The prior mean is linear in (a0, kappa):
  sum_{i in C} m_i = a0 * sum_i A_i + kappa * sum_i E_i = a0 * A_C + kappa * W_C
  where A_C = total modelled land area of C and W_C = sum_i E_i = sum_{e in C} w_e * q_e  (q_e = fraction of kernel e's mass inside the land domain - the edge correction from (b)). Note W_C is computed from the EVENTS directly, no grid sum needed.
Choose pi in [0,1] = the fraction of the national total attributed to diffuse background rather than to mapped conflict events. DEFAULT pi = 0.15 (accounts for contamination from events GED never recorded, legacy WWII ordnance, and the coarse-geocoded tail). Then:
  a0    = pi * N* / A_C                  [mines per km^2]
  kappa = (1 - pi) * N* / W_C            [mines per unit event weight]
This hits sum_i m_i = N* EXACTLY, in closed form, with no iteration.

POST-HOC MULTIPLICATIVE RESCALING (use when anything upstream changes and you want to preserve the SHAPE of the field): let G = N* / sum_i m_i. Then set
  m_i  <- G * m_i ,  alpha_i <- alpha_floor + G*m_i/psi ,  beta_i <- alpha_i / (G*m_i).
If instead you want to preserve the variance-to-mean ratio exactly, use alpha_i <- G * alpha_i and leave beta_i unchanged; then mean and variance both scale by G and G^2 respectively... note these two choices differ and you should pick the first (re-derive alpha from the new mean), because psi is the physically meaningful quantity.

TWO-TARGET CALIBRATION (match BOTH total mines and total contaminated area). Second constraint:
  sum_{i in C} A_i * P(cell i contaminated)  =  A*,  where  P(contaminated) = 1 - P(M_i = 0) = 1 - ( beta_i/(beta_i + 1) )^alpha_i.
Procedure: (1) fix kappa from the one-target formula at a trial pi; (2) the area constraint is MONOTONE DECREASING in pi at fixed N* (moving mass from the concentrated conflict field to the flat background spreads contamination over more cells, increasing the area). So solve for pi by BISECTION on [0,1], ~20 evaluations of an O(n) sum. Fully deterministic, runs in milliseconds at build time. Do NOT attempt this in the browser; bake the result in.
Note the area constraint is resolution-dependent (P(contaminated) is per-cell, so the answer depends on h). Fix h before calibrating and state it.

PER-COUNTRY: run this independently for every country in the GED with its own N*_c; countries with no external figure inherit a global delta applied to their own exposure. Do NOT calibrate globally and then slice - conflict intensity per mine varies enormously between theatres.
_source: reasoning; the closed-form a0/kappa split follows directly from the linearity of m_i in (a0, kappa) and the mass identity sum_i E_i = sum_e w_e q_e. The Ukraine survey-envelope caveat is flagged as a caution, not asserted as a figure._

### [verified] (g) Aggregation to district totals: moment-matched Gamma, quantiles, and the correlation correction
PROBLEM. For a district D, S_D = sum_{i in D} lambda_i is a sum of independent Gammas with DIFFERENT rates beta_i, which is not Gamma (it is a hypoexponential-type mixture with no closed form).

WELCH-SATTERTHWAITE MOMENT MATCHING (the usable answer):
  M_D = sum_{i in D} alpha_i / beta_i                (mean, mines)
  V_D = sum_{i in D} alpha_i / beta_i^2              (variance, independence assumed - CORRECT THIS, see below)
  Fit S_D ~ Gamma( A_D , B_D ) with  B_D = M_D / V_D ,  A_D = M_D^2 / V_D.
  This is EXACT in the first two moments by construction, and exactly correct as a distribution when all beta_i are equal.

CORRELATION CORRECTION (mandatory - this is error (E3) from item (d)). The independent V_D under-states the truth because (i) neighbouring cells share the same smeared observations and (ii) the true latent field is smooth. Apply a design effect:
  V_D^corr = DEFF * V_D ,   DEFF = min( n_D , max( 1 , 2*pi*L^2 / A_cell ) )
  Derivation: with an exponential correlation r(d) = exp(-d/L), sum over neighbours of r ~= (1/A_cell) * integral_0^inf exp(-r/L) * 2*pi*r dr = 2*pi*L^2 / A_cell. n_D = number of cells in D; capping at n_D is required because a district smaller than a correlation patch is fully correlated.
  L = spatial correlation length of the residual field. DEFAULTS: L = 20 km for the national 5 km grid (DEFF = 2*pi*400/25 = 100.5, i.e. the sd is 10x the naive value); L = 60 m for the 5 m robot grid (DEFF = 2*pi*0.0036/2.5e-5 = 905, capped at n_D). These are large factors. They are real. Reporting a district total of '4,200 +/- 12 mines' is the failure mode this prevents.
  Then recompute B_D = M_D / V_D^corr, A_D = M_D^2 / V_D^corr.

90% CREDIBLE INTERVAL - WILSON-HILFERTY (closed form, no special functions, safe in JS):
  Q(p) = (A_D / B_D) * ( 1 - 1/(9*A_D) + z_p / (3*sqrt(A_D)) )^3 ,  clipped at 0.
  z_0.05 = -1.644854 ,  z_0.95 = +1.644854.
  90% CI = [ Q(0.05) , Q(0.95) ]. Accuracy: relative error in the quantile < ~1% for A_D > 5, < ~3% for A_D > 1. For A_D < 1 (tiny districts) fall back to bisection on the regularised lower incomplete gamma P(A,Bx) using the series sum_{k>=0} x^k / ((A+1)...(A+k)) * x^A e^{-x} / Gamma(A+1), 30 terms.

KNOWN DIRECTION OF THE W-S ERROR (do not hide this). True third central moment of S_D is mu3 = 2 * sum_i alpha_i/beta_i^3, so true skewness = mu3 / V_D^(3/2). The matched Gamma has mu3 = 2*A_D/B_D^3 = 2*V_D^2/M_D, so matched skewness = 2*sqrt(V_D)/M_D. By Cauchy-Schwarz, (sum alpha/beta^2)^2 <= (sum alpha/beta)(sum alpha/beta^3), i.e. sum alpha/beta^3 >= V_D^2/M_D. Therefore TRUE SKEWNESS >= MATCHED SKEWNESS always, with equality iff all beta_i are equal. The Welch-Satterthwaite Gamma systematically UNDER-STATES the upper tail when rates are heterogeneous. Correction if you need the upper tail honestly (Cornish-Fisher):
  Q(p) ~= M_D + sqrt(V_D)*( z_p + (g1/6)*(z_p^2 - 1) ) ,  g1 = 2*sum_i (alpha_i/beta_i^3) / V_D^(3/2)
  and report max of this and the Wilson-Hilferty value at p = 0.95.

DISTRICT COUNT (what the UI headline should actually be). The user wants 'estimate 100 landmines in this district' - that is a COUNT N_D = sum_i M_i, not the latent intensity. Marginally,
  E[N_D] = M_D ,  Var[N_D] = M_D + V_D^corr   (Poisson variance adds to intensity variance)
  N_D ~= NegBin( r = M_D^2 / V_D^corr , p = M_D / (M_D + V_D^corr) ) by moment matching. Note r equals A_D exactly, consistent with the Gamma fit.
  HEADLINE NUMBER = round(M_D) + R_D, where R_D = the count of REGISTERED mines in D (deterministic, the dots).
  Display the 90% CI alongside it, always. Never display a point estimate alone on a demining map.
_source: Welch-Satterthwaite moment matching; the skewness under-statement is proved above by Cauchy-Schwarz; Wilson-Hilferty is the standard cube-root Gamma quantile approximation; the DEFF integral 2*pi*L^2 is computed from integral_0^inf exp(-r/L)*2*pi*r dr = 2*pi*L^2._

### [verified] (h) Predictive distribution for the next sweep: exact Negative Binomial parameters
QUESTION: the robot is about to sweep cell i with coverage c (effective exposure t = c*s). How many mines will it find? Let the CURRENT posterior (after all prior updates) be lambda_i ~ Gamma(alpha_i', beta_i'). Then y_new | data ~ NegBin with the Gamma-Poisson mixture:

  P(y_new = k) = [ Gamma(alpha_i' + k) / ( Gamma(alpha_i') * k! ) ] * p^(alpha_i') * (1 - p)^k ,  k = 0,1,2,...
  where  p = beta_i' / (beta_i' + t)   and   1 - p = t / (beta_i' + t).
  In (r, p) convention: r = alpha_i' (the SHAPE, which may be non-integer - use Gamma functions, or the stable recursion P(k) = P(k-1) * (alpha'+k-1)/k * (1-p)).
  MEAN:     E[y_new] = r*(1-p)/p = alpha_i' * t / beta_i'
  VARIANCE: Var[y_new] = r*(1-p)/p^2 = (alpha_i' * t / beta_i') * (1 + t/beta_i')
  VMR:      Var/Mean = 1 + t/beta_i' > 1 (always over-dispersed relative to Poisson - correct, because lambda is uncertain)
  P(find nothing): P(y_new = 0) = p^(alpha_i') = ( beta_i' / (beta_i' + t) )^(alpha_i')
  P(find at least one): 1 - ( beta_i'/(beta_i'+t) )^(alpha_i')

NUMERICALLY STABLE EVALUATION IN JS: compute log P(0) = alpha'*(log beta' - log(beta'+t)) then iterate log P(k) = log P(k-1) + log(alpha'+k-1) - log(k) + log t - log(beta'+t). No Gamma function needed.

WITH FALSE POSITIVES (see (j)): the number of ALARMS a_new = y_true + FP where FP ~ Poisson(f_i) independently, f_i = phi * c_i * A_i. The pgf is
  G(z) = exp( f_i*(z - 1) ) * ( beta_i' / (beta_i' + t*(1 - z)) )^(alpha_i')
  E[a_new] = alpha_i'*t/beta_i' + f_i ;  Var[a_new] = (alpha_i'*t/beta_i')*(1 + t/beta_i') + f_i ;  P(a_new = 0) = exp(-f_i) * (beta_i'/(beta_i'+t))^(alpha_i').
  The exact pmf is the convolution of NegBin and Poisson (a Delaporte distribution); evaluate it by direct convolution to k = 30, or moment-match to a NegBin with r = mean^2/(var - mean), p = mean/var.

USE: this is what the robot's mission planner needs to answer 'is this cell worth the battery' and it is what the HTML should show as the tooltip 'if you sweep this 5 km cell at 2% coverage you expect to find 3 mines (90% interval 0-9)'.
_source: Standard Gamma-Poisson conjugate predictive; the Delaporte pgf is the product of the Poisson and NegBin pgfs._

### [verified] (i) Value of information: an EXACT closed-form acquisition function
PRIMARY ACQUISITION - EXPECTED POSTERIOR VARIANCE REDUCTION. This has an exact closed form, which is the main result here.
  Prior variance: V_i = alpha_i / beta_i^2.
  If the robot sweeps with exposure t_i and observes y, the posterior variance is (alpha_i + y)/(beta_i + t_i)^2. Taking the expectation over the predictive y ~ NegBin of item (h), with E[y] = alpha_i*t_i/beta_i:
    E[alpha_i + y] = alpha_i + alpha_i*t_i/beta_i = alpha_i*(beta_i + t_i)/beta_i
    E[ Var_post ] = alpha_i*(beta_i + t_i) / ( beta_i * (beta_i + t_i)^2 ) = alpha_i / ( beta_i * (beta_i + t_i) )
  Therefore:
    VOI_i(t_i)  =  V_i - E[Var_post]  =  alpha_i / beta_i^2  -  alpha_i / (beta_i*(beta_i + t_i))
                =  alpha_i * t_i / ( beta_i^2 * (beta_i + t_i) )
                =  V_i * t_i / (beta_i + t_i)                      <-- EXACT. O(1). No sum, no special function.
  Interpretation: expected variance reduction = prior variance times the fraction of the total 'pseudo-exposure' the sweep contributes. Note it does not depend on the realised y at all - the expected variance reduction is deterministic, which is the standard and convenient property of the Gamma-Poisson pair.

SPATIAL VERSION (sweeping cell i also informs its neighbours through S from item (d)):
  Let the exposure delivered to cell j by sweeping cell i be  t_{j<-i} = S_ji * t_i.
  VOI_i^spatial = sum_{j : S_ji > 0}  V_j * t_{j<-i} / ( beta_j + t_{j<-i} )
  The sum has O((3*sigma_c/h)^2) terms; at sigma_c = 60 m and h = 5 m that is ~4,000 terms per candidate cell, so precompute S once as a separable Gaussian and evaluate by two 1-D passes.

EXACT EXPECTED INFORMATION GAIN (if you specifically want nats, not variance). The KL divergence between the posterior and prior Gammas is closed form:
  KL( Gamma(alpha+y, beta+t) || Gamma(alpha, beta) ) = y*digamma(alpha+y) - lnGamma(alpha+y) + lnGamma(alpha) + alpha*ln((beta+t)/beta) - (alpha+y)*t/(beta+t)
  EIG_i = E_y[ that ], with y ~ NegBin(alpha, beta/(beta+t)). Every term is elementary except E[y*digamma(alpha+y) - lnGamma(alpha+y)], which requires a truncated sum over k = 0..K with K = ceil(E[y] + 6*sd[y]) (typically K < 40). Cost ~40 log-gamma evaluations per candidate - cheap enough for a few thousand candidates, too slow for 160,000. RECOMMENDATION: use the exact variance-reduction form as the default and the EIG only for a shortlist.

MISSION-LEVEL ACQUISITION (what actually drives the robot). Pure information gain sends the robot to the most uncertain cell, which is not the same as the most useful cell. Use a weighted score:
  Score_i = w_find * E[y_new,i]  +  w_info * VOI_i^spatial / Vbar  -  w_cost * TravelTime(current_pose -> i) / Tbar  +  w_risk * Pop_i * P(M_i >= 1)
  where E[y_new,i] = alpha_i*t_i/beta_i (expected mines found = direct mission value),
        P(M_i >= 1) = 1 - (beta_i/(beta_i+1))^alpha_i (residual risk),
        Pop_i = population or civilian-use weight of cell i (embed at build time; roads, farmland, settlements),
        Vbar and Tbar are normalising constants (medians over candidate cells) so the weights are dimensionless.
  DEFAULTS: w_find = 1.0, w_info = 0.6, w_cost = 0.8, w_risk = 0.4.
  The robot picks argmax_i Score_i, drives there, sweeps, updates (Y_i, T_i), re-scores. Because the update is O(neighbourhood), the full re-score of a 400x400 grid is well under a frame time.

GREEDY GUARANTEE: the pure-information objective sum over a chosen set of VOI is monotone and submodular in the set of swept cells (each sweep raises beta, so later sweeps of overlapping cells yield strictly less - the classic diminishing-returns property, visible directly in VOI = V*t/(beta+t)). Hence greedy sequential selection achieves at least (1 - 1/e) ~= 63% of the optimal k-sweep information gain. The combined Score with travel cost loses this guarantee (it becomes an orienteering problem); note that honestly and use greedy anyway, or a 2-opt pass over the chosen cells to shorten the tour.
_source: VOI = V*t/(beta+t) derived above line by line from E[alpha+y] under the NegBin predictive; the Gamma-Gamma KL is the standard closed form; submodularity follows from the monotone decrease of V*t/(beta+t) in beta._

### [verified] (j) False positives: the posterior is an EXACT finite mixture of Gammas (still no MCMC)
DETECTOR MODEL. Three parameters:
  s   = sensitivity, P(detect | a mine lies in the swept footprint). Default 0.85 for a ground-penetrating-radar + magnetometer payload; make it a per-soil-type table if you have one.
  phi = false-alarm areal rate, alarms per km^2 of swept ground with no mine present. Default phi = 4000 /km^2 (i.e. 4 per 1000 m^2) for metal-detector-class sensors in scrap-littered post-conflict soil; this is highly site-dependent and must be estimated on-site (see calibration note below).
  f_i = phi * c_i * A_i = expected false alarms in cell i for this sweep.  t_i = c_i * s (as before).
The robot reports ALARMS a_i, not confirmed mines: a_i | lambda_i ~ Poisson( lambda_i * t_i  +  f_i ).

WHY NAIVE CONJUGACY BREAKS: the likelihood exp(-(lambda*t + f)) * (lambda*t + f)^a is not of the form lambda^k exp(-c*lambda), because of the additive f inside the power.

EXACT SOLUTION - BINOMIAL EXPANSION GIVES A FINITE GAMMA MIXTURE:
  (lambda*t + f)^a = sum_{k=0}^{a} C(a,k) * (lambda*t)^k * f^(a-k)
  => p(lambda | a) = sum_{k=0}^{a} pi_k * Gamma( lambda ; alpha + k , beta + t )
  with mixture weights (softmax of the log-weights, for numerical stability):
    log(w_k) = lnGamma(a+1) - lnGamma(k+1) - lnGamma(a-k+1) + k*ln(t) + (a-k)*ln(f) + lnGamma(alpha+k) - (alpha+k)*ln(beta+t)
    pi_k = exp(log w_k) / sum_{j=0}^{a} exp(log w_j)
  This is EXACT - not an approximation - and costs a+1 terms. Since a robot finds single-digit numbers of alarms per cell, this is trivially cheap. k is literally 'how many of the a alarms were real mines', and pi_k is its posterior.

MOMENTS OF THE MIXTURE:
  E[lambda | a]   = ( alpha + ybar ) / (beta + t) ,  where ybar = sum_k pi_k * k = the POSTERIOR EXPECTED NUMBER OF TRUE DETECTIONS
  E[lambda^2 | a] = sum_k pi_k * (alpha+k)*(alpha+k+1) / (beta+t)^2
  Var[lambda | a] = E[lambda^2|a] - E[lambda|a]^2

COLLAPSE BACK TO A SINGLE GAMMA (to keep the whole pipeline conjugate and the robot's state two numbers per cell): moment-match the mixture,
  M = E[lambda|a] , V = Var[lambda|a] ,  alpha' = M^2/V ,  beta' = M/V.
  NOTE beta' < beta + t in general, because the mixture carries EXTRA variance (uncertainty about which alarms were real) that a single Gamma at rate beta+t cannot express. Do not shortcut by using Gamma(alpha + ybar, beta + t) - it has the right mean but is over-confident.
  O(1) FALLBACK for a single-pass robot: ybar ~= a * (mhat*t) / (mhat*t + f), where mhat = alpha/beta is the current prior mean. This is the intuitive 'fraction of alarms attributable to real mines'. Use it only if a is large enough that the exact mixture is inconvenient (it never is).

KEY RESULT - A NULL SWEEP REMAINS EXACTLY CONJUGATE EVEN WITH FALSE POSITIVES:
  a = 0  =>  the mixture has one term, pi_0 = 1, and  lambda | a=0 ~ Gamma( alpha , beta + t )  exactly.
  Reason: p(a=0|lambda) = exp(-(lambda*t + f)) = exp(-f) * exp(-lambda*t), and exp(-f) is a constant in lambda that cancels in normalisation. So everything in item (c) holds unchanged under false positives. This is worth knowing because null sweeps are the overwhelming majority of robot observations.

CONFIRMED-DIG DATA. If an alarm is excavated and adjudicated, the observation becomes a CONFIRMED mine (or confirmed clutter) with no false-positive ambiguity, and you return to exact single-Gamma conjugacy with y = number of confirmed mines. Log both streams separately - the robot's (Y_i, T_i) pair should carry a flag for 'alarms' vs 'confirmed', and the confirmed stream is always preferred.

ESTIMATING phi IN THE FIELD. Run a known-clean calibration lane of swept area A_cal with a_cal alarms and zero confirmed mines: phi_hat = a_cal / A_cal, and put a Gamma(1, A_cal) posterior on phi if you want to propagate its uncertainty. Update phi per soil/terrain class; a stale phi biases ybar and therefore the whole posterior.

FALSE NEGATIVES are already fully handled by s < 1 in t = c*s - no separate machinery needed, which is a nice consequence of the thinning lemma.
_source: Binomial expansion of (lambda*t+f)^a term by term, integrated against the Gamma prior; each mixture weight is the exact normalising integral C(a,k)*t^k*f^(a-k)*Gamma(alpha+k)/(beta+t)^(alpha+k). The a=0 conjugacy result follows immediately._

### [likely] Deliverable B: the exact per-cell state the robot must log and exchange
MINIMAL SUFFICIENT STATE per cell i (this is the entire interface between the Bayesian model and the dimos robot code):
  { i, x_i, y_i_coord, A_i, alpha_i, beta_i, Y_i, T_i, R_i, last_sweep_ts }
  where (alpha_i, beta_i) is the CURRENT posterior (prior already folded in), Y_i = cumulative confirmed detections, T_i = cumulative effective exposure sum c*s, R_i = registered mine count. Everything the model needs is recoverable from (alpha_i, beta_i); (Y_i, T_i) are kept for audit and for re-running EB.
DERIVED FIELDS the planner reads (all O(1) from alpha, beta):
  mean_i        = alpha_i / beta_i
  sd_i          = sqrt(alpha_i) / beta_i
  p_any_i       = 1 - (beta_i/(beta_i+1))^alpha_i                        # P(at least one mine remains)
  expected_find = alpha_i * t / beta_i                                    # for a planned coverage t
  voi_i         = (alpha_i/beta_i^2) * t / (beta_i + t)                   # acquisition, item (i)
  p_null_i      = (beta_i/(beta_i+t))^alpha_i                             # P(sweep returns nothing)
UPDATE PROTOCOL (one function, runs in microseconds):
  on_sweep(i, c, s, alarms a, phi): t = c*s ; f = phi*c*A_i ;
    if a == 0:  alpha_i unchanged, beta_i += t          # exact, item (j)
    else:       compute the Gamma mixture of item (j), moment-match, set (alpha_i, beta_i) = (M^2/V, M/V)
    then spread evidence to neighbours with S (item d), then optionally re-run the two-pass EB (item e) at a lower rate, e.g. once per minute, not per sweep.
HEATMAP EXPORT for the planner: a dense float array of mean_i (or of p_any_i, which is the better field for risk-averse routing), plus the district-level Gamma(A_D, B_D) summaries from item (g). Ship the p_any grid as the cost surface and the voi grid as the reward surface; the planner's objective is the Score of item (i).
_source: reasoning, assembled from the closed forms derived in items (c), (e), (g), (h), (i), (j)._

## RECOMMENDATIONS
- Use intensity DENSITY rho_i (mines/km^2) as the state variable with lambda_i = rho_i * A_i. Parameterise the Gamma prior as alpha_i = alpha_floor + m_i/psi, beta_i = alpha_i/m_i with m_i = A_i*(a0 + kappa*rho^E_i), psi = 8, alpha_floor = 0.4. This is scale-invariant under cell merging; the skeleton's alpha_i = alpha_0 + kappa*E_i with fixed beta_0 is not (alpha_0 does not scale with A_i) and has no shape floor.
- Compute the prior ONCE at build time in Python/Node and bake the resulting per-cell (alpha_i, beta_i) into the HTML. The kernel convolution for Ukraine is ~3e7 operations. Never do it in the browser.
- For where_prec in {3,4,5,6}, spread w_e UNIFORMLY over the actual admin polygon rather than placing a Gaussian at the centroid. You already need polygons embedded at build time for the self-contained HTML, so use them. This is decisive for Ukraine: all 1194 where_prec=6 events sit at exactly (49.000000, 32.000000).
- Set kernel bandwidths by sigma_e = sqrt(sigma_geo(wp)^2 + sigma_phys^2 + sigma_dur(D)^2) with sigma_phys = 2.0 km and sigma_geo = {1:0.3, 2:12.5, 3:15, 4:45, 5:75, 6:220, 7:drop} km. Derive any country's values from sigma = sqrt(A_admin/(4*pi)).
- Always MASS-NORMALISE the kernel (integral = 1 over the plane, divided by the 3.5-sigma truncation constant 0.9978055). This is what stops an imprecise event from creating a hotspot and is more important than any weight term.
- Calibrate with the exact closed form a0 = pi*N*/A_C and kappa = (1-pi)*N*/W_C where W_C = sum_e w_e*q_e and pi = 0.15. Expose the mines-per-contaminated-km^2 constant delta as a visible slider in the HTML with its source cited, because it multiplies every output linearly.
- Implement the spatial coupling as column-stochastic evidence spreading: y~_i = sum_j S_ij*y_j and t~_i = sum_j S_ij*t_j with columns of S summing to 1. Verify sum_i y~_i == sum_j y_j in a unit test; getting row- vs column-normalisation backwards silently creates or destroys evidence.
- Apply the design-effect correction DEFF = min(n_D, max(1, 2*pi*L^2/A_cell)) to every district-level variance before reporting a credible interval. With L = 20 km on a 5 km grid this inflates the sd by ~10x. Omitting it produces absurdly tight intervals on district totals.
- Use the exact acquisition function VOI_i = (alpha_i/beta_i^2) * t/(beta_i + t) for robot targeting. It is O(1), requires no special functions, and needs no sampling. Reserve the exact KL-based EIG (which needs a ~40-term sum) for a shortlist.
- Handle false positives with the EXACT finite Gamma mixture of a+1 terms (computed in log space and softmaxed), then moment-match back to a single Gamma. Do not use Gamma(alpha + ybar, beta + t) directly, which has the right mean but is over-confident.
- Log only (alpha_i, beta_i, Y_i, T_i, R_i) per cell as the robot/model interface, and export p_any_i = 1 - (beta_i/(beta_i+1))^alpha_i as the planner's cost surface rather than the posterior mean. Risk-averse routing should key on P(at least one mine remains), not on the expected count.
- In the HTML, display the district headline as round(M_D) + R_D together with its 90% Wilson-Hilferty interval, and show P(cell contaminated) rather than the raw mean on the choropleth. Never render a point estimate alone on a demining map, and never paint a swept cell as clean: after a c=0.9, s=0.85 null sweep the residual risk drops only from ~15% to ~3%.

## PITFALLS
- Treating where_prec=6 as a point. All 1194 Ukraine country-level events sit on the single coordinate (49.000000, 32.000000), which is in Cherkasy oblast. A point-KDE puts a large spurious hotspot on a region that saw essentially no ground combat. These events also carry the highest mean fatalities of any precision class (best = 75.07 vs 7.15 for exact events), so they carry a lot of weight.
- Assuming where_prec=2 is an admin centroid. It is not: 16,820 where_prec=2 events occupy 1,718 distinct coordinates (compare where_prec=3 at 1,311 events on only 72 coordinates). where_prec=2 is a real point with ~25 km radius uncertainty, so sigma_geo = 12.5 km, not the raion scale.
- Using an unnormalised kernel. If K does not integrate to 1, an imprecise event contributes MORE total mass than a precise one, exactly inverting the intended behaviour.
- Row-normalising the evidence-spreading matrix S instead of column-normalising it. Mass conservation requires sum_i S_ij = 1 (over the destination index, for each source observation j). Row normalisation duplicates every detection once per neighbour.
- Claiming the evidence-spreading update is exact conjugate Bayes. It is exact only if lambda is constant over the support of the kernel. The mean bias is (ell*sigma_c^2/2)*Laplacian(lambda), it smears minefield edges by ~sigma_c, and it makes neighbouring posteriors correlated while the model treats them as independent.
- Summing independent per-cell variances to get a district variance. Because of the shared smeared observations and the genuine smoothness of the field, this under-states the variance by a factor of order 2*pi*L^2/A_cell (~100x on a 5 km grid with L = 20 km). Apply the DEFF correction.
- Forgetting that a 5 m grid needs sigma_c in metres, not kilometres. Reusing the national sigma_c = 3 km on the 400x400 robot grid smears every detection across the entire area of operations.
- Using the naive Gamma(alpha + y, beta + t) update when the robot reports ALARMS rather than confirmed mines. With a false-alarm rate phi > 0 the likelihood is Poisson(lambda*t + f), which is not conjugate; the correct posterior is a finite (a+1)-term Gamma mixture. Note the exception: a = 0 IS exactly conjugate even with false positives.
- Double-counting registered mines. Registered/confirmed mines (the deterministic dots) must be excluded from the modelled residual U_i, or the district headline adds them twice.
- Ignoring the alpha_floor. Without it a cell with m_i = 1e-6 gets alpha_i ~ 1e-6, a degenerate spike at zero with CV ~ 1000, and the Wilson-Hilferty quantile formula breaks down for alpha < 1.
- Letting f_rec decay to zero for old conflict. The 2014-2021 Donbas contact line contributes 3,523 Ukraine events and remains among the densest contamination in the country. The floor f_inf = 0.35 is essential.
- Setting f_fat(0) = 0. 254 Ukraine events have best = 0 but still represent shelling that deposits UXO. Use f_fat = (1 + best/b0)^0.5 which equals 1 at best = 0, and cap it at 20 so the best = 15,996 event does not dominate the national prior.
- Skipping the parent-posterior variance term when passing hyperparameters down the admin hierarchy. Using only the parent's mu_hat, not mu* plus Var[theta_parent | data], makes the shrinkage far too aggressive. Also, do not run the EB fit on a node with fewer than 4 children, and skip EB entirely on a cold start (mu_hat = 0/0 when no robot data exists).
- Assuming the Welch-Satterthwaite Gamma is symmetric in its error. Cauchy-Schwarz shows it always UNDER-states the true skewness when the rates beta_i differ, so the 95th percentile of the district total is systematically too low. Apply the Cornish-Fisher correction if the upper tail matters.
- Sourcing the calibration target A* from the ~139,000-174,000 km^2 Ukraine figure. That is a potentially-contaminated survey envelope, not confirmed hazardous area; using it will overstate N* by one to two orders of magnitude.