"""
@file api.py
@brief API for 3lips.
@author 30hours
"""

from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import sys
import time
import asyncio
import uuid
import yaml
import requests
import socket
import urllib.parse
import threading
import concurrent.futures
from collections import defaultdict

from common.Message import Message

# Module-level constants — override via environment variable, e.g. PROXY_TIMEOUT=5.0
_PROXY_TIMEOUT_DEFAULT = (3.0, 3.0)

def _get_proxy_timeout() -> tuple:
  """Read proxy timeout from environment or fall back to default."""
  raw = os.environ.get('PROXY_TIMEOUT')
  if raw is not None:
    try:
      val = float(raw)
      return (val, val)
    except ValueError:
      pass
  return _PROXY_TIMEOUT_DEFAULT

_PROXY_TIMEOUT = _get_proxy_timeout()

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

# Simple in-memory rate limiter for proxy endpoints
# ---------------------------------------------------------------------------
# Override defaults via environment: RATE_LIMIT_WINDOW=120 RATE_LIMIT_MAX=60
_RATE_LIMIT_WINDOW = int(os.environ.get('RATE_LIMIT_WINDOW', '60'))
_RATE_LIMIT_MAX = int(os.environ.get('RATE_LIMIT_MAX', '30'))
_rate_limit_store: dict = defaultdict(list)
_rate_limit_lock = threading.Lock()

def _check_rate_limit(client_ip: str) -> bool:
  """Return True if the client is *under* the rate limit (allowed to proceed)."""
  now = time.time()
  window_start = now - _RATE_LIMIT_WINDOW
  with _rate_limit_lock:
    # Prune old entries
    _rate_limit_store[client_ip] = [
      ts for ts in _rate_limit_store[client_ip] if ts > window_start
    ]
    if len(_rate_limit_store[client_ip]) >= _RATE_LIMIT_MAX:
      return False
    _rate_limit_store[client_ip].append(now)
    return True


# ---------------------------------------------------------------------------
# Client IP detection with reverse-proxy awareness
# ---------------------------------------------------------------------------
# In the default Docker deployment there is no reverse proxy, so
# request.remote_addr is correct.  Set TRUSTED_PROXY to the proxy's IP
# (e.g. "172.20.0.1") to activate X-Forwarded-For support.
_TRUSTED_PROXY = os.environ.get('TRUSTED_PROXY')

def _get_client_ip() -> str:
  """Return the originating client IP, respecting a trusted reverse proxy."""
  if _TRUSTED_PROXY and request.remote_addr == _TRUSTED_PROXY:
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
      return forwarded.split(',')[0].strip()
  return request.remote_addr or 'unknown'


# ---------------------------------------------------------------------------
# Private-IP detection and DNS-resolved proxying
# ---------------------------------------------------------------------------
# Custom exception for DNS resolution errors that should be surfaced to callers
class DnsResolutionError(Exception):
  """Raised when DNS resolution fails temporarily (not NXDOMAIN)."""
  pass


# DNS rebinding / TOCTOU mitigation strategy:
#   1. Resolve the hostname to all its IPs via getaddrinfo.
#   2. Classify each resolved IP as private or public.
#   3. If ANY resolved IP is private, treat the host as private and
#      connect using the resolved IP (not the hostname), which prevents
#      a second DNS lookup and closes the TOCTOU window.
#   4. If ALL resolved IPs are public, still connect using the FIRST
#      resolved IP and set the Host header to the original hostname.
#      This avoids a second DNS lookup that could return a different IP.
#   5. The Host header ensures virtual-host routing still works.
#
# RFC 1918: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
# RFC 6598: 100.64.0.0/10 (Carrier-grade NAT)
# RFC 4291: fe80::/10 (IPv6 link-local)
# RFC 4193: fc00::/7  (IPv6 unique local)


def _is_private_ip(ip: str) -> bool:
  """Check a resolved IP address against private/local ranges.

  Args:
    ip: A string representation of an IPv4 or IPv6 address.

  Returns:
    True if the IP falls within any private, loopback, link-local,
    unique-local, or carrier-grade-NAT range.
  """
  # Unspecified / "any" addresses — connecting would bind to all interfaces
  if ip in ('0.0.0.0', '::'):
    return True

  # Loopback
  if ip == '::1':
    return True
  if ip.startswith('127.'):
    return True

  # IPv4 private ranges (RFC 1918)
  if ip.startswith('10.'):
    return True
  if ip.startswith('192.168.'):
    return True
  if ip.startswith('172.'):
    parts = ip.split('.')
    if len(parts) >= 2:
      try:
        second = int(parts[1])
        if 16 <= second <= 31:
          return True
      except ValueError:
        pass

  # Carrier-grade NAT (RFC 6598: 100.64.0.0/10 → 100.64–127.x.x)
  if ip.startswith('100.'):
    parts = ip.split('.')
    if len(parts) >= 2:
      try:
        second = int(parts[1])
        if 64 <= second <= 127:
          return True
      except ValueError:
        pass

  # Link-local / APIPA (RFC 3927: 169.254.0.0/16)
  if ip.startswith('169.254.'):
    return True

  # IPv6 unique local (RFC 4193: fc00::/7 → fc00–fdff)
  if ip.startswith('fc') or ip.startswith('fd'):
    return True
  # IPv6 link-local (RFC 4291: fe80::/10 → fe80:0000 to febf:ffff)
  if ip[:3] in ('fe8', 'fe9', 'fea', 'feb'):
    return True

  return False


# DNS resolution timeout (seconds) — override via DNS_TIMEOUT env var
_DNS_TIMEOUT = float(os.environ.get('DNS_TIMEOUT', '3.0'))

def _resolve_with_timeout(hostname: str, port):
  """Resolve hostname with a timeout using a thread-pool executor.

  socket.getaddrinfo has no built-in timeout; a slow DNS server would
  block the calling thread indefinitely.  This wrapper offloads the
  call to a single-worker thread pool and enforces a timeout, raising
  socket.timeout if the resolution takes too long.
  """
  with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
    future = executor.submit(socket.getaddrinfo, hostname, port or None)
    try:
      return future.result(timeout=_DNS_TIMEOUT)
    except concurrent.futures.TimeoutError:
      raise socket.timeout(f"DNS resolution timed out after {_DNS_TIMEOUT}s")


def _resolve_and_classify(host: str) -> tuple[bool, str]:
  """Resolve hostname to IPs and classify as private or public.

  Performs DNS resolution once and returns the *resolved IP address*
  for use in the actual HTTP request.  This closes the TOCTOU window
  between the private-IP check and the outbound connection because
  ``requests`` is given a literal IP rather than a hostname that would
  trigger a second DNS lookup.

  Args:
    host: A hostname, optionally with port (``example.com:8080``) or
      brackets for IPv6 (``[::1]:8080``).

  Returns:
    (is_private, target) tuple where ``target`` is the resolved IP
    address formatted for use in a URL (bracketed if IPv6, with port
    appended if one was supplied).  If DNS resolution fails permanently
    (NXDOMAIN), returns ``(True, hostname)`` — a fail-closed posture.

  Raises:
    DnsResolutionError: if DNS resolution fails transiently (timeout, SERVFAIL).
  """
  # Extract hostname and optional port using urllib.parse
  if '://' not in host:
    host = '//' + host
  parsed = urllib.parse.urlparse(host)
  hostname = parsed.hostname if parsed.hostname else host
  try:
    port = parsed.port
  except ValueError:
    # urlparse can mis-parse bare IPv6 addresses (e.g. "://::1"
    # where ":1" is treated as a port).  Fall back to manual split.
    hostname = hostname or host
    port = None

  # Quick return for localhost / loopback
  if hostname.lower() in ('localhost', '::1', '127.0.0.1', '127.0.1.1'):
    return True, hostname

  # Resolve hostname to IP addresses (with timeout to avoid blocking)
  try:
    addrinfo = _resolve_with_timeout(hostname, port)
    ips = [info[4][0] for info in addrinfo]
  except socket.gaierror as e:
    app.logger.error(f"DNS resolution failed for {hostname}: {str(e)}")
    # Distinguish permanent NXDOMAIN (safe fail-closed) from transient errors
    errno = getattr(e, 'errno', None)
    if errno == socket.EAI_NONAME:
      return True, hostname  # NXDOMAIN — safe to block
    raise DnsResolutionError(
      f"DNS temporarily unavailable for {hostname}: {str(e)}") from e

  if not ips:
    app.logger.error(f"DNS returned no addresses for {hostname}")
    return True, hostname

  # Check if ANY resolved IP is private
  is_private = any(_is_private_ip(ip) for ip in ips)

  # Use the first resolved IP for the actual request.
  # By passing a literal IP to requests.get() we avoid a second DNS
  # lookup, fully closing the TOCTOU window between check and connect.
  resolved_ip = ips[0]

  # Format for URL: bracket IPv6 addresses when a port is present
  # (RFC 3986 §3.2.2)
  if ':' in resolved_ip and port:
    target = f"[{resolved_ip}]:{port}"
  elif port:
    target = f"{resolved_ip}:{port}"
  elif ':' in resolved_ip:
    target = f"[{resolved_ip}]"
  else:
    target = resolved_ip

  return is_private, target


def fetch_proxied_url(host: str, path: str,
                      preferred_scheme: str = 'http') -> 'requests.Response':
  """Perform a secure, server-side HTTP/HTTPS request.

  All outgoing proxy traffic goes through this single function.
  DNS is resolved once and the resolved IP is used in the request URL,
  eliminating DNS rebinding and TOCTOU vulnerabilities.

  Args:
    host: Hostname (with optional port), e.g. ``"radar.local:8080"``.
    path: URL path, e.g. ``"api/config"``.
    preferred_scheme: ``"http"`` or ``"https"`` to try first.

  Returns:
    A ``requests.Response`` object.

  Raises:
    requests.exceptions.RequestException: If all schemes fail.
  """
  host = host.strip('/')
  path = path.lstrip('/')

  # Resolve once — target_host is now a literal IP address.
  is_private, target_host = _resolve_and_classify(host)
  original_hostname = host  # preserve for Host header

  if is_private:
    schemes = ['http']
  else:
    schemes = [preferred_scheme,
               'http' if preferred_scheme == 'https' else 'https']

  last_err = None
  for scheme in schemes:
    try:
      url = f"{scheme}://{target_host}/{path}"
      headers = {'Host': original_hostname}
      response = requests.get(url, timeout=_PROXY_TIMEOUT, headers=headers)
      response.raise_for_status()
      return response
    except requests.exceptions.RequestException as e:
      last_err = e
      # Fall back only for connection-level errors (not HTTP error responses).
      if scheme == 'https' and not getattr(e, 'response', None):
        continue
      break
  raise last_err


# ---------------------------------------------------------------------------
# Proxy endpoints
# ---------------------------------------------------------------------------

def _make_proxy_error(correlation_id: str, msg: str, status: int) -> tuple:
  """Build a generic error response with a correlation ID for debugging."""
  return jsonify(error=msg, correlation_id=correlation_id), status


def _handle_proxy_errors(correlation_id: str, endpoint: str,
                         url: str, fetch_func, **fetch_kwargs):
  """Shared error handling for proxy endpoints.

  Calls ``fetch_func(**fetch_kwargs)`` and returns a Flask response
  tuple.  Catches DnsResolutionError, ValueError (non-JSON), and
  RequestException with consistent logging and error messages.

  Args:
    correlation_id: Short UUID for log correlation.
    endpoint: Human-readable endpoint label for log messages.
    url: The upstream URL being proxied (for log messages).
    fetch_func: Callable that returns a ``requests.Response``.
    **fetch_kwargs: Passed to ``fetch_func``.

  Returns:
    A tuple ``(flask.Response, int)`` suitable for Flask route return.
  """
  try:
    response = fetch_func(**fetch_kwargs)
    return jsonify(response.json())
  except DnsResolutionError as e:
    app.logger.error(
      f"[{correlation_id}] DNS error for {endpoint} {url}: {str(e)}")
    return _make_proxy_error(correlation_id,
                             "DNS temporarily unavailable", 502)
  except ValueError as e:
    app.logger.error(
      f"[{correlation_id}] Proxy error: non-JSON response "
      f"from {endpoint} {url}: {str(e)}")
    return _make_proxy_error(correlation_id, "Failed to proxy request", 502)
  except requests.exceptions.RequestException as e:
    app.logger.error(
      f"[{correlation_id}] Proxy error fetching {endpoint} "
      f"from {url}: {str(e)}")
    return _make_proxy_error(correlation_id, "Failed to proxy request", 502)


@app.route('/api/proxy/config')
def proxy_config():
  """Proxy radar /api/config endpoints to avoid direct browser-to-node requests."""
  correlation_id = str(uuid.uuid4())[:8]

  # Rate limiting
  client_ip = _get_client_ip()
  if not _check_rate_limit(client_ip):
    app.logger.warning(f"[{correlation_id}] Rate limit exceeded for {client_ip}")
    return _make_proxy_error(correlation_id, "Too many requests", 429)

  server = request.args.get('server')
  if not server:
    return _make_proxy_error(correlation_id, "Missing server parameter", 400)

  # Validate input: extract hostname via urllib.parse for robust parsing
  parsed = urllib.parse.urlparse('//' + server)
  if not parsed.hostname:
    return _make_proxy_error(correlation_id, "Invalid server format", 400)

  # Strict whitelist validation against allowed servers in config
  if server not in valid['servers']:
    app.logger.warning(f"[{correlation_id}] Unauthorized server: {server}")
    return _make_proxy_error(correlation_id, "Server not authorized", 403)

  return _handle_proxy_errors(
    correlation_id, "radar config", server,
    fetch_proxied_url, host=server, path='api/config',
    preferred_scheme='http')


@app.route('/api/proxy/adsb')
def proxy_adsb():
  """Proxy ADS-B data endpoints to avoid direct browser-to-node requests."""
  correlation_id = str(uuid.uuid4())[:8]

  # Rate limiting
  client_ip = _get_client_ip()
  if not _check_rate_limit(client_ip):
    app.logger.warning(f"[{correlation_id}] Rate limit exceeded for {client_ip}")
    return _make_proxy_error(correlation_id, "Too many requests", 429)

  url = request.args.get('url')
  if not url:
    return _make_proxy_error(correlation_id, "Missing url parameter", 400)

  # Validate input: extract hostname via urllib.parse for robust parsing
  parsed = urllib.parse.urlparse('//' + url)
  if not parsed.hostname:
    return _make_proxy_error(correlation_id, "Invalid URL format", 400)

  # Strict whitelist validation against allowed ADS-B servers in config
  if url not in valid['adsbs']:
    app.logger.warning(f"[{correlation_id}] Unauthorized ADS-B server: {url}")
    return _make_proxy_error(correlation_id, "ADS-B server not authorized", 403)

  tar1090_https = config_data.get('map', {}).get('tar1090_https', False)
  preferred = 'https' if tar1090_https else 'http'
  return _handle_proxy_errors(
    correlation_id, "ADS-B", url,
    fetch_proxied_url, host=url, path='data/aircraft.json',
    preferred_scheme=preferred)


if __name__ == "__main__":
  app.run()