---
description: "Use when writing or modifying tests for 3lips algorithms, geometry functions, or integration scenarios. Covers test location, naming, required coverage, and synthetic scenario patterns."
applyTo: "test/**/*.py"
---
# Testing Rules

## Test Location and Structure
- All tests live under `test/event/` mirroring the `event/` source structure.
- Run from the `event/` directory: `python -m pytest ../test/`
- Test file naming: `Test<ClassName>.py` (e.g. `TestEllipseParametric.py`).

## Minimum Coverage Requirements
- Every public algorithm method (`process`, `sample`) must have at least one test.
- Every geometry function must be tested with:
  - A known closed-form point (verifiable by hand or external tool)
  - At least one **eastern** hemisphere and one **western** hemisphere case (negative longitude)
  - At least one **southern** hemisphere case (negative latitude)
- Every bug fix must include a regression test that would have failed before the fix.

## Synthetic Scenario Pattern
For localisation algorithm tests, construct a known geometry:
```python
# 1. Place TX, RX, and target at known LLA positions
# 2. Compute true bistatic range: |TX→target| + |target→RX|
# 3. Pass synthetic detection (with true delay) to algorithm
# 4. Assert output position is within tolerance of true target position
tolerance_m = 500  # CEP50 requirement
```

## Accuracy Thresholds
| Method | Position tolerance |
|--------|--------------------|
| EllipseParametric | 500m CEP50 |
| EllipsoidParametric | 500m horizontal, 1000m vertical |
| SphericalIntersection | 200m CEP50 |
| TDOALeastSquares | 100m CEP50 |

## Assertion Style
```python
self.assertAlmostEqual(result[0], expected_lat, places=3)  # ±0.001° ≈ 111m
self.assertAlmostEqual(result[1], expected_lon, places=3)
self.assertAlmostEqual(result[2], expected_alt, delta=1000) # alt tolerance 1km
```

## Test Data
- Do not rely on live radar or ADS-B data in unit tests.
- All test inputs must be synthetic and deterministic.
- If a real scenario is needed, save a fixture JSON file in `test/fixtures/`.

## Performance Tests
- For methods under `Objective B` (performance), include a `time.time()` benchmark assertion:
  ```python
  start = time.time()
  result = algorithm.process(detections, radar_data)
  elapsed = time.time() - start
  self.assertLess(elapsed, 0.1)  # 100ms per target limit
  ```
