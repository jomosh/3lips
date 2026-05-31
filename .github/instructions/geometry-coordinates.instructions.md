---
description: "Use when writing or modifying coordinate transform code, Geometry.py, Ellipsoid.py, or any code that converts between LLA, ECEF, and ENU. Covers WGS-84 constants, longitude wrapping, and precision rules."
applyTo: ["event/algorithm/geometry/**/*.py", "event/data/**/*.py"]
---
# Geometry & Coordinate Conventions

## WGS-84 Constants
```python
a = 6378137.0          # semi-major axis (m)
f = 1/298.257223563    # flattening
e = 0.081819190842622  # first eccentricity
b = a * sqrt(1 - e²)   # semi-minor axis ≈ 6356752.314 m
```

## Longitude Wrapping — CRITICAL
- **Always** wrap longitude to `[-π, π)`: `lon = (lon + pi) % (2 * pi) - pi`
- **Never** use `lon % (2 * pi)` — this maps western longitudes to `[π, 2π)` and breaks all map display and accuracy comparisons.

## Coordinate Order
| System | Order |
|--------|-------|
| LLA | (lat_deg, lon_deg, alt_m) |
| ECEF | (x_m, y_m, z_m) |
| ENU | (east_m, north_m, up_m) |

## Conversion Boundaries
- Convert LLA → ECEF at input (when radar config or truth data is first consumed).
- Convert ECEF → LLA at output (final `points` list in localisation result).
- Never convert ECEF → LLA → ECEF mid-algorithm; accumulates floating-point error and wastes CPU.

## Altitude Above Ground Check
- In ENU space, the `up` component is directly the height above the reference point.
- Prefer `r_enu[2] + reference_alt > 0` over a full ECEF → LLA round-trip for above-ground filtering.

## Geometry Class Rules
- All methods are `@staticmethod` — no `self` parameter, no side effects.
- Input angles: degrees for LLA, radians for intermediate trig.
- All outputs in SI units (metres, degrees).

## Tests Required
- Every `Geometry` function must have at least one test case in the **southern** hemisphere AND one in the **western** hemisphere (negative longitude).
- Use `assertAlmostEqual` with `places=3` for position (mm tolerance) and `places=4` for angular (0.0001° ≈ 11m).
