---
description: "Add a unit test for a 3lips algorithm or geometry function using a synthetic known-answer scenario. Use when a new algorithm is added, a bug is fixed, or test coverage needs improving."
name: "Add Algorithm Unit Test"
argument-hint: "Algorithm or function to test and what scenario (e.g. 'EllipseParametric mean intersection with 3 radars in UK geometry')"
agent: "agent"
tools: [read, edit, search]
---
Add a unit test for a 3lips algorithm using a synthetic geometry with a known ground-truth answer.

## Synthetic Test Pattern

```python
import unittest
import math
from algorithm.localisation.<ClassName> import <ClassName>
from algorithm.geometry.Geometry import Geometry

class Test<ClassName>(unittest.TestCase):

    def setUp(self):
        # Define a known geometry: TX, RX, and target at known LLA
        self.target_lat  = 51.5     # degrees
        self.target_lon  = -0.5    # western hemisphere — must work correctly
        self.target_alt  = 8000.0  # metres

        # Radar 1: TX and RX at known positions
        self.tx1_lla = (51.0, -1.0, 50.0)
        self.rx1_lla = (51.5, -1.5, 50.0)

        # Compute true bistatic range for radar 1
        tx1_ecef = Geometry.lla2ecef(*self.tx1_lla)
        rx1_ecef = Geometry.lla2ecef(*self.rx1_lla)
        tgt_ecef = Geometry.lla2ecef(self.target_lat, self.target_lon, self.target_alt)
        self.delay1 = (
            Geometry.distance_ecef(tx1_ecef, tgt_ecef) +
            Geometry.distance_ecef(tgt_ecef, rx1_ecef)
        ) / (299792458 * 1e-3)   # → milliseconds

    def test_process_returns_correct_position(self):
        algo = <ClassName>("mean", nSamples=200, threshold=500)
        assoc = {"aabbcc": [
            {"radar": "radar1", "delay": self.delay1 / 1000},   # seconds
            ...
        ]}
        radar_data = {
            "radar1": {"config": {"location": {
                "tx": {"latitude": self.tx1_lla[0], "longitude": self.tx1_lla[1], "altitude": self.tx1_lla[2]},
                "rx": {"latitude": self.rx1_lla[0], "longitude": self.rx1_lla[1], "altitude": self.rx1_lla[2]}
            }}},
            ...
        }
        result = algo.process(assoc, radar_data)
        self.assertIn("aabbcc", result)
        pt = result["aabbcc"]["points"][0]
        self.assertAlmostEqual(pt[0], self.target_lat, delta=0.5)   # ±0.5° ≈ 55km (coarse)
        self.assertAlmostEqual(pt[1], self.target_lon, delta=0.5)   # must be negative for western lon

    def test_empty_input_returns_empty(self):
        algo = <ClassName>("mean", nSamples=100, threshold=500)
        self.assertEqual(algo.process({}, {}), {})

if __name__ == '__main__':
    unittest.main()
```

## Required Test Cases for Every Algorithm
1. **Valid 3-radar scenario** — assert position within tolerance
2. **Empty input** — assert returns `{}`
3. **Western hemisphere** — target with negative longitude, assert `result_lon < 0`
4. **Minimum radar count** — exactly the minimum required radars (e.g. 2 for parametric, 2 for SX)

## Tolerance Guidelines
| Algorithm | Lat/lon tolerance | Alt tolerance |
|-----------|------------------|---------------|
| EllipseParametric | 0.01° (≈1km) | N/A (2D) |
| EllipsoidParametric | 0.01° | 1000m |
| SphericalIntersection | 0.005° | 500m |
| TDOALeastSquares | 0.002° | 200m |
