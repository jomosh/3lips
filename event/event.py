"""
@file event.py
@brief Event loop for 3lips.
@author 30hours
"""

import asyncio
import requests
import threading
import asyncio
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
    alt = round(alt)
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

  # get detections all radar
  radar_detections_url = [
    "http://" + radar_name + "/api/detection" for radar_name in radar_names]
  radar_detections = []
  for url in radar_detections_url:
    try:
      response = requests.get(url, timeout=1)
      response.raise_for_status()
      data = response.json()
      radar_detections.append(data)
    except requests.exceptions.RequestException as e:
      print(f"Error fetching data from {url}: {e}")
      radar_detections.append(None)

  # get config all radar
  radar_config_url = [
    "http://" + radar_name + "/api/config" for radar_name in radar_names]
  radar_config = []
  for url in radar_config_url:
    try:
      response = requests.get(url, timeout=1)
      response.raise_for_status()
      data = response.json()
      radar_config.append(data)
    except requests.exceptions.RequestException as e:
      print(f"Error fetching data from {url}: {e}")
      radar_config.append(None)

  # store detections in dict
  radar_dict = {}
  for i in range(len(radar_names)):
    radar_dict[radar_names[i]] = {
      "detection": radar_detections[i],
      "config": radar_config[i]
    }

  # store truth in dict
  truth_adsb = {}
  adsb_urls = []
  for item in api_event:
    adsb_urls.append(item["adsb"])
  adsb_urls = list(set(adsb_urls))
  for url in adsb_urls:
    truth_adsb[url] = adsbTruth.process(url, tar1090Https)

  # main processing
  for item in api_event:

    start_time = time.time()

    # extract dict for item
    radar_dict_item =  {
      key: radar_dict[key] 
      for key in item["server"] 
      if key in radar_dict
    }

    # Primary associator is always AdsbAssociator (ADS‑B truth).
    # GeometricAssociator runs as a parallel blind path when
    # noncooperative.enabled is true (see below).
    associator = adsbAssociator

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

    # processing
    associated_dets = associator.process(item["server"], radar_dict_item, timestamp)
    associated_dets_3_radars = {
      key: value
      for key, value in associated_dets.items()
      if isinstance(value, list) and len(value) >= 3
    }
    if associated_dets_3_radars:
      print('Detections from 3 or more radars availble.')
      print(associated_dets_3_radars)
    associated_dets_2_radars = {
      key: value
      for key, value in associated_dets.items()
      if isinstance(value, list) and len(value) >= 2
    }
    localised_dets = localisation.process(associated_dets_3_radars, radar_dict_item)

    # ---- Blind association + non-cooperative detection (F0+F1+C2+F3) -------
    # The Geometric Associator + JIPDA pipeline always runs alongside the
    # primary AdsbAssociator when noncooperative.enabled is true.  It finds
    # blind candidates from radar data alone, tracks them, and classifies
    # each as cooperative (near an ADS‑B target) or non‑cooperative (no
    # ADS‑B match).  Non‑cooperative targets get "nc_" prefixed keys in
    # the ellipsoids output and are always visible on the map regardless
    # of the "Localise cooperative targets" frontend toggle.
    detections_noncooperative = {}
    blind_candidates = {}
    if noncoopEnabled:
      # Run GeometricAssociator to find blind candidates
      blind_candidates = geometricAssociator.process(
        item["server"], radar_dict_item, timestamp)

      if blind_candidates:
        # Only run JIPDA with ≥3 radars — with 1-2 radars there is no
        # unique 3D fix, so detection dots would appear at misleading
        # TX-RX midpoint positions.  nc_ ellipsoids are still generated
        # below (they correctly show all possible target locations).
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
          # Skip tentative (unconfirmed) candidates
          if track_data.get('P_exist', 0) < 0.3:
            continue
          pts = track_data.get('points', [])
          if not pts:
            continue
          blind_ecef = Geometry.lla2ecef(pts[0][0], pts[0][1], pts[0][2])
          blind_ecef_arr = np.array(blind_ecef)

          # Find nearest ADS-B target
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

          # Non-cooperative if no ADS-B target within match_distance
          if nearest_dist > noncoopMatchDist:
            detections_noncooperative[track_id] = track_data

    # ---- Output non-cooperative detections --------------------------------
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
            # Compound key so each target gets its own set of ellipsoid points
            ellipsoids[key + "-" + radar["radar"]] = points

      # Also generate ellipsoids for blind (non-cooperative) targets
      if blind_candidates:
        for key in blind_candidates:
          for radar in blind_candidates[key]:
            # Only generate if radar config is available
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
            # Prefix "nc_" so blind-target ellipsoids don't collide with ADS-B keys
            ellipsoids["nc_" + key + "-" + radar["radar"]] = points

    stop_time = time.time()

    # output data to API
    item["timestamp_event"] = timestamp
    item["truth"] = truth_adsb[item["adsb"]]
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


# event loop
async def main():

  while True:
    await event()
    await asyncio.sleep(eventInterval)

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
