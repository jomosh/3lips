---
description: "Debug a localisation accuracy problem in 3lips: wrong positions on map, large error vs ADS-B truth, or unexpected empty output. Systematic diagnosis workflow."
name: "Debug Localisation Accuracy"
argument-hint: "Describe the symptom (e.g. 'all positions show near 0°E longitude', 'ellipse-parametric-min returns nothing', 'positions 50km off truth')"
agent: "agent"
tools: [read, search, execute, todo]
---
Systematically debug a localisation accuracy or correctness problem in 3lips.

## Diagnostic Checklist

### Step 1 — Check coordinate output
- Is the longitude in `[-180, 180]`? If values are in `[180, 360]` → `ecef2lla` longitude wrap bug (A2 in TODO.md).
- Is altitude positive and reasonable (>0m, <15000m for civil aircraft)?
- Are lat/lon values in the right hemisphere for the configured radar locations?

### Step 2 — Check algorithm selection
- Is `item["localisation"]` matching the correct `elif` branch in `event.py`?
- For `min` variants: is the `method` string `"min"` and does the class check `== "min"` (not `"minimum"`)?
- Is `localised_dets` empty? Run the algorithm's `process()` in isolation with test data.

### Step 3 — Check association
- Is `associated_dets_3_radars` empty when it shouldn't be? The code requires `len(value) >= 3` for 3-radar intersection.
- Are radar detections actually non-None? Check `radar_dict[name]["detection"]`.
- Is the `distance_window = 10` too tight for the observed delay-Doppler offsets?

### Step 4 — Check ellipsoid geometry
- Compute `a` and `b` for one radar manually: does the ellipse physically reach the expected target area?
- Is `bistatic_range` being passed in the right units? (`radar["delay"] * 1000` gives ms; sample() expects ms).
- Is the `Ellipsoid.distance` (TX-RX baseline) plausible for the configured radar locations?

### Step 5 — Run a synthetic test
```python
# Minimal isolated test — run from event/ directory:
from algorithm.localisation.EllipseParametric import EllipseParametric
from algorithm.geometry.Geometry import Geometry
# ... construct minimal assoc_detections and radar_data dicts
result = EllipseParametric("mean", 100, 500).process(assoc_detections, radar_data)
print(result)
```

### Step 6 — Check the save file
- Open the latest `.ndjson` file in `save/` and inspect raw `detections_localised` values.
- Compare against `truth` positions in the same record.

## Output
Report: which step revealed the root cause, the exact incorrect value observed, the correct expected value, and the fix needed (cross-reference `TODO.md` item if applicable).
