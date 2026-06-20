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
- At least **3 blah2 radar nodes** (the event loop requires ≥ 3 associated detections before any localisation algorithm runs)

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

# ─── Blind (ADS‑B‑Free) Association ──────────────────────────────────────────
# These settings only take effect when noncooperative.enabled is true (see below).
associate:
  geometric:
    threshold: 500        # Metres — spatial proximity for intersection test.
                          # Candidates whose sampled ellipse points don't all
                          # mutually intersect within this distance are rejected.
                          # Start at 500 and tune with your radar's range resolution.
    nSamples: 50          # Ellipse sample points per detection. Lower than
                          # localisation nSamples for speed (association samples
                          # many candidate tuples). Increase for better ghost
                          # rejection at the cost of CPU.
    doppler_tolerance: 5  # Hz — Doppler sign-consistency filter. All radars in
                          # a candidate tuple must observe the same Doppler sign
                          # (all positive or all negative). Tolerance allows for
                          # noise: set to 2× your CPI Doppler resolution.
    max_detections: 20    # Per-radar guard. If any radar has more than this many
                          # detections in one epoch, enumeration is skipped entirely
                          # (clutter / interference spike protection).

# ─── EKF Tracker ─────────────────────────────────────────────────────────────
tracker:
  ekf:
    process_noise_q: 1.0       # m²/s³ — continuous white-noise acceleration.
                               # Lower values = smoother tracks but slower response
                               # to manoeuvring targets. 1.0 suits civil aviation.
    measurement_noise_r: 2500  # m² — bistatic range variance. Default 2500 ≈
                               # 50 m standard deviation, typical for FM-band PCL.
                               # Reduce for DAB/DVB-T (higher bandwidth).

# ─── JIPDA Multi‑Target Tracker ──────────────────────────────────────────────
  jipda:
    P_D: 0.9                   # Probability of detection — expected fraction of
                               # epochs where a real target produces a detection.
                               0.9 = 90 % (one missed detection every 10 epochs).
    P_G: 0.999                 # Gate probability — fraction of true measurements
                               # expected to fall inside the association gate.
    gamma: 16.27               # Chi² gate threshold for 3 degrees of freedom at
                               # P_G = 0.999. Increase to widen the gate (accept
                               # noisier associations); decrease to tighten it.
    P_exist_threshold: 0.1     # Tracks with existence probability below this are
                               # automatically deleted. Lower = keep tracks longer
                               # through gaps; higher = faster deletion of ghosts.
    confirmation_epochs: 2     # Number of consecutive epochs a candidate must be
                               # seen before a confirmed track is created (M/N = 2/2).
    max_tracks: 20             # Hard cap on concurrent tracks. Prevents runaway
                               # track creation in high-clutter environments.

# ─── Non‑Cooperative Target Detection ────────────────────────────────────────
noncooperative:
  enabled: false               # Enable blind (ADS-B‑free) detection of targets
                               # that do NOT broadcast ADS-B. When true, the
                               # Geometric Associator + EKF + JIPDA pipeline runs
                               # alongside the existing ADS-B path. Non-cooperative
                               # targets appear on the map with a "Non-coop" label
                               # and a yellow marker colour.
  match_distance: 1000         # Metres — cross-reference threshold. A blind
                               # target whose localised position is within this
                               # distance of an ADS-B target is classified as
                               # cooperative (same aircraft). Targets farther away
                               # are flagged as non-cooperative.

# ─── Event Loop ──────────────────────────────────────────────────────────────
event:
  interval: 0.5        # Seconds between backend polling cycles. Default 1.0.
                        # Reduce to catch shorter‑lived detections (e.g. 0.5 for
                        # 2 Hz polling). Doubles HTTP load on radar nodes.

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
| `associate.geometric.threshold` | int | metres | Blind association intersection distance |
| `associate.geometric.nSamples` | int | — | Ellipse samples per detection for blind association |
| `associate.geometric.doppler_tolerance` | int | Hz | Doppler sign-consistency filter range |
| `associate.geometric.max_detections` | int | — | Per-radar clutter guard (skip epoch above this) |
| `tracker.ekf.process_noise_q` | float | m²/s³ | Process noise for EKF constant-velocity model |
| `tracker.ekf.measurement_noise_r` | float | m² | Bistatic range measurement variance |
| `tracker.jipda.P_D` | float | — | Probability of detection (0.0–1.0) |
| `tracker.jipda.P_G` | float | — | Gate probability (0.0–1.0) |
| `tracker.jipda.gamma` | float | — | Chi² gate threshold (3-DOF) |
| `tracker.jipda.P_exist_threshold` | float | — | Minimum existence probability for track deletion |
| `tracker.jipda.confirmation_epochs` | int | epochs | Consecutive hits needed for track initiation |
| `tracker.jipda.max_tracks` | int | — | Hard limit on concurrent tracks |
| `noncooperative.enabled` | bool | — | Enable blind (ADS-B‑free) target detection |
| `noncooperative.match_distance` | int | metres | Max distance to match blind target to ADS-B |
| `event.interval` | float | seconds | Backend polling cycle interval |

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

### Main Controls
| Control | Description |
|---------|-------------|
| **Radar servers** | Select which blah2 radar nodes to include (multi-select) |
| **Localisation** | Which algorithm to use for position fixing (see below) |
| **ADS-B** | Select the ADS-B truth server for association and map overlay |
| **Submit** | Start (or update) the processing request |

### Settings Popup (⚙️ Cog Icon, Top-Left)

Click the gear icon in the top-left corner of the map to open the settings panel. The panel
stays open until you click the gear again, allowing multiple adjustments without re-opening.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| **Altitude display** | Toggle button | metres | Switch altitude units between metres and feet. Updates all target labels and the colour legend bar. Preference is saved in your browser. |
| **Min radars for ellipsoids** | Number (1–10) | 3 | How many unique radars must have ellipsoid data before the bistatic surfaces are drawn on the map. Set to **1** to see single-radar ellipsoids; set to **3** (default) to match the localisation requirement. |
| **Ellipsoid fade time** | Seconds (0–60) | 0 | How long ellipsoid points stay on the map after their radar stops providing data. At **0** (default) points disappear immediately. Set to e.g. **5** to leave a fading trail that helps visualise historical detections. |
| **Localise cooperative targets** | Checkbox | ☑ checked | When unchecked, hides cooperative (ADS‑B‑matched) ellipsoids/ellipses and detection dots/labels. **Non‑cooperative targets are always shown** regardless of this toggle — they are radar-only detections with no ADS‑B match. |
| **Show cooperative targets** | Checkbox | ☑ checked | When unchecked, hides the raw ADS‑B truth overlay from tar1090 (aircraft positions, callsigns, and altitudes). Independent of localisation — you can show truth without localisation, or vice versa. |

Results update once per second. The map shows:
- **Coloured ellipses/ellipsoids**: the sampled bistatic surfaces for each radar (magenta/rose, per‑target hue)
- **Target markers**: localised positions — altitude-coloured for cooperative (ADS‑B‑matched) targets, yellow for non‑cooperative targets
- **ADS-B overlay**: truth positions from tar1090 for comparison (when "Show cooperative targets" is checked)
- **Non-cooperative targets**: appear with a "Non-coop" label and yellow marker when `noncooperative.enabled` is true. Their ellipsoids and detection dots are always visible regardless of the toggles above.

### Non‑Cooperative Target Visibility

Non‑cooperative targets are classified **server-side** in the event loop. The
`noncooperative.match_distance` config value (default **1000 metres**) controls
the threshold:

1. The Geometric Associator finds blind candidates from radar detections alone.
2. The JIPDA tracker estimates each candidate's ECEF position.
3. For each blind target, the nearest ADS‑B aircraft position is found in ECEF space.
4. If the distance is **greater than** `match_distance`, the target is classified as
   **non‑cooperative** — it has no matching ADS‑B aircraft. Its ellipsoids receive
   an `"nc_"` key prefix and it is always rendered on the map.

Targets within `match_distance` of an ADS‑B aircraft are classified as
**cooperative** (the same aircraft seen by both radar and ADS‑B). Their ellipsoids
and detection dots are controlled by the "Localise cooperative targets" toggle.

---

## API Reference

### Endpoint: `GET /api`

Trigger or poll a localisation request.

**Query parameters:**

| Parameter | Required | Example | Description |
|-----------|----------|---------|-------------|
| `server` | yes (repeat) | `server=radar1.example.com` | blah2 radar node URL. Repeat for each radar. |
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
    "aabbcc-radar1": [[51.1, -0.8, 0], [51.2, -0.7, 0], "..."],
    "nc_T1-radar1": [[51.3, -0.9, 500], [51.4, -0.8, 500], "..."]
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
| `detections_noncooperative` | object | (Optional) Non‑cooperative targets `[lat, lon, alt]` by track ID. Present only when `noncooperative.enabled` is true. |
| `ellipsoids` | object | Sampled ellipsoid points per target+radar. Cooperative targets use keys of the form `"hex‑radarName"`. Non‑cooperative targets (present only when `noncooperative.enabled` is true) use keys prefixed `"nc_"`: `"nc_synthId‑radarName"`. |
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

> **`SphericalIntersection` with < 3 pairs**: Detections with fewer than 3 associated pairs are now silently skipped (a `matrix_rank(S) < 3` guard returns no output for that target). Accuracy may still degrade for near-collinear node geometries — see TODO item **D1** for the remaining conditioning work.

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

If a radar node is unreachable (timeout or error), 3lips continues with the remaining available nodes. Localisation requires at least **3 nodes responding** for all methods. `SphericalIntersection` silently skips targets with fewer than 3 associated detections; accuracy may degrade for near-collinear geometries — see TODO item D1 for the remaining conditioning work.

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
1. **ADS-B dependency (mitigated)**: By default, association requires ADS-B truth via adsb2dd. Targets not broadcasting ADS-B (military, general aviation without transponder) are invisible. Enable `noncooperative.enabled: true` in `config.yml` to activate the blind Geometric Associator + EKF + JIPDA pipeline. Non‑cooperative targets then appear on the map with a "Non‑coop" label and yellow marker. Blind association requires ≥ 3 radars (ghost probability ≈ 6×10⁻⁶ per candidate at N=3).
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

Both services open `config/config.yml` relative to their working directory, and both import from `common/`.  The Docker setup provides these via volume mounts; for a bare-host run you need to make them available first:

```bash
# One-time setup — create symlinks so each service can find shared directories
ln -s "$(pwd)/config" api/config && ln -s "$(pwd)/common" api/common
ln -s "$(pwd)/config" event/config && ln -s "$(pwd)/common" event/common
```

```bash
# Terminal 1: API service
cd api
pip install -r requirements.txt
FLASK_APP=api.py flask run --port 5000

# Terminal 2: Event loop
cd event
pip install -r requirements.txt
python event.py
```

### Running tests

```bash
cd event
python3 -m unittest discover -s ../test/event/ -p "Test*.py" -v
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
│   │   ├── tracker/        # EKF + JIPDA multi‑target tracking
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