---
description: "Implement a new localisation algorithm for 3lips: creates the class file, wires it into api.py and event.py, and scaffolds the unit test."
name: "Implement Localisation Algorithm"
argument-hint: "Algorithm name and brief description (e.g. 'TDOA Least-Squares using scipy LM optimiser')"
agent: "agent"
tools: [read, edit, search, todo]
---
Implement a new localisation algorithm for 3lips following the project conventions.

## Steps

1. **Read first** — read the existing algorithm most similar to what is being implemented (e.g. `event/algorithm/localisation/EllipseParametric.py` for a sampling method, `SphericalIntersection.py` for a closed-form method).

2. **Create the class** at `event/algorithm/localisation/<ClassName>.py`:
   - Constructor: `__init__(self, **kwargs)` accepting any config parameters
   - Method: `process(self, assoc_detections, radar_data) -> dict`
   - Return schema: `{target_hex: {"points": [[lat, lon, alt], ...]}}`
   - Return `{}` if no detections — never `None`
   - All geometry in ECEF; convert to LLA only at final output
   - Cache static geometry (Ellipsoid objects) in `self.<cache_list>`

3. **Wire into `api/api.py`** — add entry to `localisations` list:
   ```python
   {"name": "<Display Name>", "id": "<kebab-id>"}
   ```

4. **Wire into `event/event.py`** — add `elif` branch and instantiate at top:
   ```python
   myAlgorithm = MyAlgorithm(...)
   # ...
   elif item["localisation"] == "<kebab-id>":
       localisation = myAlgorithm
   ```

5. **Write unit test** at `test/event/Test<ClassName>.py`:
   - Construct a synthetic 3-radar geometry with a known target position
   - Compute true bistatic ranges from geometry
   - Assert output position within tolerance (see testing.instructions.md)
   - Assert `process({}, radar_data)` returns `{}`

6. **Benchmark** — measure and document processing time per target.

7. **Update `TODO.md`** — check off the relevant task.

## Geometric requirements to document in docstring
- Minimum number of radars required
- Whether shared TX or shared RX is assumed
- Coordinate system assumptions
- Known failure modes (near-collinear geometry, low altitude targets, etc.)
