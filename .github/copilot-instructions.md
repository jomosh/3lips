# 3lips — Copilot Instructions

## Project Purpose

3lips is a **real-time multi-static passive radar target localisation system**. It receives bistatic delay/Doppler detections from multiple [blah2](https://github.com/jomosh/blah2) radar nodes, associates them to aircraft targets using ADS-B truth via [adsb2dd](https://github.com/jomosh/adsb2dd), localises target positions using geometric algorithms, and serves results through a JSON API and a MapLibre GL JS web frontend.

This is a **signal-processing and sensor fusion project**, not a general web app. Every change must be evaluated for its effect on **localisation accuracy**, **processing latency**, and **algorithmic correctness**.

---

## Architecture

```
blah2 radar nodes (HTTP)          ADS-B truth (tar1090 HTTP)
        │                                    │
        ▼                                    ▼
event/event.py  ─── ZMQ (port 6969) ───  api/api.py (Flask)
   │                                          │
   ├─ algorithm/associator/AdsbAssociator     └─ map/ (MapLibre GL JS frontend)
   ├─ algorithm/localisation/
   │   ├─ EllipseParametric.py   (2D, parametric sampling)
   │   ├─ EllipsoidParametric.py (3D, parametric sampling)
   │   └─ SphericalIntersection.py (closed-form, shared TX/RX only)
   ├─ algorithm/geometry/Geometry.py  (WGS-84 coordinate transforms)
   ├─ algorithm/truth/AdsbTruth.py
   └─ data/Ellipsoid.py
```

- **`api/`**: Flask server, serves web UI and `/api` endpoint, validates inputs, forwards to event loop via ZMQ `Message`.
- **`event/`**: Asynchronous event loop (1 Hz). Fetches radar data, runs association and localisation, writes results back to API state.
- **`common/Message.py`**: ZMQ pub/sub wrapper between api and event containers.
- **`config/config.yml`**: Single source of truth for all runtime configuration.

---

## Domain Knowledge — Bistatic Radar Geometry

- A **bistatic radar** has a transmitter (TX) and a separate receiver (RX). The target lies on an **ellipsoid** with TX and RX as foci, and semi-major axis `a = (bistatic_range + TX-RX_distance) / 2`.
- **Bistatic range** (delay × speed_of_light) is the sum of the TX→target and target→RX path lengths. This is what `radar["delay"]` encodes (in seconds; multiply by 1000 for milliseconds, then × c for metres).
- **Localisation** requires ≥2 bistatic pairs (radars) to intersect their ellipsoids and find the target position.
- The **SphericalIntersection (SX) method** is a closed-form solution valid *only* when all bistatic pairs share a common TX or a common RX. Do not apply SX to arbitrary multi-static geometries.
- All position computations use **ECEF (Earth-Centred Earth-Fixed)** coordinates internally. Convert to/from **LLA (latitude/longitude/altitude)** only at input/output boundaries. Never accumulate errors by converting back and forth mid-computation.
- **WGS-84** is the reference ellipsoid throughout. Use constants: `a = 6378137.0 m`, `f = 1/298.257223563`.

---

## Coordinate Conventions

- **LLA**: latitude (degrees, -90 to +90), longitude (degrees, **-180 to +180**), altitude (metres above WGS-84 ellipsoid).
- **ECEF**: x (metres, through prime meridian equator), y (metres, 90°E equator), z (metres, north pole).
- **ENU**: local East-North-Up frame, origin at a reference LLA point.
- `Geometry.ecef2lla` must return longitude in `[-π, π)` — currently it incorrectly wraps to `[0, 2π)`. **Do not use** `lon % (2*pi)` anywhere; use `(lon + pi) % (2*pi) - pi`.
- When converting a chain ENU→ECEF→LLA, prefer a direct altitude check on the ENU `u` (up) component rather than a full round-trip.

---

## Code Conventions

- **Python 3.x**, no typing annotations required but acceptable.
- **NumPy** for all batch array operations; never use Python `for` loops with `math.sqrt` for operations over more than ~10 elements. Prefer vectorised operations.
- **`scipy`** is available (or should be added) for optimisation (`scipy.optimize.least_squares`) and spatial indexing (`scipy.spatial.cKDTree`).
- **`requests`** is used for synchronous HTTP; migrate to **`aiohttp`** for any new async fetch code.
- Algorithm classes are stateless per-call (except for cache). Pass all inputs as arguments; do **not** mutate arguments in-place.
- `Geometry` methods are static (no `self`). Keep them pure functions with no side effects.
- Config values are loaded from `config/config.yml` once at startup and passed to constructors — no runtime re-reads except for intentional cache refresh.

---

## Performance Requirements

- **Event loop latency**: target <500ms per epoch for 3 radars, 5 targets. The event loop runs at 1 Hz; any localisation taking >1s will cause the queue to fall behind.
- **Per-target localisation**: target <100ms per target for parametric methods; <10ms for least-squares / SX methods.
- **HTTP fetch budget**: total radar data fetch should complete in <1s (use concurrent async fetches).
- **Memory**: avoid materialising large intermediate arrays that are only needed for one step. Stream or chunk where possible.
- Profile with Python `cProfile` or `line_profiler` before and after optimisation changes.

---

## Accuracy Requirements

- **2D localisation accuracy**: CEP50 < 500m for a 3-radar geometry with 100m range resolution at 50km range (typical passive radar scenario).
- **3D localisation accuracy**: CEP50 < 1km in altitude for `EllipsoidParametric`.
- **Comparison baseline**: ADS-B truth positions (accuracy ~10m horizontal, ~30m vertical). All accuracy metrics should be computed against ADS-B.
- When adding a new algorithm, always provide an accuracy benchmark against a known synthetic scenario with ground truth.

---

## Testing

- Unit tests live in `test/`.
- Run tests with: `python -m pytest test/` from the `event/` directory.
- Each algorithm must have at least one unit test with a known closed-form answer.
- Geometry tests (`TestGeometry.py`) must include both eastern and **western** hemisphere cases.
- When fixing a bug, add a regression test that would have caught it.

---

## Known Issues to Never Re-introduce

- Do **not** use `lon % (2 * math.pi)` — this produces wrong longitudes for the western hemisphere.
- Do **not** mutate `radar_data` or `radar_detections` dicts that are passed in from the event loop. Always work on copies.
- Do **not** use the string `"minimum"` in new localisation `method` comparisons — the convention is `"min"` (matching what `event.py` passes to constructors).
- Do **not** leave `self.ellipsoids` cache unpopulated after creation.

---

## Adding a New Localisation Algorithm

1. Create `event/algorithm/localisation/<ClassName>.py`.
2. Implement `process(assoc_detections, radar_data) -> dict` with the same output schema: `{target_hex: {"points": [[lat, lon, alt], ...]}}`.
3. Add an entry to the `localisations` list in `api/api.py`.
4. Add the `elif` branch in `event/event.py`.
5. Write a unit test in `test/event/`.
6. Add a benchmark entry comparing accuracy and latency vs existing methods.
7. Document the algorithm's geometric requirements (minimum radars, shared TX/RX assumption, etc.) in the class docstring.

---

## Docker & Services

- **`api`** service: Flask on port 49156. Mounts `config/` read-only.
- **`event`** service: async Python loop. Mounts `config/` and `save/`.
- Services communicate via ZMQ on the Docker internal network (host `event`, port `6969`).
- See `docker-compose.yml` for full service definitions and port mappings.
- See `docs/USER_GUIDE.md` for full setup instructions.
