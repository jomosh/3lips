---
description: "Use when writing performance-sensitive Python code in the event loop or algorithm files. Covers NumPy vectorisation patterns, async HTTP, caching, and profiling conventions for 3lips."
applyTo: "event/**/*.py"
---
# Performance Rules for Event Loop Code

## NumPy Vectorisation
- Use NumPy for **any** operation over more than ~10 elements.
- Replace `for point in list: math.sqrt(...)` with `np.linalg.norm(array, axis=1)`.
- Replace pairwise distance loops with broadcasting:
  ```python
  dists = np.linalg.norm(pts1[:, None] - pts2[None, :], axis=2)  # (N, M)
  ```
- Use `np.any(dists < threshold, axis=1)` instead of any-loop over distances.

## Avoid These Anti-Patterns
```python
# BAD: Python loop over geometry
for p in points:
    d = math.sqrt((p[0]-x)**2 + (p[1]-y)**2 + (p[2]-z)**2)

# GOOD: vectorised
pts = np.array(points)
d = np.linalg.norm(pts - np.array([x, y, z]), axis=1)
```

## Async HTTP
- Use `aiohttp` + `asyncio.gather` for all concurrent radar fetches.
- Never use `requests.get` inside the async event loop for parallelisable calls.
- Timeout: 1s per request (existing convention).

## Caching
- Radar config (TX/RX position, carrier frequency) changes at most on radar restart — cache in a dict, refresh on failure or every 60s.
- Ellipsoid geometry (computed from config) is static — cache in the algorithm instance.

## Profiling Conventions
- Before optimising, measure: `python -m cProfile -s cumulative event.py | head -30`
- For line-level: `pip install line_profiler` and use `@profile` decorator.
- Always record a before/after benchmark in the PR description.

## Memory
- Avoid materialising `n × m` distance matrices if `n*m > 1e6` — use KD-tree instead.
- Do not keep processed frame data in memory longer than one epoch; the `api` list handles retention.
