"""
@file event.py
@brief Event loop for 3lips.
@author 30hours
"""

import asyncio
import aiohttp
import math
import threading
import time
import copy
import json
import hashlib
import os
import yaml
from urllib.parse import unquote

import numpy as np

from algorithm.associator.AdsbAssociator import AdsbAssociator
from algorithm.associator.GeometricAssociator import GeometricAssociator
from algorithm.localisation.EllipseParametric import EllipseParametric
from algorithm.localisation.EllipsoidParametric import EllipsoidParametric
from algorithm.localisation.SphericalIntersection import SphericalIntersection
from algorithm.truth.AdsbTruth import AdsbTruth
from algorithm.tracker.EKFTracker import EKFTracker
from algorithm.tracker.JIPDATracker import JIPDATracker
from common.Message import Message
from data.Ellipsoid import Ellipsoid
from algorithm.geometry.Geometry import Geometry

# init config file
try:
  with open('config/config.yml', 'r') as file:
    config = yaml.safe_load(file)
  nSamplesEllipse = config['localisation']['ellipse']['nSamples']
  thresholdEllipse = config['localisation']['ellipse']['threshold']
  nDisplayEllipse = config['localisation']['ellipse']['nDisplay']
  nSamplesEllipsoid = config['localisation']['ellipsoid']['nSamples']
  thresholdEllipsoid = config['localisation']['ellipsoid']['threshold']
  nDisplayEllipsoid = config['localisation']['ellipsoid']['nDisplay']
  tDeleteAdsb = config['associate']['adsb']['tDelete']
  adsb2ddServer = config['associate']['adsb']['adsb2dd']
  adsb2ddHttps = config['associate']['adsb']['adsb2dd_https']
  save = config['3lips']['save']
  tDelete = config['3lips']['tDelete']
  saveRetentionHours = config.get('3lips', {}).get('save_retention_hours', 24)
  tar1090Https = config['map']['tar1090_https']
  eventInterval = config.get('event', {}).get('interval', 1.0)
  geometricConfig = config.get('associate', {}).get('geometric', {})
  ekfConfig = config.get('tracker', {}).get('ekf', {})
  jipdaConfig = config.get('tracker', {}).get('jipda', {})
  noncoopEnabled = config.get('noncooperative', {}).get('enabled', False)
  noncoopMatchDist = config.get('noncooperative', {}).get('match_distance', 1000)
except FileNotFoundError:
  print("Error: Configuration file not found.")
except yaml.YAMLError as e:
  print("Error reading YAML configuration:", e)
except KeyError as e:
  print(f"Error: Missing configuration key: {e}")

# init event loop
api = []

# init config
tDelete = tDelete
adsbAssociator = AdsbAssociator(adsb2ddServer, adsb2ddHttps)
ellipseParametricMean = EllipseParametric("mean", nSamplesEllipse, thresholdEllipse)
ellipseParametricMin = EllipseParametric("min", nSamplesEllipse, thresholdEllipse)
ellipsoidParametricMean = EllipsoidParametric("mean", nSamplesEllipsoid, thresholdEllipsoid)
ellipsoidParametricMin = EllipsoidParametric("min", nSamplesEllipsoid, thresholdEllipsoid)
sphericalIntersection = SphericalIntersection()
adsbTruth = AdsbTruth(tDeleteAdsb)
geometricAssociator = GeometricAssociator(geometricConfig)
ekf = EKFTracker(ekfConfig)
jipda = JIPDATracker(ekf, jipdaConfig)
saveFile = '/app/save/' + str(int(time.time())) + '.ndjson'

# ---- Radar config cache ----
_radar_config_cache = {}          # {radar_name: config_dict or None}
_radar_config_cache_lock = asyncio.Lock()
_CONFIG_REFRESH_INTERVAL = 60     # seconds between background config refreshes

# Long-lived aiohttp session (set by main())
_session = None


async def _fetch_json(url, timeout=1.0):
  """Fetch JSON from a URL using the shared session. Returns None on failure."""
  global _session
  try:
    async with _session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
      resp.raise_for_status()
      return await resp.json()
  except Exception as e:
    print(f"Error fetching {url}: {e}")
    return None


async def _get_radar_configs(radar_names):
  """Return cached configs for the given radar names.
  Fetches on cache miss. All missing radars fetched concurrently.
  Thread-safe via asyncio.Lock."""
  # Determine which radars need fetching
  missing = [n for n in radar_names
             if n not in _radar_config_cache
             or _radar_config_cache[n] is None]

  if missing:
    tasks = [_fetch_json(f"http://{name}/api/config") for name in missing]
    results = await asyncio.gather(*tasks)
    async with _radar_config_cache_lock:
      for name, result in zip(missing, results):
        # Only cache successful fetches — None on failure so the next
        # epoch retries.  Storing None would poison the cache until the
        # background refresh runs (up to 60 s later).
        if result is not None:
          _radar_config_cache[name] = result

  return {name: _radar_config_cache.get(name) for name in radar_names}


async def _background_config_refresh():
  """Periodically refresh all cached radar configs (handles radar restarts)."""
  while True:
    await asyncio.sleep(_CONFIG_REFRESH_INTERVAL)
    async with _radar_config_cache_lock:
      names = list(_radar_config_cache.keys())
    if not names:
      continue
    tasks = [_fetch_json(f"http://{name}/api/config") for name in names]
    results = await asyncio.gather(*tasks)
    async with _radar_config_cache_lock:
      for name, result in zip(names, results):
        if result is not None:
          _radar_config_cache[name] = result


def _sample_and_convert_ellipsoid(radar_config, radar_name, delay,
                                   localisation, n_display):
  """Sample an ellipsoid at the given bistatic delay and return
  display-ready LLA points.

  Shared by ADS-B and blind-target ellipsoid rendering so the
  per-radar coordinate transforms and rounding logic are not
  duplicated.

  Args:
      radar_config (dict): 'config' block from a radar in
          radar_dict_item.
      radar_name (str): Radar name for the Ellipsoid object.
      delay (float): Bistatic delay in seconds.
      localisation: Localisation instance (must have .sample()).
      n_display (int): Number of display sample points.

  Returns:
      list: [[lat, lon, alt], ...] with lat/lon rounded to 3
          decimal places and altitude rounded to integer metres.
  """
  from algorithm.geometry.Geometry import Geometry
  from data.Ellipsoid import Ellipsoid

  x_tx, y_tx, z_tx = Geometry.lla2ecef(
    radar_config['location']['tx']['latitude'],
    radar_config['location']['tx']['longitude'],
    radar_config['location']['tx']['altitude'])
  x_rx, y_rx, z_rx = Geometry.lla2ecef(
    radar_config['location']['rx']['latitude'],
    radar_config['location']['rx']['longitude'],
    radar_config['location']['rx']['altitude'])
  ellipsoid = Ellipsoid(
    [x_tx, y_tx, z_tx],
    [x_rx, y_rx, z_rx],
    radar_name)
  points = localisation.sample(ellipsoid, delay * 1000, n_display)
  for i in range(len(points)):
    lat, lon, alt = Geometry.ecef2lla(points[i][0], points[i][1], points[i][2])
    alt = round(alt) if not (math.isnan(alt) or math.isinf(alt)) else 0
    points[i] = ([round(lat, 3), round(lon, 3), alt])
  return points


async def event():

  print('Start event', flush=True)

  global api, save
  timestamp = int(time.time()*1000)
  api_event = copy.copy(api)

  # list all blah2 radars
  radar_names = []
  for item in api_event:
    for radar in item["server"]:
      radar_names.append(radar)
  radar_names = list(set(radar_names))

  # collect unique ADS-B truth URLs
  adsb_urls = list(set(item["adsb"] for item in api_event))

  # ---- Phase 1: Concurrent I/O (detections + configs + ADS-B truth) ----
  detection_results = await asyncio.gather(*[
    _fetch_json(f"http://{name}/api/detection") for name in radar_names
  ])
  config_results = await _get_radar_configs(radar_names)
  truth_results = await asyncio.gather(*[
    adsbTruth.process_async(url, tar1090Https, _session)
    for url in adsb_urls
  ])

  # Build radar_dict from Phase 1 results
  radar_dict = {}
  for i, name in enumerate(radar_names):
    radar_dict[name] = {
      "detection": detection_results[i],
      "config": config_results.get(name)
    }

  truth_adsb = dict(zip(adsb_urls, truth_results))

  # Diagnostic: log what each radar returned
  status_parts = []
  for name in radar_names:
    rd = radar_dict[name]
    det_ok = "OK" if rd["detection"] is not None else "None"
    cfg_ok = "OK" if rd["config"] is not None else "None"
    status_parts.append(f"{name} detection={det_ok} config={cfg_ok}")
  print("Radar data: " + ", ".join(status_parts), flush=True)

  # ---- Phase 2: adsb2dd association (concurrent per radar internally) ----
  adsb_associated = await adsbAssociator.process_async(
    radar_names, radar_dict, timestamp, _session)

  # ---- Processing (unchanged logic, now with ADS-B fallback) ----
  for item in api_event:

    start_time = time.time()

    # extract dict for item
    radar_dict_item = {
      key: radar_dict[key]
      for key in item["server"]
      if key in radar_dict
    }

    # localisation selection
    if item["localisation"] == "ellipse-parametric-mean":
      localisation = ellipseParametricMean
    elif item["localisation"] == "ellipse-parametric-min":
      localisation = ellipseParametricMin
    elif item["localisation"] == "ellipsoid-parametric-mean":
      localisation = ellipsoidParametricMean
    elif item["localisation"] == "ellipsoid-parametric-min":
      localisation = ellipsoidParametricMin
    elif item["localisation"] == "spherical-intersection":
      localisation = sphericalIntersection
    else:
      print("Error: Localisation invalid.")
      return

    # Filter ADS-B associations to only include radars in this item.
    # adsb_associated is keyed by hex, with values [{radar, delay, doppler}, ...].
    associated_dets = {}
    for hex_key, det_list in adsb_associated.items():
      filtered = [d for d in det_list if d["radar"] in item["server"]]
      if filtered:
        associated_dets[hex_key] = filtered

    # Check whether any radars in this item have valid detection data.
    # If all detection fetches failed, no associator can produce output.
    radars_with_data = sum(
      1 for rn in item["server"]
      if rn in radar_dict_item
      and radar_dict_item[rn]["detection"] is not None
      and radar_dict_item[rn]["config"] is not None
    )
    if radars_with_data == 0:
      print(
        f"WARNING: No radar detection data available for {item['server']} — "
        "check radar connectivity (see 'Radar data:' log above)",
        flush=True)

    # If ADS-B produced nothing (tar1090/adsb2dd down), fall back to
    # GeometricAssociator as the primary associator.
    if not associated_dets:
      print(
        "ADS-B association returned no results — "
        "falling back to GeometricAssociator",
        flush=True)
      associated_dets = geometricAssociator.process(
        item["server"], radar_dict_item, timestamp)

    associated_dets_3_radars = {
      key: value
      for key, value in associated_dets.items()
      if isinstance(value, list) and len(value) >= 3
    }
    if associated_dets_3_radars:
      print('Detections from 3 or more radars availble.')
      print(associated_dets_3_radars)

    localised_dets = localisation.process(associated_dets_3_radars, radar_dict_item)

    # ---- Blind association + non-cooperative detection (F0+F1+C2+F3) -------
    detections_noncooperative = {}
    blind_candidates = {}
    if noncoopEnabled:
      # Run GeometricAssociator to find blind candidates
      blind_candidates = geometricAssociator.process(
        item["server"], radar_dict_item, timestamp)

      if blind_candidates:
        n_radars_available = sum(
          1 for rn in item["server"]
          if rn in radar_dict_item
          and radar_dict_item[rn] is not None
          and radar_dict_item[rn].get("config") is not None
          and radar_dict_item[rn].get("detection") is not None
          and radar_dict_item[rn]["detection"].get("delay")
        )
        if n_radars_available >= 3:
          tracked_blind = jipda.process(
            blind_candidates, radar_dict_item, timestamp)
        else:
          tracked_blind = {}

        # Cross-reference: classify blind targets vs ADS-B targets
        for track_id, track_data in tracked_blind.items():
          if track_data.get('P_exist', 0) < 0.3:
            continue
          pts = track_data.get('points', [])
          if not pts:
            continue
          blind_ecef = Geometry.lla2ecef(pts[0][0], pts[0][1], pts[0][2])
          blind_ecef_arr = np.array(blind_ecef)

          nearest_dist = float('inf')
          for hex_key, loc_data in localised_dets.items():
            adsb_pts = loc_data.get('points', [])
            if not adsb_pts:
              continue
            adsb_ecef = Geometry.lla2ecef(
              adsb_pts[0][0], adsb_pts[0][1], adsb_pts[0][2])
            dist = np.linalg.norm(blind_ecef_arr - np.array(adsb_ecef))
            if dist < nearest_dist:
              nearest_dist = dist

          if nearest_dist > noncoopMatchDist:
            detections_noncooperative[track_id] = track_data

    item["detections_noncooperative"] = detections_noncooperative

    if associated_dets:
      print(associated_dets, flush=True)

    # show ellipsoids of associated detections for all targets
    ellipsoids = {}
    if item["localisation"] == "ellipse-parametric-mean" or \
    item["localisation"] == "ellipsoid-parametric-mean" or \
    item["localisation"] == "ellipse-parametric-min" or \
    item["localisation"] == "ellipsoid-parametric-min":
      if associated_dets:
        for key in associated_dets:
          for radar in associated_dets[key]:
            cfg = radar_dict_item[radar["radar"]]["config"]
            points = _sample_and_convert_ellipsoid(
              cfg, radar["radar"], radar["delay"],
              localisation, nDisplayEllipse)
            if item["localisation"] == "ellipse-parametric-mean" or \
            item["localisation"] == "ellipse-parametric-min":
              for pt in points:
                pt[2] = 0
            ellipsoids[key + "-" + radar["radar"]] = points

      # Also generate ellipsoids for blind (non-cooperative) targets
      if blind_candidates:
        for key in blind_candidates:
          for radar in blind_candidates[key]:
            if radar["radar"] not in radar_dict_item:
              continue
            if radar_dict_item[radar["radar"]] is None:
              continue
            cfg = radar_dict_item[radar["radar"]].get("config")
            if cfg is None:
              continue
            points = _sample_and_convert_ellipsoid(
              cfg, radar["radar"], radar["delay"],
              localisation, nDisplayEllipse)
            if item["localisation"] == "ellipse-parametric-mean" or \
            item["localisation"] == "ellipse-parametric-min":
              for pt in points:
                pt[2] = 0
            ellipsoids["nc_" + key + "-" + radar["radar"]] = points

    stop_time = time.time()

    # output data to API
    item["timestamp_event"] = timestamp
    item["truth"] = truth_adsb.get(item["adsb"], {})
    item["detections_associated"] = associated_dets
    item["detections_localised"] = localised_dets
    item["ellipsoids"] = ellipsoids
    item["time"] = stop_time - start_time

    print('Method: ' + item["localisation"], flush=True)
    print(item["time"], flush=True)

  # delete old API requests
  api_event = [
    item for item in api_event if timestamp - item["timestamp"] <= tDelete*1000]

  # update API
  api = api_event

  # save to file
  if save:
    append_api_to_file(api)
    _cleanup_save_files('/app/save', saveRetentionHours)


# event loop
async def main():
  global _session

  # Create long-lived aiohttp session with connection pooling
  connector = aiohttp.TCPConnector(
    limit=20,             # max concurrent connections
    limit_per_host=5,     # max per host
    ttl_dns_cache=300,    # DNS cache TTL (5 minutes)
    force_close=False,    # allow keep-alive
  )
  timeout = aiohttp.ClientTimeout(total=5, connect=1)

  async with aiohttp.ClientSession(
    connector=connector,
    timeout=timeout
  ) as session:
    _session = session

    # Start background config refresh
    asyncio.create_task(_background_config_refresh())

    while True:
      await event()
      await asyncio.sleep(eventInterval)

def _cleanup_save_files(save_dir, retention_hours):
  """Delete .ndjson files older than retention_hours from save_dir."""
  if retention_hours <= 0:
    return
  try:
    cutoff = time.time() - retention_hours * 3600
    for fname in os.listdir(save_dir):
      if not fname.endswith('.ndjson'):
        continue
      fpath = os.path.join(save_dir, fname)
      try:
        if os.path.getmtime(fpath) < cutoff:
          os.remove(fpath)
          print(f"Cleaned up old save file: {fname}")
      except OSError:
        pass
  except OSError:
    pass

def append_api_to_file(api_object, filename=saveFile):

  if not os.path.exists(filename):
    with open(filename, 'w') as new_file:
      pass

  with open(filename, 'a') as json_file:
    json.dump(api_object, json_file)
    json_file.write('\n')

def short_hash(input_string, length=10):

  hash_object = hashlib.sha256(input_string.encode())
  short_hash = hash_object.hexdigest()[:length]
  return short_hash

# message received callback
async def callback_message_received(msg):

  timestamp = int(time.time()*1000)

  # update timestamp if API entry exists
  for x in api:
    if x["hash"] == short_hash(msg):
      x["timestamp"] = timestamp
      break

  # add API entry if does not exist, split URL
  if not any(x.get("hash") == short_hash(msg) for x in api):
    api.append({})
    api[-1]["hash"] = short_hash(msg)
    url_parts = msg.split("&")
    for part in url_parts:
      key, value = unquote(part).split("=", 1)
      if key in api[-1]:
        if not isinstance(api[-1][key], list):
          api[-1][key] = [api[-1][key]]
        api[-1][key].append(value)
      else:
        api[-1][key] = value
    api[-1]["timestamp"] = timestamp
    if not isinstance(api[-1]["server"], list):
      api[-1]["server"] = [api[-1]["server"]]

  # json dump
  for item in api:
    if item["hash"] == short_hash(msg):
      output = json.dumps(item)
      break

  return output

# init messaging
# Bind to 0.0.0.0 so the listener accepts connections from the Docker
# internal network (where the api container connects via 'event:6969').
# Port 6969 is not published to the host in docker-compose.yml, so
# external access is blocked by the Docker network layer.
message_api_request = Message('0.0.0.0', 6969)
message_api_request.set_callback_message_received(callback_message_received)

if __name__ == "__main__":
  threading.Thread(target=message_api_request.start_listener).start()
  asyncio.run(main())
