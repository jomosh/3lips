"""
@file AdsbAssociator.py
@author 30hours
"""

import asyncio
import aiohttp
import requests
import math

class AdsbAssociator:

  """
  @class AdsbAssociator
  @brief A class for associating detections of the same target.
  @details First associate ADS-B truth with each radar detection.
  Then associate over multiple radars.
  @see blah2 at https://github.com/jomosh/blah2.
  Uses truth data in delay-Doppler space from an adsb2dd server.
  @see adsb2dd at https://github.com/jomosh/adsb2dd.
  @todo Add adjustable window for associating truth/detections.
  """

  def __init__(self, adsb2dd_server, adsb2dd_https):

    """
    @brief Constructor for the AdsbAssociator class.
    """

    self.adsb2dd_server = adsb2dd_server
    self.adsb2dd_https = adsb2dd_https

  def process(self, radar_list, radar_data, timestamp):

    """
    @brief Associate detections from 2+ radars.
    @param radar_list (list): List of radars to associate.
    @param radar_data (dict): Radar data for list of radars.
    @param timestamp (int): Timestamp to compute delays at (ms).
    @return dict: Associated detections by [hex][radar].
    """

    assoc_detections = {}
    assoc_detections_radar = []

    for radar in radar_list:

      valid_config = radar_data[radar]["config"] is not None
      valid_detection = radar_data[radar]["detection"] is not None
      
      if valid_config and valid_detection:

        # get URL for adsb2truth
        url = self.generate_api_url(radar, radar_data[radar])

        # get ADSB detections
        try:
          response = requests.get(url, timeout=1)
          response.raise_for_status()
          data = response.json()
          adsb_detections = data
        except requests.exceptions.RequestException as e:
          print(f"Error fetching data from {url}: {e}")
          adsb_detections = None
          continue

        # associate radar and truth
        assoc_detections_radar.append(self.process_1_radar(
          radar, radar_data[radar]["detection"], 
          adsb_detections, timestamp, radar_data[radar]["config"]["capture"]["fc"]))

    # associate detections between radars
    output = {}
    for entry in assoc_detections_radar:
      for key, value in entry.items():
        if key not in output:
          output[key] = [value]
        else:
          output[key].append(value)
    #output = {key: values for key, values in output.items() if len(values) > 1}

    return output

  async def process_async(self, radar_list, radar_data, timestamp, session):
    """
    @brief Async variant: fires all per-radar adsb2dd HTTP calls concurrently
    via asyncio.gather, then runs process_1_radar() locally on each result.
    @param radar_list (list): List of radar names to associate.
    @param radar_data (dict): Radar data keyed by radar name.
    @param timestamp (int): Timestamp to compute delays at (ms).
    @param session (aiohttp.ClientSession): Shared session for connection reuse.
    @return dict: Associated detections by [hex][radar].
    """
    # Build (radar_name, url) pairs for all valid radars
    fetch_radars = []
    fetch_tasks = []

    for radar in radar_list:
      rd = radar_data.get(radar)
      if rd is None or rd["config"] is None or rd["detection"] is None:
        continue
      url = self.generate_api_url(radar, rd)
      fetch_radars.append(radar)
      fetch_tasks.append(self._fetch_adsb2dd(session, url))

    # Fire all adsb2dd HTTP calls concurrently
    results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

    # Local CPU-bound association per radar
    assoc_detections_radar = []
    for radar, result in zip(fetch_radars, results):
      if isinstance(result, Exception):
        print(f"Error fetching adsb2dd for {radar}: {result}")
        continue
      if result is None:
        continue
      rd = radar_data[radar]
      assoc_detections_radar.append(
        self.process_1_radar(
          radar, rd["detection"], result, timestamp,
          rd["config"]["capture"]["fc"]))

    # Merge per-radar results (same as synchronous process)
    output = {}
    for entry in assoc_detections_radar:
      for key, value in entry.items():
        if key not in output:
          output[key] = [value]
        else:
          output[key].append(value)

    return output

  async def _fetch_adsb2dd(self, session, url):
    """
    @brief Fetch JSON from adsb2dd endpoint. Returns None on failure.
    """
    try:
      async with session.get(url, timeout=aiohttp.ClientTimeout(total=1)) as resp:
        resp.raise_for_status()
        return await resp.json()
    except Exception as e:
      print(f"Error fetching {url}: {e}")
      return None

  def process_1_radar(self, radar, radar_detections, adsb_detections, timestamp, fc):

    """
    @brief Associate detections between 1 radar/truth pair.
    @details Output 1 detection per truth point.
    @param radar (str): Name of radar to process.
    @param radar_detections (dict): blah2 radar detections.
    @param adsb_detections (dict): adsb2dd truth detections.
    @return dict: Associated detections.
    """

    assoc_detections = {}
    distance_window = 10

    for aircraft in adsb_detections:

      if 'delay' in radar_detections:

        if 'delay' in adsb_detections[aircraft] and len(radar_detections['delay']) >= 1:

          # extrapolate delay to current time
          # TODO extrapolate Doppler too
          for i in range(len(radar_detections['delay'])):
            delta_t = (timestamp - radar_detections['timestamp'])/1000
            delay = (1000*radar_detections['delay'][i] + \
            (-radar_detections['doppler'][i]*(299792458/fc))*delta_t)/1000
            # Clamp to ≥0: a negative extrapolated delay means "closer
            # than the direct TX‑RX path", which is physically impossible.
            radar_detections['delay'][i] = max(0.0, delay)

          # distance from aircraft to all detections
          closest_point, distance = self.closest_point(
            adsb_detections[aircraft]['delay'], 
            adsb_detections[aircraft]['doppler'],
            radar_detections['delay'],
            radar_detections['doppler']
          )

          if distance < distance_window:

            assoc_detections[aircraft] = {
              'radar': radar,
              'delay': closest_point[0],
              'doppler': closest_point[1],
              'timestamp': adsb_detections[aircraft]['timestamp']
            }

    return assoc_detections

  def generate_api_url(self, radar, radar_data):

    """
    @brief Generate an adsb2dd API endpoint for each radar.
    @see adsb2dd at https://github.com/jomosh/adsb2dd.
    @param radar (str): Radar to run adsb2dd.
    @param radar_data (dict): Radar data for this radar.
    @return str: adsb2dd API for radar.
    """

    rx_lat = radar_data['config']['location']['rx']['latitude']
    rx_lon = radar_data['config']['location']['rx']['longitude']
    rx_alt = radar_data['config']['location']['rx']['altitude']
    tx_lat = radar_data['config']['location']['tx']['latitude']
    tx_lon = radar_data['config']['location']['tx']['longitude']
    tx_alt = radar_data['config']['location']['tx']['altitude']
    fc = radar_data['config']['capture']['fc']

    adsb = radar_data['config']['truth']['adsb']['tar1090']

    api_url = ('https' if self.adsb2dd_https else 'http') + '://' + self.adsb2dd_server + '/api/dd'

    api_query = (
      api_url +
      "?rx=" + str(rx_lat) + "," + 
      str(rx_lon) + "," + 
      str(rx_alt) +
      "&tx=" + str(tx_lat) + "," + 
      str(tx_lon) + "," + 
      str(tx_alt) +
      "&fc=" + str(fc/1000000) +
      "&server=" + "http://" + str(adsb)
    )

    return api_query

  def closest_point(self, x1, y1, x_coords, y_coords):

    x1, y1 = float(x1), float(y1)
    x_coords = [float(x) for x in x_coords]
    y_coords = [float(y) for y in y_coords]

    distances = [math.sqrt((x - x1)**2 + (y - y1)**2) for x, y in zip(x_coords, y_coords)]
    min_distance_index = distances.index(min(distances))
    
    closest_x = x_coords[min_distance_index]
    closest_y = y_coords[min_distance_index]
    distance = distances[min_distance_index]
    
    return [closest_x, closest_y], distance
