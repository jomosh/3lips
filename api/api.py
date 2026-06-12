"""
@file api.py
@brief API for 3lips.
@author 30hours
"""

from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import time
import asyncio
import yaml
import requests
import re
import json as json_lib


from common.Message import Message

app = Flask(__name__)

# init config file
try:
  with open('config/config.yml', 'r') as file:
      config = yaml.safe_load(file)
  radar_data = config['radar']
  map_data = config['map']
  config_data = config
except FileNotFoundError:
  print("Error: Configuration file not found.")
except yaml.YAMLError as e:
  print("Error reading YAML configuration:", e)

# store state data
servers = []
for radar in radar_data:
  if radar['name'] and radar['url']:
    servers.append({'name': radar['name'], 'url': radar['url']})

associators = [
  {"name": "ADSB Associator", "id": "adsb-associator"}
]

localisations = [
  {"name": "Ellipse Parametric (Mean)", "id": "ellipse-parametric-mean"},
  {"name": "Ellipse Parametric (Min)", "id": "ellipse-parametric-min"},
  {"name": "Ellipsoid Parametric (Mean)", "id": "ellipsoid-parametric-mean"},
  {"name": "Ellipsoid Parametric (Min)", "id": "ellipsoid-parametric-min"},
  {"name": "Spherical Intersection", "id": "spherical-intersection"}
]

adsbs = [
  {"name": map_data['tar1090'], "url": map_data['tar1090']},
  {"name": "None", "url": ""}
]

# store valid ids
valid = {}
valid['servers'] = [item['url'] for item in servers]
valid['associators'] = [item['id'] for item in associators]
valid['localisations'] = [item['id'] for item in localisations]
valid['adsbs'] = [item['url'] for item in adsbs]

# message received callback
async def callback_message_received(msg):
  print(f"Callback: Received message in main.py: {msg}", flush=True)

# init messaging
message_api_request = Message('event', 6969)

@app.route("/")
def index():
  return render_template("index.html", servers=servers, \
  associators=associators, localisations=localisations, adsbs=adsbs)

# serve static files from the /app/public folder
@app.route('/public/<path:file>')
def serve_static(file):
  base_dir = os.path.abspath(os.path.dirname(__file__))
  public_folder = os.path.join(base_dir, 'public')
  return send_from_directory(public_folder, file)

@app.route("/api")
def api():
  api = request.query_string.decode('utf-8')
  # input protection
  servers_api = request.args.getlist('server')
  associators_api = request.args.getlist('associator')
  localisations_api = request.args.getlist('localisation')
  adsbs_api = request.args.getlist('adsb')
  if not all(item in valid['servers'] for item in servers_api):
    return 'Invalid server'
  if not all(item in valid['associators'] for item in associators_api):
    return 'Invalid associator'
  if not all(item in valid['localisations'] for item in localisations_api):
    return 'Invalid localisation'
  if not all(item in valid['adsbs'] for item in adsbs_api):
    return 'Invalid ADSB'
  # send to event handler
  try:
    reply_chunks = message_api_request.send_message(api)
    reply = ''.join(reply_chunks)
    print(reply, flush=True)
    return reply
  except Exception as e:
    reply = "Exception: " + str(e)
    return jsonify(error=reply), 500

@app.route("/map/<path:file>")
def serve_map(file):
  base_dir = os.path.abspath(os.path.dirname(__file__))
  public_folder = os.path.join(base_dir, 'map')
  return send_from_directory(public_folder, file)

# output config file
@app.route('/config')
def config():
  return config_data

# helper function to determine if a host is on a private/local network
# RFC 1918: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
# RFC 4193: fc00::/7 (IPv6 unique local)
def _is_private_host(host):
  host_lower = host.lower()
  
  # Strip port if present
  if ':' in host_lower and host_lower.count(':') == 1:
    host_lower = host_lower.split(':')[0]

  # IPv6 local (loopback and link-local)
  if host_lower.startswith('['):
    host_lower = host_lower.strip('[]').split('%')[0]
  
  if host_lower in ('localhost', '::1', '127.0.0.1'):
    return True
    
  # IPv4 private ranges
  if host_lower.startswith('10.') or host_lower.startswith('127.'):
    return True
  if host_lower.startswith('192.168.'):
    return True
  if host_lower.startswith('172.'):
    # 172.16.0.0/12 → 172.16-31.x.x
    parts = host_lower.split('.')
    if len(parts) >= 2:
      try:
        second = int(parts[1])
        if 16 <= second <= 31:
          return True
      except ValueError:
        pass
        
  # IPv6 unique local fc00::/7 → fc00-fdff
  if host_lower.startswith('fc') or host_lower.startswith('fd'):
    return True
    
  return False

# helper function to perform secure, server-side HTTP/HTTPS requests with DNS/Connect timeouts
def fetch_proxied_url(host, path, preferred_scheme='http'):
  host = host.strip('/')
  path = path.lstrip('/')
  
  # For private network nodes, avoid SSL (no certificate authority on private IPs)
  if _is_private_host(host):
    schemes = ['http']
  else:
    # Public hosts: try preferred first, fall back to alternative
    schemes = [preferred_scheme, 'http' if preferred_scheme == 'https' else 'https']

  last_err = None
  for scheme in schemes:
    try:
      url = f"{scheme}://{host}/{path}"
      response = requests.get(url, timeout=(3.0, 3.0))
      response.raise_for_status()
      return response
    except requests.exceptions.RequestException as e:
      last_err = e
      # Fall back only for connection-level errors (not HTTP error responses)
      if scheme == 'https' and not getattr(e, 'response', None):
        continue
      break
  raise last_err


# proxy radar config to avoid direct browser-to-node requests
@app.route('/api/proxy/config')
def proxy_config():
  server = request.args.get('server')
  if not server:
    return jsonify(error="Missing server parameter"), 400
  
  # Sanitize input: only allow valid hostname characters
  if not re.match(r'^[a-zA-Z0-9.:-]+$', server):
    return jsonify(error="Invalid server format"), 400
    
  # Strict whitelist validation against allowed servers in config
  if server not in valid['servers']:
    return jsonify(error="Server not authorized"), 403
    
  try:
    # Try HTTPS fallback for public nodes, default to HTTP
    response = fetch_proxied_url(server, 'api/config', preferred_scheme='http')
    return jsonify(response.json())
  except ValueError as e:
    app.logger.error(f"Proxy error: non-JSON response from radar config {server}: {str(e)}")
    return jsonify(error="Invalid response from radar server"), 502
  except requests.exceptions.RequestException as e:
    app.logger.error(f"Proxy error fetching radar config from {server}: {str(e)}")
    return jsonify(error="Failed to proxy radar config request"), 502

# proxy adsb to avoid direct browser-to-node requests
@app.route('/api/proxy/adsb')
def proxy_adsb():
  url = request.args.get('url')
  if not url:
    return jsonify(error="Missing url parameter"), 400
    
  # Sanitize input: only allow valid hostname characters
  if not re.match(r'^[a-zA-Z0-9.:-]+$', url):
    return jsonify(error="Invalid URL format"), 400
    
  # Strict whitelist validation against allowed ADS-B servers in config
  if url not in valid['adsbs']:
    return jsonify(error="ADS-B server not authorized"), 403
    
  try:
    tar1090_https = config_data.get('map', {}).get('tar1090_https', False)
    preferred = 'https' if tar1090_https else 'http'
    response = fetch_proxied_url(url, 'data/aircraft.json', preferred_scheme=preferred)
    return jsonify(response.json())
  except ValueError as e:
    app.logger.error(f"Proxy error: non-JSON response from ADS-B {url}: {str(e)}")
    return jsonify(error="Invalid response from ADS-B server"), 502
  except requests.exceptions.RequestException as e:
    app.logger.error(f"Proxy error fetching ADS-B data from {url}: {str(e)}")
    return jsonify(error="Failed to proxy ADS-B request"), 502

if __name__ == "__main__":
  app.run()
