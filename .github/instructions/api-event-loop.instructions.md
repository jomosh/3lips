---
description: "Use when working on the Flask API, ZMQ messaging, API input validation, API output schema, or adding new localisation methods to the API layer in api/api.py and event/event.py."
applyTo: ["api/**/*.py", "event/event.py"]
---
# API and Event Loop Rules

## Input Validation
- All query parameters are validated against the `valid` dict in `api.py` before forwarding.
- Never trust raw query string values — always validate against the allowlist.
- New localisation methods must be added to **both** `localisations` list in `api.py` AND the `elif` chain in `event.py`.

## Output Schema (per API item)
```json
{
  "hash": "...",
  "server": ["radar1", "radar2"],
  "associator": "adsb-associator",
  "localisation": "ellipse-parametric-mean",
  "adsb": "adsb.server",
  "timestamp": 1234567890000,
  "timestamp_event": 1234567890000,
  "truth": { "hex": { "lat": ..., "lon": ..., "alt": ..., "flight": "..." } },
  "detections_associated": { "hex": [{ "radar": "...", "delay": ..., "doppler": ... }] },
  "detections_localised": { "hex": { "points": [[lat, lon, alt]] } },
  "ellipsoids": { "radar": [[lat, lon, alt], ...] },
  "time": 0.123
}
```

## Event Loop Lifecycle
1. Copy `api` list to avoid mutation during processing: `api_event = copy.copy(api)`.
2. Fetch all radar URLs first, then process — do not interleave fetch and compute.
3. Process each API item independently; do not share state between items in the same epoch.
4. Update `api` atomically at the end of the epoch.

## Adding a New Localisation Method
```python
# In api/api.py — add to localisations list:
{"name": "TDOA Least Squares", "id": "tdoa-least-squares"}

# In event/event.py — add elif branch:
elif item["localisation"] == "tdoa-least-squares":
    localisation = tdoaLeastSquares
```

## ZMQ Messaging
- The `Message` class wraps ZMQ push/pull. Do not bypass it for API↔event communication.
- Messages are URL-encoded query strings. Parse with `urllib.parse.unquote` and `split("=", 1)`.
