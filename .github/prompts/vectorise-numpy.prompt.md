---
description: "Vectorise a slow Python function in 3lips using NumPy: replace for-loops with broadcasting, add KD-tree nearest-neighbour search, and benchmark the result."
name: "Vectorise Python with NumPy"
argument-hint: "Function name and file path to vectorise (e.g. 'EllipseParametric.process in event/algorithm/localisation/EllipseParametric.py')"
agent: "agent"
tools: [read, edit, execute, todo]
---
Vectorise a performance-critical Python function in 3lips using NumPy.

## Workflow

1. **Profile first** — measure the current execution time:
   ```bash
   cd event && python -c "
   import time, cProfile
   # import and run the target function with realistic data
   cProfile.run('target_function()', sort='cumulative')
   "
   ```

2. **Identify the bottleneck** — look for lines with high `cumtime` involving `math.sqrt`, list comprehensions, or nested `for` loops.

3. **Vectorise the distance computation**:
   ```python
   # Replace:
   for p1 in list1:
       for p2 in list2:
           d = math.sqrt((p1[0]-p2[0])**2 + ...)

   # With:
   arr1 = np.array(list1)   # (N, 3)
   arr2 = np.array(list2)   # (M, 3)
   dists = np.linalg.norm(arr1[:, None] - arr2[None, :], axis=2)  # (N, M)
   ```

4. **For the intersection mean/min methods**:
   ```python
   # mean: find all points in arr1 that have any neighbour in arr2 within threshold
   valid = np.any(dists < threshold, axis=1)
   valid_points = arr1[valid]
   result = valid_points.mean(axis=0) if len(valid_points) > 0 else None

   # min: find point in arr1 with minimum distance to nearest in arr2
   min_dists = dists.min(axis=1)
   best_idx = np.argmin(min_dists)
   result = arr1[best_idx] if min_dists[best_idx] < threshold else None
   ```

5. **For large N (>500 points), use cKDTree**:
   ```python
   from scipy.spatial import cKDTree
   tree2 = cKDTree(arr2)
   # Query: for each point in arr1, find nearest in arr2
   min_dists, _ = tree2.query(arr1)
   valid = min_dists < threshold
   ```

6. **Validate** — run the existing unit tests to confirm outputs are equivalent.

7. **Benchmark** — measure new execution time and compare:
   ```python
   import time
   start = time.perf_counter()
   for _ in range(100): target_function(...)
   print(f"{(time.perf_counter()-start)*10:.2f}ms per call")
   ```

8. **Update TODO.md** — check off the relevant B-series task.
