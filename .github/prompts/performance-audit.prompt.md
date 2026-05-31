---
description: "Audit the 3lips event loop for performance bottlenecks: profile execution, identify slow operations, and produce a prioritised list of optimisation recommendations."
name: "Performance Audit"
argument-hint: "Optional: specific component to audit (e.g. 'EllipsoidParametric', 'HTTP fetch', 'full event loop')"
agent: "agent"
tools: [read, search, execute]
---
Perform a performance audit of the 3lips event loop.

## Audit Scope
Read and analyse the following files:
- `event/event.py` — event loop structure, HTTP fetches, per-target processing
- `event/algorithm/localisation/EllipseParametric.py` — 2D intersection
- `event/algorithm/localisation/EllipsoidParametric.py` — 3D intersection
- `event/algorithm/localisation/SphericalIntersection.py` — closed-form
- `event/algorithm/geometry/Geometry.py` — coordinate transform calls
- `event/algorithm/associator/AdsbAssociator.py` — per-radar HTTP + association

## Analysis Dimensions

### 1. I/O Latency
- Count sequential `requests.get` calls per epoch.
- Estimate worst-case total I/O time (n_radars × timeout).
- Identify any config fetch calls that could be cached.

### 2. Computational Complexity
- For each algorithm, state the complexity in terms of:
  - `N` = nSamples
  - `K` = number of radars
  - `T` = number of targets
- Identify O(N²) or O(N·M) patterns that could be reduced.

### 3. Vectorisation Gaps
- List all `for` loops that call `math.sqrt` or scalar distance functions.
- List all loops that iterate over points in NumPy arrays (should use broadcasting).

### 4. Redundant Computation
- List any coordinate transforms computed more than once for the same point in the same frame.
- List any objects constructed from scratch each frame that could be cached.

## Output Format
Produce a prioritised table:
| Component | Issue | Complexity | Estimated Speedup | Effort |
|-----------|-------|-----------|-------------------|--------|

Then a narrative summary with the top 3 highest-ROI optimisations to implement first.
