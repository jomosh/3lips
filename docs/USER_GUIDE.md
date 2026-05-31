# 3lips User Guide

## Table of Contents

1. [Overview](#overview)
2. [Requirements](#requirements)
3. [Installation](#installation)
4. [Configuration Reference](#configuration-reference)
5. [Running the System](#running-the-system)
6. [Web Interface](#web-interface)
7. [API Reference](#api-reference)
8. [Choosing a Localisation Algorithm](#choosing-a-localisation-algorithm)
9. [Deployment Topologies](#deployment-topologies)
10. [Connecting Radar Nodes](#connecting-radar-nodes)
11. [Accuracy and Limitations](#accuracy-and-limitations)
12. [Troubleshooting](#troubleshooting)
13. [Development Setup](#development-setup)

---

## Overview

3lips processes bistatic delay/Doppler detections from one or more [blah2](https://github.com/jomosh/blah2) passive coherent location (PCL) radar nodes and produces geolocated target positions. The name refers to the fact that at least three bistatic ellipsoids (from three radar pairs) are needed for a good 3D position fix.

### How It Works

Each **blah2** radar node outputs a list of detections as `(delay, Doppler)` pairs — i.e. the total path-length excess and the relative velocity of each detected target. 3lips:

1. **Fetches** detection and config data from each blah2 node every second.
2. **Associates** detections across radars using ADS-B aircraft truth from a [tar1090](https://github.com/wiedehopf/tar1090) server via [adsb2dd](https://github.com/jomosh/adsb2dd).
3. **Localises** each target using one of several ellipsoid-intersection algorithms.
4. **Serves** the results as JSON via a REST API and renders them on a MapLibre GL JS web map.

---

## Requirements

### Host System
- Linux (tested), macOS, or Windows with WSL2
- [Docker Engine](https://docs.docker.com/engine/install/) ≥ 20.10
- [Docker Compose](https://docs.docker.com/compose/install/) ≥ 2.0 (`docker compose` with a space, not `docker-compose`)
- Network access to your blah2 radar nodes and ADS-B truth server
- At least **2 blah2 radar nodes** for 2D localisation; **3 or more** for reliable 3D

### External Services Required
| Service | Purpose | URL format |
|---------|---------|-----------|
| [blah2](https://github.com/jomosh/blah2) | Bistatic radar node(s) | `hostname:port` |
| [tar1090](https://github.com/wiedehopf/tar1090) | ADS-B aircraft truth display | `hostname:port` |
| [adsb2dd](https://github.com/jomosh/adsb2dd) | ADS-B → delay-Doppler converter | `hostname:port` |

> **Note**: adsb2dd is a small service that queries your tar1090 ADS-B server and computes the expected bistatic delay and Doppler for each aircraft given a radar's TX/RX geometry. It must be running and accessible from the 3lips host.

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/jomosh/3lips /opt/3lips
cd /opt/3lips

# 2. Edit configuration (see Configuration Reference below)
nano config/config.yml

# 3. Build and start all services
docker compose up -d --build

# 4. Open the web interface
# http://localhost:49156
```

To stop:
```bash
docker compose down
```

To view logs:
```bash
docker compose logs -f         # all services
docker compose logs -f api     # API service only
docker compose logs -f event   # event loop only
```

---

## Configuration Reference

All configuration lives in `config/config.yml`. This file is mounted read-only into both containers and is read once at startup.

### Full annotated example

```yaml
# ─── Radar Nodes ────────────────────────────────────────────────────────────
radar:
  - name: radar1               # Display name shown in the web UI dropdown
    url: "radar1.example.com"  # Hostname (+ optional :port) of the blah2 node
  - name: radar2               # Add as many radar entries as you have nodes
    url: "192.168.1.50:3000"   # IP addresses work too

# ─── Association ─────────────────────────────────────────────────────────────
associate:
  adsb:
    tDelete: 5                          # Seconds; remove an ADS-B track if not
                                        # updated within this window. Increase if
                                        # your ADS-B feed is intermittent.
    adsb2dd: "adsb2dd.example.com:49155" # Hostname:port of the adsb2dd service
    adsb2dd_https: false                # Set true if adsb2dd is behind TLS

# ─── Localisation Tuning ─────────────────────────────────────────────────────
localisation:
  ellipse:
    nSamples: 100    # Number of points sampled on each 2D ellipse.
                     # Higher → finer intersection resolution, slower.
                     # Recommended range: 50–500. Start at 100.
    threshold: 500   # Distance threshold in metres. Two points on different
                     # ellipses are considered "intersecting" if they are
                     # within this distance. Too small → missed detections;
                     # too large → ambiguous positions.
    nDisplay: 50     # Number of points to send to the map for the ellipse
                     # visualisation overlay (independent of nSamples).

  ellipsoid:
    nSamples: 60     # N for the 3D ellipsoid. The surface is sampled at
                     # N × (N/2) = N²/2 points total. With N=60: 1,800 points.
                     # Increase carefully — CPU cost scales as O(N²).
    threshold: 500   # Same meaning as ellipse threshold, in metres.
    nDisplay: 50     # Points sent to map for ellipsoid visualisation.

# ─── Map Display ─────────────────────────────────────────────────────────────
map:
  location:
    latitude: 51.5074    # Initial map centre latitude (decimal degrees)
    longitude: -0.1278   # Initial map centre longitude. Negative = west.
  center_width: 50000    # Initial map view half-width in metres (E-W)
  center_height: 40000   # Initial map view half-height in metres (N-S)

  # Tile servers for map background layers.
  # Replace with your own tile proxy or self-hosted server for production.
  tile_server:
    osm: tile.openstreetmap.org/           # OpenStreetMap standard
    carto_light: basemaps.cartocdn.com/light_all/
    carto_dark: basemaps.cartocdn.com/dark_all/
    opentopomap: tile.opentopomap.org/     # Topographic (useful for terrain)

  tar1090: "adsb.example.com"  # Hostname of the tar1090 ADS-B truth display
                               # shown as overlay on the map
  tar1090_https: false         # Set true if tar1090 is behind TLS

# ─── System ──────────────────────────────────────────────────────────────────
3lips:
  save: true     # If true, write all API state to a .ndjson file in save/
                 # for offline replay and accuracy analysis.
  tDelete: 60    # Seconds of inactivity before removing an API request
                 # from the processing queue. A browser tab that is closed
                 # or stops polling will be cleaned up after this time.
```

---

### Parameter Quick Reference

| Parameter | Type | Units | Effect |
|-----------|------|-------|--------|
| `radar[].name` | string | — | Display label in UI |
| `radar[].url` | string | — | blah2 API hostname[:port] |
| `associate.adsb.tDelete` | int | seconds | ADS-B track expiry |
| `associate.adsb.adsb2dd` | string | — | adsb2dd service address |
| `localisation.ellipse.nSamples` | int | — | Ellipse sample density |
| `localisation.ellipse.threshold` | int | metres | Intersection test distance |
| `localisation.ellipse.nDisplay` | int | — | Ellipse map display points |
| `localisation.ellipsoid.nSamples` | int | — | Ellipsoid sample density (cost = N²/2) |
| `localisation.ellipsoid.threshold` | int | metres | Intersection test distance |
| `localisation.ellipsoid.nDisplay` | int | — | Ellipsoid map display points |
| `map.location.latitude` | float | degrees | Map initial centre latitude |
| `map.location.longitude` | float | degrees | Map initial centre longitude (negative = west) |
| `map.center_width` | int | metres | Initial map E-W extent |
| `map.center_height` | int | metres | Initial map N-S extent |
| `map.tar1090` | string | — | tar1090 ADS-B overlay server |
| `3lips.save` | bool | — | Enable NDJSON save file |
| `3lips.tDelete` | int | seconds | Idle API session expiry |

---

## Running the System

### Starting
```bash
cd /opt/3lips
docker compose up -d --build   # build images and start in background
docker compose ps              # check all containers are "Up"
```

### Stopping
```bash
docker compose down
```

### Restarting after config change
```bash
docker compose restart         # fast restart without rebuild
# OR
docker compose up -d --build   # rebuild if code changed
```

### Viewing real-time logs
```bash
docker compose logs -f event   # event loop processing output
docker compose logs -f api     # API request handling
```

---

## Web Interface

Open **http://localhost:49156** in a browser.

### Controls
| Control | Description |
|---------|-------------|
| **Radar servers** | Select which blah2 radar nodes to include (multi-select) |
| **Associator** | Association method — currently only ADS-B Associator |
| **Localisation** | Which algorithm to use for position fixing (see below) |
| **ADS-B** | Select the ADS-B truth server for association and map overlay |
| **Submit** | Start (or update) the processing request |

Results update once per second. The map shows:
- **Coloured ellipses/ellipsoids**: the sampled bistatic surfaces for each radar (for parametric methods)
- **Target markers**: localised positions
- **ADS-B overlay**: truth positions from tar1090 for comparison

---

## API Reference

### Endpoint: `GET /api`

Trigger or poll a localisation request.

**Query parameters:**

| Parameter | Required | Example | Description |
|-----------|----------|---------|-------------|
| `server` | yes (repeat) | `server=radar1.example.com` | blah2 radar node URL. Repeat for each radar. |
| `associator` | yes | `associator=adsb-associator` | Association method ID |
| `localisation` | yes | `localisation=ellipse-parametric-mean` | Localisation algorithm ID |
| `adsb` | yes | `adsb=adsb.example.com` | tar1090 server hostname |

**Example request:**
```
GET /api?server=radar1.example.com&server=radar2.example.com&associator=adsb-associator&localisation=ellipse-parametric-mean&adsb=adsb.example.com
```

**Response** (JSON):
```json
{
  "hash": "abc1234567",
  "server": ["radar1.example.com", "radar2.example.com"],
  "associator": "adsb-associator",
  "localisation": "ellipse-parametric-mean",
  "adsb": "adsb.example.com",
  "timestamp": 1234567890000,
  "timestamp_event": 1234567890000,
  "truth": {
    "aabbcc": { "lat": 51.5, "lon": -0.5, "alt": 8000, "flight": "BAW123", "timestamp": 1234567890 }
  },
  "detections_associated": {
    "aabbcc": [
      { "radar": "radar1.example.com", "delay": 0.000234, "doppler": 12.5, "timestamp": 1234567890 }
    ]
  },
  "detections_localised": {
    "aabbcc": { "points": [[51.52, -0.48, 0]] }
  },
  "ellipsoids": {
    "radar1.example.com": [[51.1, -0.8, 0], [51.2, -0.7, 0], "..."]
  },
  "time": 0.085
}
```

**Response fields:**

| Field | Type | Description |
|-------|------|-------------|
| `hash` | string | Unique ID for this parameter set |
| `truth` | object | ADS-B truth positions by aircraft hex code |
| `detections_associated` | object | Associated detections by hex, per radar |
| `detections_localised` | object | Localised positions `[lat, lon, alt]` per hex |
| `ellipsoids` | object | Sampled ellipsoid points per radar (for map display) |
| `time` | float | Processing time in seconds for this epoch |

---

### Endpoint: `GET /config`

Returns the current `config.yml` as JSON. Useful for frontend initialisation.

---

## Choosing a Localisation Algorithm

| Algorithm ID | Description | Radars needed | 3D? | Speed | Notes |
|---|---|---|---|---|---|
| `ellipse-parametric-mean` | Sample 2D ellipses at ground level, find mean intersection | ≥ 3 | No | Medium | Good for flat terrain scenarios. Altitude forced to 0. |
| `ellipse-parametric-min` | Same, but report minimum-distance intersection point | ≥ 3 | No | Medium | More precise point estimate than mean. |
| `ellipsoid-parametric-mean` | Sample 3D ellipsoids, find mean intersection | ≥ 3 | Yes | Slow | Provides altitude estimate. CPU intensive with high nSamples. |
| `ellipsoid-parametric-min` | Same, but report minimum-distance intersection point | ≥ 3 | Yes | Slow | Best 3D accuracy of parametric methods. |
| `spherical-intersection` | Closed-form algebraic solution | ≥ 3 | Yes | Fast | **Requires all radars to share a common TX or common RX.** Will give wrong results for arbitrary geometries. Only works for Topology A (shared TX) currently; Topology B (shared RX) is a known bug. |

### Recommendations

- **Getting started**: Use `ellipse-parametric-mean` — it is the most forgiving and always gives a result as long as 3+ radars are active.
- **Best 2D accuracy**: `ellipse-parametric-min` with `nSamples: 200–500`.
- **3D position (altitude)**: `ellipsoid-parametric-min` — increase `nSamples` to 80–120 for better altitude accuracy. Note: slow.
- **Lowest latency**: `spherical-intersection` — if your deployment has a common transmitter (e.g. a single FM broadcast transmitter with multiple receivers), this is the fastest and most accurate option.
- **High target count**: Reduce `nSamples` and `threshold`, or switch to `spherical-intersection`.

### Tuning `nSamples` and `threshold`

> **See also**: [Deployment Topologies](#deployment-topologies) for guidance on how different physical arrangements of TX and RX sites affect which algorithms you can use and how many bistatic pairs you need.

- `threshold` should be set to approximately the **range resolution** of your radar (speed of light × pulse bandwidth reciprocal). For FM-based passive radar with ~100kHz bandwidth: resolution ≈ 3000m. For DAB with ~1.5MHz: ≈ 200m. A typical starting value is 500m.
- `nSamples` controls how finely the ellipse is sampled. Too low → misses the intersection. Too high → slow. Scale with `threshold`: a tighter threshold needs more samples to ensure two ellipses' sample points fall within it.

---

## Deployment Topologies

3lips is a **multi-bistatic** passive radar system. Each blah2 node represents one **bistatic pair** — one transmitter (TX) and one receiver (RX). The physical arrangement of those TX and RX sites determines what position information you can extract and which algorithms apply.

The four principal configurations are described below.

---

### Topology A — Multiple RX, Shared TX *(standard PCL)*

```
         [FM Tower / TX]
          /      |      \
        RX1     RX2     RX3
```

- **Description**: One transmitter of opportunity (FM, DAB, DVB-T broadcast); multiple independent passive receivers.
- **Each blah2 node**: Same `tx` latitude/longitude/altitude, different `rx` coordinates.
- **Geometry**: All ellipsoids share the FM tower as one focus. Baselines fan outward from the TX toward each RX. Angular diversity depends on how widely the receivers are spread around the transmitter.
- **Algorithms**: All three algorithms support this. `SphericalIntersection` is specifically designed for it.
- **Minimum for a reliable 3D fix**: 3 bistatic pairs (3 RX nodes).
- **Practical notes**: This is the most common PCL deployment and the architecture the current codebase is optimized for. A typical example: one FM broadcast tower with three receive masts at 20–100 km range.

---

### Topology B — Multiple TX, Shared RX *(multi-illuminator)*

```
  [FM-A]   [DAB-B]  [DVB-T-C]
      \       |      /
           [RX]
```

- **Description**: A single receive site processes signals from multiple transmitters of opportunity simultaneously.
- **Each blah2 node**: Same `rx` coordinates, different `tx` coordinates.
- **Geometry**: All ellipsoids share the RX site as one focus. Baselines fan outward from the RX toward each TX. Good geometric diversity if transmitters are angularly spread as seen from the receiver.
- **Algorithms**:
  - `EllipseParametric` / `EllipsoidParametric`: ✅ Fully supported — each radar constructs its own ellipsoid from its individual TX/RX config.
  - `SphericalIntersection`: ⚠️ **Currently broken** — the code hardcodes `type="rx"` (TX as the shared node), which is the inverse of what this topology requires. Fix is tracked as TODO item **C6**. After the fix, configure `shared_node: rx` in `config.yml`.
- **Minimum for a reliable 3D fix**: 3 bistatic pairs (3 TX sources).
- **Practical advantage**: Only one receive antenna mast and one wideband ADC/blah2 receiver are required. Multiple blah2 processes run on the same hardware, each tuned to a different carrier frequency and configured with the corresponding transmitter coordinates. This is arguably the most hardware-efficient passive radar architecture.

---

### Topology C — Multiple TX, Multiple RX *(fully multistatic)*

```
  [TX-A]            [TX-B]
     |  \          /  |
     |   [RX1] [RX2]  |
     |________________|
```

- **Description**: Each blah2 node is a fully independent bistatic pair — no TX or RX site is shared between any two nodes.
- **Each blah2 node**: Different `tx` and different `rx` coordinates.
- **Geometry**: Maximum geometric diversity. Ellipsoid baselines point in all directions. GDOP (Geometric Dilution of Precision) is typically the best achievable for a given number of sites.
- **Algorithms**:
  - `EllipseParametric` / `EllipsoidParametric`: ✅ Fully supported — algorithm is geometry-agnostic; it builds one ellipsoid per bistatic pair from that pair's TX/RX positions.
  - `SphericalIntersection`: ❌ **Not applicable** — the SX closed-form solution requires a shared common node (shared TX or shared RX). It cannot be applied to arbitrary multistatic geometries. Use `EllipseParametric` or, when available, the planned TDOA Least-Squares algorithm (TODO item **C1**), which handles all topologies.
- **Minimum for a reliable 3D fix**: 3 independent bistatic pairs.
- **Overdetermined variant — 2 TX × 2 RX**: Two transmit sites (A, B) and two receive sites (1, 2) can be configured as four blah2 nodes covering all pairings: TX-A/RX-1, TX-A/RX-2, TX-B/RX-1, TX-B/RX-2. This gives 4 bistatic pairs (highly overdetermined for 3D) from only 4 physical antenna locations. Parametric algorithms support this without modification.

---

### Topology D — Same TX and RX, Multiple Carrier Frequencies

```
    [TX] ————————————— [RX]
 (same sites, different fc: 88 MHz, 103 MHz, 198 MHz …)
```

- **Description**: The same physical TX and RX sites are used, but different carrier frequencies are processed (e.g. two FM stations in view of the same receiver).
- **Each blah2 node**: **Identical** `tx` and `rx` coordinates; different `fc`.
- **Geometry**: A bistatic ellipsoid is defined entirely by the TX and RX positions and the measured bistatic range. Since path lengths are **frequency-independent** in air, the same target produces the same bistatic range at all frequencies → **identical ellipsoids**. Multiple frequencies add zero additional geometric constraint for localisation.
  - Formally: all ellipsoids are confocal (same two foci) and co-sized (same semi-major axis for any given target). Intersecting identical surfaces gives the entire surface, not a point.
- **Cannot localise on its own**. If you want frequency diversity, pair it with at least one additional independent bistatic pair from a different TX or RX site (Topology A, B, or C).
- **What multiple frequencies do provide**: *Detection diversity* — targets with frequency-selective RCS may appear on one frequency and not another. You see more or different targets, but the position accuracy for any individual target does not improve.

---

### Algorithm and Topology Compatibility

| Topology | `EllipseParametric` | `EllipsoidParametric` | `SphericalIntersection` |
|---|:---:|:---:|:---:|
| **A** — Multiple RX, shared TX | ✅ | ✅ | ✅ *(designed for this)* |
| **B** — Multiple TX, shared RX | ✅ | ✅ | ⚠️ Broken (TODO C6) |
| **C** — Multiple TX, multiple RX | ✅ | ✅ | ❌ Not applicable |
| **D** — Same TX/RX, different fc | ❌ No geometric benefit | ❌ | ❌ |

### Minimum Bistatic Pairs Required

All algorithms need at least **3 independent bistatic pairs with distinct baselines** for a reliable 3D position fix.

| Pairs available | Outcome |
|---|---|
| 1 | Target constrained to an ellipsoid surface — no position fix |
| 2 | Intersection is a 3D curve — two ambiguous ghost solutions; unreliable |
| **3** | **Unique 3D fix** (non-degenerate geometry). Ghost probability ~1 in 10,000 per epoch with well-separated baselines |
| 4+ | Overdetermined — improved accuracy and ghost immunity |

> **`SphericalIntersection` with 2 pairs**: The algorithm will raise an unhandled exception (singular matrix crash) if fewer than 3 pairs are supplied. This is a known bug — TODO item **D1**.

---

## Connecting Radar Nodes

Each blah2 node must be network-accessible from the 3lips host. The 3lips event loop polls two endpoints per node:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/detection` | GET | Returns current delay/Doppler detections |
| `/api/config` | GET | Returns TX/RX positions, carrier frequency |

The `/api/config` response must include:
```json
{
  "location": {
    "tx": { "latitude": ..., "longitude": ..., "altitude": ... },
    "rx": { "latitude": ..., "longitude": ..., "altitude": ... }
  },
  "capture": {
    "fc": 100000000
  },
  "truth": {
    "adsb": {
      "tar1090": "hostname"
    }
  }
}
```

If a radar node is unreachable (timeout or error), 3lips continues with the remaining available nodes. Localisation requires at least **3 nodes responding** for all methods. `SphericalIntersection` is documented elsewhere as needing only 2, but the current implementation will crash (singular matrix) with fewer than 3 — see TODO item D1.

---

## Accuracy and Limitations

### Expected Accuracy
| Scenario | Horizontal CEP50 | Notes |
|----------|-----------------|-------|
| 3 radars, 50km range, 100m range res | ~300–500m | Good geometry |
| 3 radars, poor crossing angle (<20°) | >1000m | Dilution of precision |
| 3 radars (SphericalIntersection) | ~200–500m | Common TX only; requires 3 pairs minimum |
| Altitude (EllipsoidParametric) | ~500–2000m | Highly geometry dependent |

### Known Limitations
1. **ADS-B dependency**: The current association requires ADS-B truth. Targets not broadcasting ADS-B (military, general aviation without transponder) are not localised.
2. **Minimum 3 radars** for parametric methods. With only 2 radars, two ellipses intersect along a curve, not a point.
3. **SphericalIntersection requires a shared node**: All radars must share the same transmitter (Topology A) or the same receiver (Topology B — currently a bug, TODO C6). Mixing independent TX/RX pairs (Topology C) gives wrong positions silently. See the [Deployment Topologies](#deployment-topologies) section for full details.
4. **No temporal smoothing**: Each epoch produces an independent position fix. Track jitter is expected; a Kalman filter is planned (see `TODO.md`).
5. **Western hemisphere**: A known longitude-wrapping bug affects targets west of 0° longitude. Tracked in `TODO.md` item A2.

---

## Troubleshooting

### No targets appearing on map
1. Check the event container logs: `docker compose logs -f event`
2. Verify radar nodes are accessible: `curl http://<radar-url>/api/config`
3. Verify adsb2dd is running: `curl http://<adsb2dd-url>/api/dd?...`
4. Check that ADS-B aircraft are visible in tar1090 within the radar coverage area
5. Confirm `associate.adsb.adsb2dd` in config.yml matches your adsb2dd address

### Targets appear at wrong location (e.g. near 0°E when they should be in UK)
- This is bug **A2** in `TODO.md`: longitude wrapping in `ecef2lla`. See TODO for fix.

### `ellipse-parametric-min` / `ellipsoid-parametric-min` return nothing
- This is bug **A1** in `TODO.md`: string mismatch between `"min"` and `"minimum"`.

### Event loop is very slow (>2s per epoch)
- Reduce `nSamples` (especially for `ellipsoid` — cost scales as N²/2).
- Check if radar nodes are timing out (adds 1s per node × 2 calls = up to 6s with 3 nodes).
- See `TODO.md` items B1–B6 for planned performance improvements.

### Docker build fails
- Ensure Docker Engine is ≥ 20.10.
- On Linux, ensure your user is in the `docker` group: `sudo usermod -aG docker $USER`
- Try: `docker compose build --no-cache`

### Port 49156 already in use
- Change the host port in `docker-compose.yml`: `"49156:5000"` → `"<new_port>:5000"`

---

## Development Setup

### Running without Docker

```bash
# Terminal 1: API service
cd api
pip install -r requirements.txt
flask run --port 5000

# Terminal 2: Event loop
cd event
pip install -r requirements.txt
python event.py
```

### Running tests

```bash
cd event
python -m pytest ../test/ -v
```

### Project structure

```
3lips/
├── api/                    # Flask API server + web frontend
│   ├── api.py              # Main API routes and validation
│   ├── map/                # MapLibre GL JS frontend
│   └── templates/          # Jinja2 HTML templates
├── common/
│   └── Message.py          # ZMQ messaging wrapper
├── config/
│   └── config.yml          # All runtime configuration
├── event/                  # Async event processing loop
│   ├── event.py            # Main event loop (1 Hz)
│   ├── algorithm/
│   │   ├── associator/     # Detection association algorithms
│   │   ├── geometry/       # WGS-84 coordinate transforms
│   │   ├── localisation/   # Position fix algorithms
│   │   └── truth/          # ADS-B truth fetching
│   └── data/
│       └── Ellipsoid.py    # Bistatic ellipsoid geometry
├── test/                   # Unit tests (run from event/ directory)
├── save/                   # NDJSON session save files (auto-created)
├── docs/                   # Documentation
│   └── USER_GUIDE.md       # This file
└── TODO.md                 # Development roadmap
```

### Saved session files

When `3lips.save: true`, each run creates a `.ndjson` file in `save/` named by Unix timestamp. Each line is a JSON snapshot of the full API state at one epoch. Use `script/plot_accuracy.py` and `script/plot_associate.py` for offline analysis.

```bash
cd script
pip install -r requirements.txt
python plot_accuracy.py ../save/<timestamp>.ndjson
```
