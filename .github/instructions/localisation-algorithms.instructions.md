---
description: "Use when writing or modifying localisation algorithms (EllipseParametric, EllipsoidParametric, SphericalIntersection, TDOALeastSquares, EKFTracker). Covers bistatic geometry rules, output schema, caching, and vectorisation requirements."
applyTo: "event/algorithm/localisation/**/*.py"
---
# Localisation Algorithm Rules

## Output Schema
Every `process()` method must return:
```python
{
  "target_hex": {
    "points": [[lat, lon, alt], ...]   # lat/lon in degrees, alt in metres
  }
}
```
Return `{}` (empty dict) if no detections — never `None`.

## Bistatic Geometry
- Semi-major axis: `a = (bistatic_range + tx_rx_distance) / 2`
- Semi-minor axis: `b = sqrt(a² - (tx_rx_distance/2)²)`
- `bistatic_range` from radar is in **seconds** — multiply by `1000` for milliseconds, then by `c = 299792458 m/s` for metres. The code uses `radar["delay"] * 1000` because `sample()` expects milliseconds input and internally scales.
- All internal position calculations in **ECEF metres**. Convert to LLA only at the final output step.

## Caching
- Cache `Ellipsoid` objects in `self.ellipsoids` keyed by `radar_name`.
- After creating a new `Ellipsoid`, append it to `self.ellipsoids`.
- Ellipsoid geometry (TX/RX positions, distance, pitch, yaw) is static once computed.

## Vectorisation
- Intersection searches must use NumPy broadcasting, not Python for-loops.
- Use `np.linalg.norm(pts1[:, None] - pts2[None, :], axis=2)` for pairwise distance matrices.
- For K ellipsoids, build a `scipy.spatial.cKDTree` on each secondary set and use `query_ball_point`.

## Method String Convention
- The `method` constructor argument uses short strings: `"mean"` or `"min"`.
- Never check for `"minimum"` — the event loop passes `"min"`.

## Mutation Safety
- Never modify `assoc_detections` or `radar_data` arguments in-place.
- Work on local copies if modification is needed.

## SphericalIntersection Specific
- Only valid when all bistatic pairs share a common TX or common RX.
- Always check `np.linalg.matrix_rank(S) >= 3` (full column rank) before calling `np.linalg.inv(S.T @ S)`. S is (nDetections × 3); fewer than 3 non-coplanar rows make S.T @ S singular. A rank-2 check is not sufficient — use `nDetections >= 3` as a fast pre-check, then confirm rank for degenerate geometries.
- Fall back to `np.linalg.lstsq` for rank-deficient S.
