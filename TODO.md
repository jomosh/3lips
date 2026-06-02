# 3lips — Project TODO

> Generated: 2026-05-29 from full codebase analysis.  
> Organised into phases by priority: correctness → speed → accuracy → robustness → long-term.

---

## Phase 1 — Bug Fixes (Correctness) 🔴

These are confirmed defects that silently produce wrong results today.

### A1 — `"min"` vs `"minimum"` string mismatch
- **Files**: `event/algorithm/localisation/EllipseParametric.py`, `EllipsoidParametric.py`
- **Problem**: `event.py` creates instances with `method="min"` but `process()` checks `elif self.method == "minimum":`. All `min` variants silently fall through to the `else` branch and return an empty dict on every call. Both `ellipse-parametric-min` and `ellipsoid-parametric-min` are completely broken.
- **Fix**: Change the `elif` check in both files from `"minimum"` to `"min"`, OR change the constructor call in `event.py` to pass `"minimum"`.
- [ ] Fix string mismatch in `EllipseParametric.process()`
- [ ] Fix string mismatch in `EllipsoidParametric.process()`
- [ ] Add unit test: construct with `"min"` and verify non-empty output

### A2 — `ecef2lla` wraps longitude to `[0°, 360°)` instead of `[-180°, 180°)`
- **File**: `event/algorithm/geometry/Geometry.py`
- **Problem**: `lon = lon % (2 * math.pi)` maps all longitudes to `[0, 2π)`. The configured centre is London (`lon: -0.1278°`). Any target west of the prime meridian returns a longitude of ~359.87° instead of ~-0.13°. This breaks map display and accuracy comparison vs ADS-B truth for the entire western hemisphere.
- **Fix**: Change wrapping to `lon = (lon + math.pi) % (2 * math.pi) - math.pi` to give `(-π, π]`.
- [ ] Fix `ecef2lla` longitude wrapping
- [ ] Update `TestGeometry.py` to add a western-hemisphere test case (e.g. London)
- [ ] Verify map frontend correctly handles negative longitudes

### A3 — Ellipsoid cache (`self.ellipsoids`) is never populated
- **Files**: `EllipseParametric.py`, `EllipsoidParametric.py`
- **Problem**: Both classes maintain a `self.ellipsoids = []` list and attempt a lookup on each call, but the newly created `Ellipsoid` is never appended. The cache is dead code — every frame re-constructs every `Ellipsoid` from scratch including redundant coordinate transforms.
- **Fix**: After creating an `ellipsoid`, append it to `self.ellipsoids`.
- [ ] Fix cache in `EllipseParametric.process()`
- [ ] Fix cache in `EllipsoidParametric.process()`

### A4 — `AdsbAssociator` mutates shared radar detection data in-place
- **File**: `event/algorithm/associator/AdsbAssociator.py`
- **Problem**: `radar_detections['delay'][i] = delay` overwrites the shared `radar_dict` that is passed to all API items and all targets in the same epoch. If two API items reference the same radar, or if a radar has multiple targets, the second read gets already-extrapolated (possibly double-extrapolated) delays.
- **Fix**: Deep-copy `radar_detections` at the start of `process_1_radar()` before applying extrapolation. Or work with a local copy of the delay list.
- [ ] Add `import copy` and apply `copy.deepcopy` on the detections before mutation

### A5 — `EllipseParametric.sample()` uses hardcoded 100m altitude
- **File**: `event/algorithm/localisation/EllipseParametric.py`
- **Problem**: `Geometry.enu2ecef(r_1[i][0], r_1[i][1], 100, ...)` samples the 2D ellipse at 100m altitude. Display later forces altitude to 0. This introduces a small but systematic horizontal position error in the ECEF→distance comparisons.
- **Fix**: Change `100` to `0` (or to the midpoint altitude of the ellipse for improved accuracy).
- [ ] Fix hardcoded altitude in `EllipseParametric.sample()`

---

## Phase 2 — Performance (Speed) 🟠

### B1 — Vectorise intersection search with NumPy (highest priority)
- **Files**: `EllipseParametric.py`, `EllipsoidParametric.py`
- **Problem**: The intersection logic uses a Python `for` loop calling `math.sqrt` millions of times. For `EllipsoidParametric` with `nSamples=60`: 60×30 = 1,800 points per ellipsoid → 1,800 × 1,800 × K distance computations per target. This is the dominant CPU cost.
- **Fix**: Use NumPy broadcasting to compute the full distance matrix at once:
  ```python
  pts1 = np.array(samples1)                              # (N, 3)
  pts2 = np.array(samples2)                              # (M, 3)
  dists = np.linalg.norm(pts1[:, None] - pts2[None, :], axis=2)  # (N, M)
  valid_mask = np.any(dists < threshold, axis=1)         # (N,)
  ```
- Expected speedup: **50–200×** for ellipsoid case.
- [ ] Vectorise `EllipseParametric` intersection
- [ ] Vectorise `EllipsoidParametric` intersection
- [ ] Add processing time benchmark before/after

### B2 — Parallelise HTTP fetches with `asyncio` / `aiohttp`
- **File**: `event/event.py`
- **Problem**: Detection and config data are fetched from each radar sequentially with `requests.get(..., timeout=1)`. For 3 radars: up to 6 sequential HTTP calls = up to 6 seconds of blocking before processing starts.
- **Fix**: Replace with `aiohttp` + `asyncio.gather()` for concurrent fetches. All radar URLs fetched in a single `await` call.
- [ ] Add `aiohttp` to `event/requirements.txt`
- [ ] Rewrite radar fetch section to use `asyncio.gather`

### B3 — Cache radar configs; only poll detections each epoch
- **File**: `event/event.py`
- **Problem**: `/api/config` is fetched from each radar node every second. Radar TX/RX positions and carrier frequency never change at runtime.
- **Fix**: Cache config on first successful fetch per radar. Provide a background refresh (e.g. every 60s) to handle radar restarts.
- [ ] Implement config cache dict keyed by radar URL
- [ ] Add background config refresh timer

### B4 — Arc-length parametrisation for ellipse/ellipsoid sampling
- **Files**: `EllipseParametric.py`, `EllipsoidParametric.py`
- **Problem**: `np.linspace(0, 2π, n)` gives uniform angle spacing, which is non-uniform in physical distance. For elongated ellipses (large bistatic range, small TX-RX baseline — typical of passive radar), the minor-axis region (where intersections occur) is sparsely sampled.
- **Fix**: Compute cumulative arc length as a function of angle, then use `np.interp` to find angles at uniform arc-length positions.
- **Note**: Also mentioned in README Future Work.
- [ ] Implement arc-length parametrisation for 2D ellipse
- [ ] Implement arc-length parametrisation for 3D ellipsoid
- [ ] Adaptive `nSamples` proportional to ellipse perimeter (also in README)

### B5 — Eliminate double coordinate round-trip in `EllipsoidParametric.sample()`
- **File**: `EllipsoidParametric.py`
- **Problem**: Each sample point is converted: ENU → ECEF → LLA (to check `alt > 0`) → ECEF (to store). This is two full coordinate transforms per sample just to filter below-ground points.
- **Fix**: Check `r_1[i][2] + midpoint_ecef_z > 0` directly in ENU space (the `u` axis in ENU is "up"), or compute altitude without a full inverse transform.
- [ ] Refactor altitude check in `EllipsoidParametric.sample()`

### B6 — Use `scipy.spatial.cKDTree` for nearest-neighbour intersection
- **Files**: `EllipseParametric.py`, `EllipsoidParametric.py`
- **Problem**: For K ellipsoids, the current approach for the `mean` method is O(N × M × K). A KD-tree built on each secondary ellipsoid reduces the per-query cost from O(M) to O(log M).
- **Fix**: Build a `cKDTree` on `samples2` and query with `tree.query_ball_point(pts1, threshold)`.
- [ ] Add `scipy` to `event/requirements.txt`
- [ ] Implement KD-tree intersection in both parametric classes

### B7 — Parallelise per-target processing
- **File**: `event/event.py`
- **Problem**: The main processing loop iterates over `api_event` sequentially. Multiple simultaneous API clients all block each other.
- **Fix**: Use `concurrent.futures.ThreadPoolExecutor` or `asyncio.gather` per API item.
- [ ] Evaluate thread-safety of shared state before parallelising
- [ ] Implement per-item parallel processing

---

## Phase 3 — Accuracy (Algorithm Upgrades) 🟡

### C1 — Implement TDOA Least-Squares localisation (new algorithm)
- **Problem**: The parametric sampling approach is limited by sample density and the fixed threshold heuristic. The true problem is a non-linear least-squares problem:
  $$\min_{x} \sum_{i=1}^{N} \left( R_i^{\text{meas}} - (|x - T_i| + |x - R_i|) \right)^2$$
  This can be solved with `scipy.optimize.least_squares` (Levenberg-Marquardt) in <1ms per target, using all ellipsoids simultaneously.
- **Benefits**: No sampling noise, uses all radars at once, gives covariance estimate from Jacobian, works with 2+ radars.
- **Topology support**: Unlike `SphericalIntersection`, the cost function uses each pair's individual $(T_i, R_i)$ positions — it naturally handles all deployment topologies (A, B, and C) without any shared-node restriction. This makes it the recommended replacement for `SphericalIntersection` in Topology C (fully multistatic) deployments.
- [ ] Create `event/algorithm/localisation/TDOALeastSquares.py`
- [ ] Implement cost function and Jacobian for bistatic range model
- [ ] Use `scipy.optimize.least_squares` with LM method
- [ ] Add warm-start from previous frame position
- [ ] Wire into `event.py` and `api.py`
- [ ] Add unit tests for each topology (A, B, C) with known synthetic geometry

### C2 — Implement Extended Kalman Filter (EKF) track management
- **Problem**: Each epoch produces a fresh, noisy position fix with no temporal continuity. Aircraft tracks jump epoch to epoch. An EKF with a constant-velocity kinematic model would smooth noise and provide velocity estimates.
- **State**: `[x, y, z, ẋ, ẏ, ż]` in ECEF
- **Measurement**: bistatic range per radar (non-linear)
- **Benefits**: Reduced position jitter, velocity readout, track continuity through short gaps.
- [ ] Create `event/algorithm/tracker/EKFTracker.py`
- [ ] Implement predict (constant-velocity) and update (bistatic range) steps
- [ ] Implement track initiation (2-frame confirmation) and deletion
- [ ] Thread-safe track store per API config item
- [ ] Add Doppler as secondary measurement (see C3)
- [ ] Wire into event loop
- [ ] Add simulation-based unit tests

### C3 — Use Doppler measurements in localisation
- **Problem**: Bistatic Doppler is captured and associated but then discarded. Doppler constrains the component of velocity along the bistatic bisector, providing an additional measurement that improves both position (through temporal integration in EKF) and velocity accuracy.
- [ ] Add bistatic Doppler model to EKF measurement equation
- [ ] Add Doppler residual to TDOA Least-Squares cost function (optional, weighted)
- [ ] Expose estimated velocity in API output

### C4 — Compute and expose GDOP
- **Problem**: No quality metric is provided. The Geometric Dilution of Precision (GDOP) quantifies how ellipsoid crossing geometry amplifies range measurement errors into position error. Users cannot currently judge when an estimate is reliable.
- **Formula**: GDOP = sqrt(trace((J^T J)^{-1})) where J is the bistatic range Jacobian
- [ ] Create `event/algorithm/quality/GDOP.py`
- [ ] Compute GDOP from radar geometry and estimated position
- [ ] Add `gdop` field to API output JSON
- [ ] Display GDOP on map (e.g. colour-coded confidence ellipse)

### C5 — Weighted measurements (SNR-proportional)
- **Problem**: All radar measurements are treated equally. A radar with a high-SNR detection has lower range uncertainty than a marginal detection near the noise floor.
- [ ] Expose SNR or detection confidence from blah2 API
- [ ] Weight residuals in TDOA Least-Squares by `1/sigma_i`
- [ ] Weight innovation covariance in EKF by measurement quality

### C6 — Fix `SphericalIntersection` reference-node selection
- **File**: `event/algorithm/localisation/SphericalIntersection.py` line 25
- **Problem**: `self.type = "rx"` is hardcoded. The SX algorithm requires a shared node (either all radars share one TX, or all share one RX), and `type` controls which node varies across radars. The hardcoded `"rx"` means the algorithm always treats the **transmitter as the shared/constant node** and the receivers as varying — i.e. it only works for a single-transmitter, multi-receiver PCL deployment (the typical FM passive radar case). A deployment with a common receiver and multiple different transmitters (`type = "tx"`) is silently broken: the matrix S is built from TX ECEF positions instead of RX positions, producing completely wrong target locations with no error or warning. Additionally, the reference node is `next(iter(radar_data))` which relies on dict ordering — if the first radar in the dict is not the shared-node host, the ENU origin is wrong.
- [ ] Make `type` a constructor parameter loaded from config.yml (`localisation.spherical.shared_node: tx | rx`)
- [ ] Validate that the configured shared-node position is the same (within tolerance) across all radars in the set before computing
- [ ] Log a clear warning if shared-node validation fails
- [ ] Document geometric requirement and `type` semantics in the class docstring

### C7 — Ghost-target disambiguation for `SphericalIntersection`
- **File**: `SphericalIntersection.py` lines ~105–115
- **Problem**: The quadratic produces two candidate ENU positions `x_t[0]` and `x_t[1]`. The code selects whichever has the larger `x_t[i][2]` (the ENU "up" component). Two specific failure modes:
  1. **Neither solution is above ground**: in poor geometry or noisy measurements, both solutions can have `up < 0`. The code still returns the "least underground" one as a valid fix, producing a target underground with no warning.
  2. **Low-altitude targets**: for a target at 200m altitude (helicopter, drone), both solutions may have very similar `up` values and the wrong one could be selected due to measurement noise.
- **Note**: The comparison is correctly done on the ENU array `x_t` (before LLA conversion), not the post-conversion `x_t_list`, so the index is consistent. The logic itself is sound — just missing the positivity guard.
- [ ] Add `up > 0` guard: skip the target entirely if both solutions are underground (return no point for this target rather than a wrong underground position)
- [ ] Add kinematic plausibility check using Doppler sign: the selected solution's geometry should produce the same Doppler sign as observed
- [ ] Consider selecting solution nearest to prior EKF track estimate (requires C2)

---

## Phase 4 — Robustness 🟢

### D1 — Condition number guard in `SphericalIntersection`
- **File**: `SphericalIntersection.py` line ~87
- **Problem**: `S_star = np.linalg.inv(S.T @ S) @ S.T`. Two distinct failure modes:
  1. **Fewer than 3 detections / degenerate geometry**: ~~if `assoc_detections[target]` has only 1 or 2 entries, S is (1×3) or (2×3). `S.T @ S` is 3×3 but rank-deficient, and `np.linalg.inv` raises `numpy.linalg.LinAlgError: Singular matrix` — an **unhandled exception that propagates up and crashes the event loop processing for that epoch**~~ **Fixed**: a `matrix_rank(S) < 3: continue` guard now skips any target whose detection matrix is rank-deficient (covers < 3 detections and co-planar/co-linear nodes).
  2. **Nearly co-linear receivers**: if 3+ receivers exist but lie along nearly the same line of sight from the target, S is full-rank but ill-conditioned. `inv` completes but the result is numerically garbage (position estimate far from truth). No warning is given.
- **Fix**: Replace `np.linalg.inv(S.T @ S) @ S.T` with `np.linalg.lstsq(S, ...)` directly, which handles both cases gracefully using the Moore-Penrose pseudoinverse (LAPACK DGELSD). Also add a minimum detection count guard at the top of the target loop.
- [ ] Replace `np.linalg.inv(S.T @ S) @ S.T` with `np.linalg.lstsq(S, ..., rcond=None)` for all three solve operations
- [x] Add rank guard — implemented as `if np.linalg.matrix_rank(S) < 3: continue`, which is more general than a length check alone (also catches co-planar nodes with ≥3 detections).
- [ ] Add `np.linalg.cond(S)` check: log a warning when condition number > 100 (poorly conditioned geometry)
- [ ] Add unit test: 1-detection input → no crash, empty output for that target
- [ ] Add unit test: 2-detection input → no crash, empty output (not 3, so guard triggers)

### D2 — Adaptive sample density
- **Files**: `EllipseParametric.py`, `EllipsoidParametric.py`
- **Problem**: Fixed `nSamples` regardless of ellipse size. A very large ellipse (long-range detection) needs more samples than a small one to achieve the same spatial resolution.
- **Note**: Mentioned in README Future Work.
- [ ] Compute ellipse perimeter / ellipsoid surface area
- [ ] Scale `nSamples` proportional to size, subject to a min/max bound

### D3 — Validate detection timestamp coherence
- **File**: `event/event.py`
- **Problem**: Detections from different radars are associated by ADS-B hex code but their timestamps are not verified to be close in time. A stale detection from one radar could be combined with fresh detections from others.
- [ ] Add timestamp difference check: reject associations where `|t1 - t2| > max_time_delta`
- [ ] Expose `max_time_delta` in config.yml

### D4 — Per-target processing timeout
- **File**: `event/event.py`
- **Problem**: A single slow or complex target (e.g. with many associated radars) can delay all other targets.
- [ ] Wrap per-target processing in a timeout context
- [ ] Log slow targets

### D5 — Extrapolation-only Doppler association TODO
- **File**: `AdsbAssociator.py`
- **Problem**: The code includes `# TODO extrapolate Doppler too` — Doppler is currently not extrapolated to the current timestamp, only delay is. This degrades association quality for fast-moving targets observed with a time gap.
- [ ] Implement Doppler extrapolation using radial acceleration model
- [ ] Make extrapolation window configurable

### D8 — UI validation: warn when `SphericalIntersection` is selected with incompatible radar geometry
- **Files**: `api/api.py`, `api/map/main.js` (or `api/public/js/index.js`)
- **Problem**: `SphericalIntersection` will silently return wrong positions if the selected radar nodes do not share the same transmitter (or same receiver). Currently there is no check at the API layer or in the UI — a user can freely select `spherical-intersection` with radars on different FM transmitters and receive plausible-looking but completely wrong target positions.
- **Two-layer fix**:
  1. **API-side**: When `localisation=spherical-intersection` is submitted, inspect the `config.location.tx` (or `rx`) of each radar in `radar_data`. If any two radars have TX positions more than `shared_node_tolerance` metres apart, add a `"warnings": ["SphericalIntersection requires a shared TX; selected radars have different TX locations"]` field to the API response.
  2. **UI-side**: Display the warning prominently (e.g. yellow banner below the Submit button) before the user can interpret the map results.
- **Tolerance**: TX positions ≤ 100m apart → same site. TX positions > 100m apart → different transmitters. Make configurable.
- [ ] Add shared-node check in `api.py` when `localisation == "spherical-intersection"`
- [ ] Add `warnings` array field to the API response JSON schema
- [ ] Display `warnings` in the web UI (yellow alert banner)
- [ ] Add unit test: API with two radars having different TX positions returns a warning
- [ ] Document the shared-node requirement more prominently in USER_GUIDE.md algorithm table

### D9 — Verify and test Topology B and C deployments end-to-end
- **Context**: The USER_GUIDE.md now documents four deployment topologies (A: shared TX; B: shared RX; C: fully multistatic; D: same TX/RX, different fc). Topology B and C have never been integration-tested. Topology A is the only configuration verified against real data.
- **Topology B** (same RX, different TX) risk: The `EllipseParametric`/`EllipsoidParametric` algorithms are geometry-agnostic and *should* work, but the ellipsoid orientation and midpoint calculation in `Ellipsoid.py` has only been exercised with the TX-to-RX baseline pointing in the shared-TX direction. Need to confirm yaw/pitch computation is correct when the shared node is RX.
- **Topology C** (different TX, different RX) risk: Same as above. Additionally, `SphericalIntersection` must not be offered as an option in the UI when Topology C is detected (see D8).
- **Topology D** (same TX, same RX, different fc) risk: The algorithm will appear to run and return points, but those points are meaningless (see USER_GUIDE.md). The UI should ideally warn the user.
- [ ] Write a synthetic unit test for Topology B: 3 blah2 configs with same RX, 3 different TX positions → verify EllipseParametric returns correct position
- [ ] Write a synthetic unit test for Topology C: 3 fully independent TX-RX pairs → verify EllipseParametric returns correct position
- [ ] Write a synthetic test for Topology D: 2 pairs with identical TX/RX coords → verify output is empty or carries a warning (should produce no intersection)
- [ ] Confirm `Ellipsoid.py` yaw/pitch computation is correct for all baseline orientations (add assertion-based test)
- [ ] Add a UI warning when all selected radars have identical TX **and** identical RX coordinates (Topology D detected)

### D6 — Hard-coded association window
- **File**: `AdsbAssociator.py`
- **Problem**: `distance_window = 10` is hard-coded with no units documentation. This is in normalised delay-Doppler distance and is not configurable.
- [ ] Move `distance_window` to `config.yml` under `associate.adsb`
- [ ] Document units in config

### D7 — Non-ADS-B association algorithm (see Phase F for full plan)
- **File**: `event/algorithm/associator/`
- **Problem**: The only associator requires external ADS-B truth via adsb2dd. Targets not broadcasting ADS-B (military aircraft, general aviation without transponder, drones) are completely invisible to the system.
- **Key finding**: The ADS-B dependency is **entirely in the association layer**. Every localisation algorithm (`EllipseParametric`, `EllipsoidParametric`, `SphericalIntersection`) consumes `{id: [{radar, delay, doppler}]}` and is agnostic to how that dict was populated. A blind associator producing the same schema requires **zero changes** to any localisation code.
- **Note**: Mentioned in README Future Work. See Phase F below for the full research-backed implementation plan.
- [ ] Implement Phase F1 `GeometricAssociator` (see Phase F)
- [ ] Add `associate.geometric` config block
- [ ] Wire into `event.py` and `api.py` alongside existing `adsb-associator`

---

## Phase 5 — Long-Term / Feature Roadmap 🔵

### E1 — Detection vs Track data selection per radar
- **Note**: Mentioned in README Future Work.
- [ ] Add `data_mode: detection | track` per radar in config.yml
- [ ] Support consuming track-level (fused) data from blah2 instead of raw detections

### E2 — Long-term metrics and visualisation
- **Note**: Mentioned in README Future Work.
- [ ] Track 2D localisation error vs ADS-B truth per aircraft
- [ ] Compute RMSE, CEP50, CEP90 over a sliding window
- [ ] Store metrics to a time-series database (e.g. InfluxDB)
- [ ] Add Grafana dashboard for live accuracy monitoring
- [ ] Plot number of aircraft tracked vs time

### E3 — HTTPS support throughout
- [ ] Add TLS termination at API layer (nginx reverse proxy or Gunicorn + cert)
- [ ] Support HTTPS for all outbound radar and ADS-B requests (config flags already exist)

### E4 — Multi-hypothesis / multi-target tracking
- [ ] Implement Joint Probabilistic Data Association (JPDA) or MHT
- [ ] Handle crossing tracks without ID swap

### E5 — GPU acceleration
- [ ] Profile which operations would benefit from CuPy (drop-in NumPy replacement on CUDA)
- [ ] Implement ellipsoid sampling on GPU for high-density scenarios

### E6 — Replay / offline analysis mode
- [ ] Load saved `.ndjson` files and re-process with different algorithms
- [ ] Compare algorithm accuracy head-to-head on the same recorded data
- [ ] Export accuracy metrics to CSV/PDF report

### E7 — Web UI improvements
- [ ] Add algorithm accuracy overlay on map (GDOP ellipse per target)
- [ ] Show per-radar detection count and last-seen time
- [ ] Add target history trail (last N positions)
- [ ] Export current state to GeoJSON

### E8 — CI/CD pipeline
- [ ] Add GitHub Actions workflow for automated test run on push
- [ ] Add lint (flake8 / ruff) step
- [ ] Add Docker build + push to registry on tag
- [ ] Add accuracy regression test with known synthetic scenario

### E9 — Configuration schema validation
- [ ] Add `jsonschema` or `pydantic` validation for `config.yml` at startup
- [ ] Produce clear error messages for missing or malformed config keys

### E10 — Documentation
- [ ] Add per-algorithm accuracy/performance comparison table to README
- [ ] Document blah2 integration requirements (config fields needed from radar)
- [ ] Add architecture diagram (sequence diagram: API → event → radar → localisation)
- [ ] Publish API reference (OpenAPI/Swagger spec)

---

---

## Phase F — Blind (ADS-B-Free) Association 🟣

> **Research context** (2025-06-01): Full algorithm survey conducted. The findings below are self-contained so this phase can be implemented from a fresh context without re-researching.
> **Prerequisite for cross-reference features:** Phase F1 (GeometricAssociator) must be implemented before F0 can work.

---

### F0 — Non-Cooperative Target Detection (ADS-B Cross-Reference)

> **Purpose:** Identify targets that are detected by the radar system but are NOT broadcasting ADS-B (military aircraft, general aviation without transponder, drones, etc.).
> **Architecture:** Run both AdsbAssociator and GeometricAssociator in parallel within the same epoch, then cross-reference their outputs. Targets appearing only in the blind associator output are flagged as non-cooperative.
>
> **This adds to the system — it does not replace anything.**

**Context — Why This Is Useful:**

- Military aircraft routinely fly with ADS-B off or with inaccurate position data
- Many general aviation aircraft have no ADS-B Out equipment
- Drones and UAS platforms typically do not broadcast ADS-B
- With F1 alone, you get blind targets but cannot distinguish cooperative vs non-cooperative
- With F0, you can separately visualise friendly/known aircraft vs unknown/uncooperative tracks

**Architecture (per epoch):**

```
                    ┌──────────────────────────────┐
                    │  AdsbAssociator (existing)    ├──▶ dict[hex] = {radar, delay, doppler}
                    └──────────────────────────────┘
Radar detections ──┤
                    ┌──────────────────────────────┐
                    │  GeometricAssociator (F1)     ├──▶ dict[synth_id] = {radar, delay, doppler}
                    └──────────────────────────────┘
                             │
                             ▼
                    ┌──────────────────────────────┐
                    │  Cross-Reference Stage (F0)   │
                    │  - Localise both sets          │
                    │  - Compare ECEF positions      │
                    │  - Classify each blind target  │
                    └──────────────────────────────┘
                             │
                    ┌────────┴────────┐
                    ▼                 ▼
             Cooperative        Non-Cooperative
             (matches ADS-B)   (no ADS-B match)
```

**Algorithm (step by step):**

1. **Run both associators.** For the current epoch, execute `AdsbAssociator.process()` as today. In the same epoch, also execute `GeometricAssociator.process()` on the same radar data.

2. **Localise both sets.** Run the selected localisation algorithm on both associator outputs independently. This produces two position estimate dicts:
   - `localised_adsb`: `{hex: {"points": [[lat, lon, alt]]}}`
   - `localised_blind`: `{synth_id: {"points": [[lat, lon, alt]]}}`

3. **Cross-reference.** For each target in `localised_blind`, compute the ECEF distance to every target in `localised_adsb`. If any ADS-B target is within `noncooperative.match_distance` (configurable, default 1000m), classify the blind target as **cooperative** — it's the same aircraft seen by both algorithms. Otherwise, classify it as **non-cooperative**.

4. **Merge output.** Produce a unified output dict that separates the two classes:
   ```python
   {
     "cooperative": {hex: {points, truth}},        # existing schema
     "noncooperative": {synth_id: {points}}         # new — unknown targets
   }
   ```

5. **(Optional) Track persistence (requires F3).** A non-cooperative target may appear in multiple epochs. Use a track ID mapping (`synth_id` → persistent track number) to maintain identity across frames. Without this, the synth_id will change each epoch as detection tuples drift.

**Configuration additions to `config/config.yml`:**

```yaml
noncooperative:
  enabled: false                  # toggle non-cooperative detection on/off
  match_distance: 1000           # metres — max distance to match blind↔ADS-B
  min_radars: 3                  # min radars for a non-cooperative declaration
  localisation: "ellipse-parametric-min"  # algorithm for blind-localised targets
```

**API schema extension:**

```json
{
  "hash": "...",
  "detections_localised": { "hex": {"points": [...]} },
  "detections_noncooperative": { "synth_id": {"points": [...]} },
  "cooperative_count": 5,
  "noncooperative_count": 2
}
```

Both fields co-exist. `detections_localised` continues to hold ADS-B-associated results (backward compatible). `detections_noncooperative` is added when `noncooperative.enabled: true`.

**UI changes (`api/map/main.js`):**

- Non-cooperative targets rendered with a distinct icon/colour (e.g. red triangle vs blue aircraft)
- Toggle layer visibility: "ADS-B targets" / "Non-cooperative targets" / "Both"
- Hover/click on non-cooperative target shows synthetic ID, detection count, age if tracked

**Implementation plan:**

1. [ ] Add `noncooperative` config block to `config/config.yml`
2. [ ] In `event/event.py`: after `localised_dets = localisation.process(...)`, add a second block that runs `GeometricAssociator` + localisation if `noncooperative.enabled`
3. [ ] Implement cross-reference logic: for each blind target, find nearest ADS-B target in ECEF; if distance > `match_distance`, flag as non-cooperative
4. [ ] Extend API output schema: add `detections_noncooperative` and `cooperative_count` / `noncooperative_count`
5. [ ] Add `noncooperative` field to the ZMQ message sent from `event` to `api`
6. [ ] Update `api/api.py` to pass `detections_noncooperative` through to frontend
7. [ ] Update `api/map/main.js` to render non-cooperative targets with distinct styling
8. [ ] Add unit test: synthetic 3-radar epoch with 1 ADS-B target + 1 non-cooperative target → both detected and correctly classified
9. [ ] Add unit test: `noncooperative.enabled: false` → no change to existing output
10. [ ] Add unit test: `match_distance: 1` (very tight) → no false-positive classification drift

**Known limitations:**
- Gating is per epoch — a single epoch with poor geometry could misclassify a target. Track-level gating (F3 JIPDA) would resolve this.
- If both the ADS-B and blind target are the **same** physical aircraft but observed with different detections (different CPIs), they could both be classified as non-cooperative + cooperative separately (true positive for non-cooperative, but double-counting the aircraft). Mitigation: use a temporal proximity filter (within same epoch window) and compare not just position but also Doppler sign.
- The `GeometricAssociator` must be instantiated even when `noncooperative.enabled` is false for the primary path (ADS-B only). When `noncooperative.enabled: true`, it adds a second localisation call on the blind output.
- If the `GeometricAssociator` produces no targets (e.g. due to `max_detections` guard or high false-alarm rate), no non-cooperative targets will be reported that epoch. This is correct behaviour.

---


### Background — Why ADS-B Is Currently Required

`AdsbAssociator` uses an external adsb2dd service to compute the expected bistatic `(delay, Doppler)` for every ADS-B aircraft, then matches those predictions against each radar's detection list. This solves the **data association problem**: given M detections from radar 1 and M detections from radar 2, which pairs belong to the same physical target?

The ADS-B-free solution answers this purely from radar geometry. It does **not** affect localisation accuracy — the CRLB floor is set by radar bandwidth and SNR, not by the association method. ADS-B only provides a shortcut to the association answer; the geometry provides the same answer without external truth.

### Key Architectural Invariant

Every blind associator MUST produce this exact output schema (identical to `AdsbAssociator.process()`) — no localisation code changes are needed:

```python
{
  "a3f9c1": [    # synthetic ID = e.g. hash of (delay1, delay2, delay3) tuple
    {"radar": "radar1.example.com", "delay": 0.000234, "doppler": 12.5},
    {"radar": "radar2.example.com", "delay": 0.000198, "doppler": 11.8},
    {"radar": "radar3.example.com", "delay": 0.000271, "doppler": 13.1},
  ]
}
```

The only file changed at the call site is `event/event.py` (one `elif` branch) and `api/api.py` (one list entry).

### The Ghost Problem and Why N≥3 Radars Suffices

With N=2 radars, every cross-radar detection pair (one from each radar) produces one intersection region. For M detections per radar, M² pairs exist, but only M_targets produce a *consistent* intersection. The remaining (M²−M_targets) pairs are ghosts — they produce intersections at wrong positions. Ghost suppression at N=2 is poor without ADS-B gating.

At N=3, a ghost requires three independent ellipses to mutually intersect within the threshold. For well-separated radars at 50 km range with a 500 m threshold:

$$P(\text{ghost survives}) \approx \left(\frac{500\,\text{m}}{\text{ellipse arc length}}\right)^{N-1}$$

For a typical 200 km arc at N=3: $P \approx (500/200000)^2 \approx 6 \times 10^{-6}$ per candidate. This makes enumeration practical — false tracks are extremely rare with 3+ well-separated radars.

### CRLB Note on Accuracy

No association method changes the fundamental accuracy floor. The Cramér-Rao Lower Bound is set by radar bandwidth and SNR:

$$\sigma_r \geq \frac{c}{2\beta\sqrt{2 \cdot \text{SNR}}}$$

| Waveform | Bandwidth | σ_r at 0 dB SNR | σ_r at 20 dB SNR |
|---|---|---|---|
| FM broadcast | ~100 kHz | ~1500 m | ~150 m |
| DAB | ~1.5 MHz | ~100 m | ~10 m |
| DVB-T | ~7.6 MHz | ~20 m | ~2 m |

ADS-B vs blind approaches differ **only in false-association rate**, not in true-target accuracy once correctly associated.

### Approach Survey

| ID | Name | ADS-B? | Min radars | Ghost risk | Cost/epoch | Impl effort | Phase |
|---|---|:---:|:---:|---|---|:---:|:---:|
| **F-A** | Geometric enumeration | No | 2 (≥3 recommended) | Low at N≥3 | O(M^N × S) | Low | **F1** |
| **F-B** | Doppler consistency filter | No | 2 (secondary) | 5–50× reduction | O(candidates) | Low | **F1** |
| **F-C** | TDOA pair pre-filter | No (shared TX) | 2 | N/A — pruning stage | O(M²) | Medium | **F2** |
| **F-D** | DBSCAN in ECEF space | No | 2 | eps-sensitive | O(n log n) KD-tree | Low | **F2** |
| **F-E** | JPDA / JIPDA tracking | No | 1 (with prior) | Low (probabilistic) | O(K²–K³) pruned | High | F3 |
| **F-F** | PHD particle filter | No | 1 | Optimal (CRLB) | O(P × N_radars) | Very high | F4 |

**Key papers for implementer:**
- Malanowski & Kulpa, "Two methods for target localization in multistatic passive radar," *IEEE Trans. AES* 48(1), 2012 — enumeration + ghost analysis for PCL
- Musicki & Evans, "Joint Integrated Probabilistic Data Association – JIPDA," *IEEE Trans. AES* 40(3), 2004 — recommended track management
- Ester et al., "A density-based algorithm for discovering clusters," *KDD* 1996 — DBSCAN
- Vo & Ma, "The Gaussian Mixture PHD Filter," *IEEE Trans. Signal Process.* 54(11), 2006 — PHD filter
- Colone et al., "Passive Coherent Location," *IEEE AESS Magazine*, 2012 — PCL system overview

### Enumeration Scaling (M^N Candidates)

| M per radar | N=2 | N=3 | N=4 | Comment |
|---|---|---|---|---|
| 5 | 25 | 125 | 625 | Trivial — no pre-filter needed |
| 10 | 100 | 1,000 | 10,000 | Fast with vectorised NumPy |
| 20 | 400 | 8,000 | 80,000 | ~20 ms with NumPy |
| 50 | 2,500 | 125,000 | 6.25M | Use TDOA pre-filter (F2) |

---

### F1 — `GeometricAssociator`: Enumeration + Doppler Filter
- **Files to create**: `event/algorithm/associator/GeometricAssociator.py`
- **Files to modify**: `event/event.py` (one `elif` branch), `api/api.py` (one list entry), `config/config.yml` (new `associate.geometric` block)
- **Removes**: hard dependency on `adsb2dd` service for basic operation

**Algorithm (step by step):**

1. **Build detection lists.** For each radar in `radar_data`, extract `detections["delay"]` and `detections["doppler"]` as parallel lists. Skip radars with `None` detection data.

2. **Enumerate N-tuples.** Use `itertools.product` over all detection lists. Each tuple has one `(delay_i, doppler_i)` per radar.
   ```python
   import itertools, hashlib
   per_radar = [
       list(zip(det["delay"], det["doppler"])) for det in detection_lists
   ]
   candidates = list(itertools.product(*per_radar))
   ```

3. **Geometric intersection test.** For each candidate tuple, compute the ECEF sample points on each bistatic ellipse (reuse `Geometry` + `Ellipsoid` infrastructure already in the codebase). Check that all N sets have mutual proximity within `threshold` metres using vectorised NumPy distance:
   ```python
   # pts[i]: (S, 3) array of ECEF points for radar i
   dists = [
       np.linalg.norm(pts[0][:, None] - pts[i][None, :], axis=2).min(axis=1)
       for i in range(1, N)
   ]
   passes = np.all(np.stack(dists) < threshold, axis=0).any()
   ```

4. **Doppler consistency filter.** For candidates passing step 3, verify sign-consistency and optional ratio-consistency of Doppler values across radars. For a target moving toward the transmitter, all receivers should observe the same sign of Doppler shift (positive or negative depending on geometry). Full check: compute unit vectors at the estimated intersection position and verify:
   $$\left|\frac{f_{d,i}}{f_{d,j}} - \frac{(\hat{\mathbf{u}}_{TX \to r} + \hat{\mathbf{u}}_{r \to RX_i}) \cdot \hat{\mathbf{v}}}{(\hat{\mathbf{u}}_{TX \to r} + \hat{\mathbf{u}}_{r \to RX_j}) \cdot \hat{\mathbf{v}}}\right| < \epsilon_{doppler}$$
   Use `doppler_tolerance` from config (default: 5 Hz ≈ 2× Doppler resolution for 1s CPI).

5. **Deduplicate.** Multiple surviving N-tuples may correspond to the same target (repeated near-identical detections). Cluster by mean ECEF intersection point with the same `threshold`; keep the candidate with the lowest total ellipse intersection distance.

6. **Build output dict.** Key each surviving candidate by `hashlib.sha256(str(delays_tuple).encode()).hexdigest()[:8]`. Return in the `{id: [{radar, delay, doppler}]}` schema.

**Config additions to `config/config.yml`:**
```yaml
associate:
  geometric:
    threshold: 500        # metres — spatial proximity for intersection test
    nSamples: 50          # ellipse samples per detection (lower than localisation for speed)
    doppler_tolerance: 5  # Hz — Doppler consistency filter tolerance
    max_detections: 20    # per radar; skip enumeration above this (clutter guard)
```

**`api/api.py` addition:**
```python
associators = [
    {"name": "ADSB Associator",      "id": "adsb-associator"},
    {"name": "Geometric Associator", "id": "geometric-associator"},  # ADD
]
```

**`event/event.py` addition (one elif branch):**
```python
elif item["associator"] == "geometric-associator":
    associated_dets = geometricAssociator.process(radar_list, radar_data, timestamp)
```

- [ ] Create `event/algorithm/associator/GeometricAssociator.py`
- [ ] Implement N-tuple enumeration using `itertools.product`
- [ ] Implement vectorised geometric intersection test (reuse `Ellipsoid` + `Geometry`)
- [ ] Implement Doppler sign-consistency post-filter
- [ ] Implement optional full Doppler ratio post-filter
- [ ] Implement candidate deduplication
- [ ] Add `associate.geometric` block to `config/config.yml`
- [ ] Wire into `event/event.py` and `api/api.py`
- [ ] Add `max_detections` guard to skip enumeration in high-clutter epochs
- [ ] Unit test: 3-radar synthetic geometry, 1 real target + 3 false detections per radar → exactly 1 output target
- [ ] Unit test: empty detection lists → empty output `{}`
- [ ] Unit test: output schema is identical to `AdsbAssociator` format
- [ ] Integration test: substitute `GeometricAssociator` for `AdsbAssociator` in event loop — verify localisation still produces correct positions

---

### F2 — TDOA Pair Pre-Filter and DBSCAN Alternative
- **Prerequisite**: F1 complete
- **Purpose**: Scale `GeometricAssociator` to M>20 (high false-alarm / dense detection environments) without exceeding the 500 ms latency budget

**F2a — TDOA pair pre-filter (for shared-TX geometry)**

For two receivers (i, j) sharing the same transmitter TX, the difference in bistatic ranges implies a TDOA. Given candidate delays (τᵢ, τⱼ), a necessary geometric consistency condition is:

$$|c(\tau_i - \tau_j) - (|\mathbf{TX} - \mathbf{RX}_i| - |\mathbf{TX} - \mathbf{RX}_j|)| \leq 2 R_{max}$$

where $R_{max}$ is the maximum observable target range. Use NumPy broadcasting to check all M² pairs in one vectorised operation. This prunes the candidate set to O(M_valid) before the expensive M^N enumeration.

Implementation note: This pre-filter is only valid when all radars share the same transmitter. Make it conditional on `config.associate.geometric.use_tdoa_prefilter: true` with a note that it requires shared TX.

**F2b — DBSCAN associator (alternative path for high M)**

For each radar's detection list:
1. Sample every ellipse using `EllipseParametric.sample()` (or the vectorised variant from B1)
2. Tag each point with its radar index and detection index
3. Concatenate all N×S×M points into one ECEF array
4. Run `scipy.spatial.cKDTree`-based DBSCAN with `eps=threshold`, `min_samples=N`
5. Each qualifying cluster (contains ≥1 sample from each radar) → one candidate target
6. Back-map cluster membership to detection indices to recover `{radar, delay, doppler}` tuples

Complexity: O(n log n) where n = N×S×M. For N=3, S=50, M=50: n=7,500 → sub-millisecond with cKDTree.

Limitation: DBSCAN back-mapping is non-trivial when a single detection's ellipse spans a long arc and its samples populate multiple clusters. Select the detection whose centroid of contributing samples is closest to the cluster centre.

- [ ] Implement TDOA pair pre-filter in `GeometricAssociator` as optional stage (config `use_tdoa_prefilter: true`)
- [ ] Implement DBSCAN associator path (either as mode flag in `GeometricAssociator` or separate `DBSCANAssociator` class)
- [ ] Add `scipy` to `event/requirements.txt` if not already present (check first)
- [ ] Benchmark F1 (enumeration) vs F2b (DBSCAN) at M=5, 10, 20, 50 detections/radar
- [ ] Unit test: TDOA pre-filter correctly rejects a geometrically inconsistent pair

---

### F3 — JPDA / JIPDA Track Management
- **Prerequisite**: F1 complete (track initiation); C2 EKF tracker strongly recommended
- **Purpose**: Persistent multi-target tracking without ADS-B. Reduces per-epoch jitter, provides velocity estimates, handles temporary detection gaps (target in shadow, low-SNR epoch)

**Architecture:**

`GeometricAssociator` (F1) handles **track initiation** — finding new targets from cold start each epoch. JPDA/JIPDA handles **track maintenance** — once a track exists, use its predicted position to gate and weight incoming detections probabilistically.

**Why JIPDA over JPDA:**
- JIPDA (Musicki & Evans, 2004) handles track termination probabilistically via track existence probability `P_exist` — no separate deletion rule needed
- Well-suited to 1 Hz discrete epoch structure: each epoch is one JIPDA predict+update cycle
- `P_exist` can be exposed to the UI as a confidence score (e.g. display only tracks with `P_exist > 0.9`)

**Multi-static bistatic measurement model:**

For N radars, each provides a bistatic range measurement:
$$z_i(\mathbf{x}) = |\mathbf{x} - \mathbf{TX}| + |\mathbf{x} - \mathbf{RX}_i|$$

The measurement Jacobian H_i (for the EKF linearisation) is:
$$H_i = \frac{(\mathbf{x} - \mathbf{TX})^T}{|\mathbf{x} - \mathbf{TX}|} + \frac{(\mathbf{x} - \mathbf{RX}_i)^T}{|\mathbf{x} - \mathbf{RX}_i|}$$

The joint measurement covariance is block-diagonal over radars (independent noise per receiver). This is the same Jacobian already implicit in `SphericalIntersection.py` — reuse that infrastructure.

**Integration with existing code:**
- JIPDA tracker lives in `event/algorithm/tracker/JPDATracker.py`
- Each epoch: (1) JIPDA predict all existing tracks, (2) run `GeometricAssociator` for untracked detections, (3) JIPDA update using gated detections, (4) initiate new tracks for detections unassigned to any existing track
- Track states are stored per API client (keyed by client ID) in a thread-safe dict

**Output schema extension (add to existing schema, do not break existing consumers):**
```json
{
  "a3f9c1": {
    "points": [[lat, lon, alt]],
    "velocity": [vx, vy, vz],
    "p_exist": 0.97,
    "age_epochs": 12
  }
}
```

- [ ] Create `event/algorithm/tracker/JPDATracker.py` implementing JIPDA (Musicki & Evans, 2004)
- [ ] Implement bistatic range measurement model and Jacobian H_i for N radars
- [ ] Implement track initiation (2-scan M/N confirmation from `GeometricAssociator` output)
- [ ] Implement JIPDA predict/update cycle
- [ ] Implement track deletion via `P_exist` threshold (configurable, default 0.1)
- [ ] Per-client thread-safe track store (avoid cross-contaminating independent API consumers)
- [ ] Expose `P_exist`, velocity `[vx, vy, vz]`, `age_epochs` in output schema (optional fields — backward compatible)
- [ ] Unit test: 10-epoch simulated trajectory, verify track maintained through 2-epoch detection gap
- [ ] Unit test: track terminated after 5 consecutive missed detections

---

### F4 — PHD Particle Filter (Long-Term / Research)
- **Prerequisite**: F3 complete; upstream change to blah2 to expose raw range-Doppler maps
- **Purpose**: Approaches CRLB-optimal performance for non-cooperative targets in high-clutter environments; eliminates explicit detection thresholding (Track-Before-Detect)

- **Key paper**: Vo & Ma, "The Gaussian Mixture PHD Filter," *IEEE Trans. Signal Process.* 54(11), 2006
- **PCL application**: Tharmarasa et al., "Multitarget passive coherent location with transmitted signal uncertainty," *IEEE Trans. Signal Process.* 58(9), 2010

- [ ] Define upstream requirement: blah2 API must expose range-Doppler map as 2D float array via `/api/rdmap` endpoint
- [ ] Implement Gaussian Mixture PHD filter adapted for bistatic range-Doppler observations
- [ ] Define birth intensity model for new targets (uniform over expected surveillance volume in ECEF)
- [ ] Implement resampling and pruning for particle variant
- [ ] Benchmark accuracy vs JIPDA on simulated clutter scenario with known ground truth

---

## Testing Backlog

- [ ] Unit test: `ecef2lla` with London coordinates (negative longitude)
- [ ] Unit test: `EllipseParametric("min", ...)` returns non-empty output for valid 3-radar scenario
- [ ] Unit test: `EllipsoidParametric("min", ...)` same
- [ ] Unit test: `AdsbAssociator` does not mutate input radar_data dict
- [ ] Integration test: known TX/RX/target geometry → expected LLA output within threshold
- [ ] Performance benchmark: time per target for each localisation method
- [ ] Accuracy benchmark: simulated target trajectory vs ground truth

---

## Quick Reference — Priority Order

| # | Item | Effort | Impact |
|---|------|--------|--------|
| A2 | Fix lon wrap (ecef2lla) | 1 line | All western targets are wrong |
| A1 | Fix min/minimum | 1 line | Restores 2 broken modes |
| A3 | Fix ellipsoid cache | 2 lines | Minor perf |
| A4 | Fix mutation bug | 3 lines | Correctness with multiple API clients |
| A5 | Fix 100m altitude | 1 line | Minor accuracy |
| B1 | Vectorise NumPy | 1 day | 50–200× ellipsoid speedup |
| B2 | Async HTTP | 2 days | 3× latency reduction |
| B3 | Cache config | 0.5 day | Minor speedup |
| C1 | TDOA least-squares | 3 days | Best accuracy + speed |
| C2 | EKF tracker | 1–2 weeks | Track continuity, velocity |
| C4 | GDOP metric | 1 day | Quality feedback |
| F1 | GeometricAssociator (enumeration + Doppler filter) | 3–5 days | Removes ADS-B hard dependency |
| F2 | TDOA pre-filter + DBSCAN (scales to M>20) | 3 days | Handles high-clutter environments |
| F3 | JIPDA track management | 1–2 weeks | Persistent tracking, velocity, gap handling |
| F4 | PHD particle filter | 4+ weeks | CRLB-optimal non-cooperative tracking |
| D8 | SX geometry warning in UI | 0.5 day | Prevents silent wrong results for users |
| D9 | Verify Topology B/C/D end-to-end | 2 days | Ensures multi-illuminator setups work correctly |
